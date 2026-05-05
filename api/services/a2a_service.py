"""
A2A Service — Bridges the A2A protocol surface to Enclave's workflow engine
and chat router.

Concrete responsibilities:
  - Maintain in-memory and on-disk task state (mirrors workflow_engine's
    persistence layout under data/a2a/<task_id>/)
  - Translate inbound A2A Messages into either a chat completion or a
    workflow seed
  - Run work in a background asyncio task so the SSE stream can yield
    intermediate state updates
  - Expose an async iterator of streaming events for tasks/sendSubscribe

Cancellation: tasks check a per-task asyncio.Event between steps; the chat
path is single-shot and only honors cancel before the LLM call returns.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterator, Dict, List, Optional

from ..logging_config import logger
from ..models.a2a_models import (
    Artifact,
    DataPart,
    Message,
    MessageRole,
    Task,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
    TextPart,
    parse_skill_id,
)


# Where task state JSON is mirrored. Workflow runs already live under
# data/workflows/; A2A keeps a thin index of tasks separately so that
# chat-mode tasks (which don't have a workflow run) are also persisted.
TASK_DATA_DIR = Path("./data/a2a")


@dataclass
class _TaskRuntime:
    """In-memory companion to a Task while it is running."""

    task: Task
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    queue: "asyncio.Queue[TaskStatusUpdateEvent | TaskArtifactUpdateEvent]" = field(
        default_factory=asyncio.Queue
    )
    runner: Optional[asyncio.Task] = None


class A2AService:
    """A2A task lifecycle manager."""

    def __init__(self, ollama_service, workflow_engine, plugin_service=None):
        self.ollama = ollama_service
        self.workflows = workflow_engine
        self.plugins = plugin_service
        self._runtime: Dict[str, _TaskRuntime] = {}
        TASK_DATA_DIR.mkdir(parents=True, exist_ok=True)

    # ── Public surface ──────────────────────────────────────────────────

    async def send(
        self,
        skill_id: str,
        message: Message,
        task_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> Task:
        """Synchronously execute a task and return the final Task."""
        task = self._create_task(task_id, session_id, message)
        await self._run_task(task, skill_id, message)
        return task

    async def send_subscribe(
        self,
        skill_id: str,
        message: Message,
        task_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> AsyncIterator[TaskStatusUpdateEvent | TaskArtifactUpdateEvent]:
        """
        Kick off a task in the background and yield SSE events until the
        terminal status (completed/failed/canceled) is observed.
        """
        task = self._create_task(task_id, session_id, message)
        rt = self._runtime[task.id]
        rt.runner = asyncio.create_task(self._run_task(task, skill_id, message))

        async def _stream():
            while True:
                event = await rt.queue.get()
                yield event
                # Terminate when we see the final status frame.
                if (
                    isinstance(event, TaskStatusUpdateEvent)
                    and event.final
                ):
                    break

        return _stream()

    def get(self, task_id: str) -> Optional[Task]:
        rt = self._runtime.get(task_id)
        if rt is not None:
            return rt.task
        return self._load_persisted(task_id)

    async def cancel(self, task_id: str) -> Task:
        rt = self._runtime.get(task_id)
        if rt is None:
            persisted = self._load_persisted(task_id)
            if persisted is None:
                raise KeyError(task_id)
            # Already-finished tasks aren't cancelable.
            raise ValueError("task already terminal")
        if rt.task.status.state in {
            TaskState.COMPLETED,
            TaskState.FAILED,
            TaskState.CANCELED,
        }:
            raise ValueError("task already terminal")
        rt.cancel_event.set()
        # Update state immediately so callers polling get() see it.
        rt.task.status = TaskStatus(state=TaskState.CANCELED)
        await self._emit_status(rt, final=True)
        self._persist(rt.task)
        return rt.task

    # ── Internals ───────────────────────────────────────────────────────

    def _create_task(
        self,
        task_id: Optional[str],
        session_id: Optional[str],
        first_message: Message,
    ) -> Task:
        task = Task(
            id=task_id or str(__import__("uuid").uuid4()),
            session_id=session_id,
            status=TaskStatus(state=TaskState.SUBMITTED),
            history=[first_message],
        )
        self._runtime[task.id] = _TaskRuntime(task=task)
        self._persist(task)
        return task

    async def _run_task(self, task: Task, skill_id: str, message: Message) -> None:
        rt = self._runtime[task.id]
        try:
            kind, target = parse_skill_id(skill_id)
        except ValueError as exc:
            await self._fail(rt, str(exc))
            return

        # Move to working
        rt.task.status = TaskStatus(state=TaskState.WORKING)
        await self._emit_status(rt)

        try:
            if rt.cancel_event.is_set():
                await self._cancel_inflight(rt)
                return

            if kind == "chat":
                await self._run_chat(rt, message)
            elif kind == "workflow":
                await self._run_workflow(rt, target or "", message)
            else:
                await self._fail(rt, f"unsupported skill kind: {kind}")
                return

            if rt.cancel_event.is_set():
                await self._cancel_inflight(rt)
                return

            rt.task.status = TaskStatus(state=TaskState.COMPLETED)
            await self._emit_status(rt, final=True)
            self._persist(rt.task)
        except Exception as exc:
            logger.exception("a2a task %s crashed", rt.task.id)
            await self._fail(rt, f"internal error: {exc}")

    async def _run_chat(self, rt: _TaskRuntime, message: Message) -> None:
        """Run a single-turn chat completion via OllamaService."""
        prompt = message.text()
        # Use Ollama's default model selection by passing the configured
        # default; the chat router picks a model per request, but A2A's
        # chat skill is intentionally simple and uses the platform default.
        from os import getenv

        model = getenv("DEFAULT_MODEL", "mistral")
        # OllamaService.chat is sync; run in thread to avoid blocking loop.
        result = await asyncio.to_thread(
            self.ollama.chat,
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=2048,
        )
        artifact = Artifact(
            name="response",
            parts=[TextPart(text=result.get("content", ""))],
            index=0,
            last_chunk=True,
            metadata={
                "model": model,
                "prompt_tokens": result.get("prompt_eval_count", 0),
                "completion_tokens": result.get("eval_count", 0),
            },
        )
        rt.task.artifacts.append(artifact)
        rt.task.history.append(
            Message(role=MessageRole.AGENT, parts=[TextPart(text=result.get("content", ""))])
        )
        await rt.queue.put(TaskArtifactUpdateEvent(id=rt.task.id, artifact=artifact))

    async def _run_workflow(self, rt: _TaskRuntime, workflow_id: str, message: Message) -> None:
        """Map an A2A workflow skill invocation onto WorkflowEngine.run."""
        from ..exceptions import WorkflowValidationError

        # Seed sourcing: structured DataPart is preferred; otherwise text
        # becomes seed.input. Workflows that need richer seeds should send
        # DataPart.
        seed: Dict = {}
        for part in message.parts:
            if isinstance(part, DataPart):
                seed.update(part.data)
        text_seed = message.text()
        if text_seed and "input" not in seed:
            seed["input"] = text_seed

        yaml_path = f"./workflows/{workflow_id}.yaml"
        try:
            defn = await asyncio.to_thread(self.workflows.load, yaml_path)
        except FileNotFoundError:
            await self._fail(rt, f"workflow not found: {workflow_id}")
            return

        try:
            await asyncio.to_thread(
                self.workflows.validate, defn, list(seed.keys()) or None
            )
        except WorkflowValidationError as exc:
            await self._fail(rt, f"workflow validation failed: {exc}")
            return

        run = await asyncio.to_thread(self.workflows.run, defn, seed)

        # Each step's workspace becomes one Artifact. This gives external
        # callers the same observability surface the UI's context inspector
        # already exposes.
        for idx, step_result in enumerate(run.step_results):
            step_outputs = run.context.workspace.get(step_result.step_id, {})
            artifact = Artifact(
                name=step_result.step_id,
                description=f"step {step_result.step_id} output",
                parts=[DataPart(data=step_outputs)],
                index=idx,
                last_chunk=(idx == len(run.step_results) - 1),
                metadata={
                    "model": step_result.model_used,
                    "duration_seconds": step_result.duration_seconds,
                    "tokens": step_result.token_count,
                    "status": step_result.status,
                    "workflow_run_id": run.run_id,
                },
            )
            rt.task.artifacts.append(artifact)
            await rt.queue.put(TaskArtifactUpdateEvent(id=rt.task.id, artifact=artifact))

        rt.task.metadata = (rt.task.metadata or {}) | {
            "workflow_run_id": run.run_id,
            "workflow_status": run.status,
        }

        if run.status == "failed":
            await self._fail(rt, run.error or "workflow failed")

    # ── State transitions ──────────────────────────────────────────────

    async def _emit_status(self, rt: _TaskRuntime, final: bool = False) -> None:
        await rt.queue.put(
            TaskStatusUpdateEvent(id=rt.task.id, status=rt.task.status, final=final)
        )

    async def _fail(self, rt: _TaskRuntime, reason: str) -> None:
        rt.task.status = TaskStatus(
            state=TaskState.FAILED,
            message=Message(role=MessageRole.AGENT, parts=[TextPart(text=reason)]),
        )
        await self._emit_status(rt, final=True)
        self._persist(rt.task)

    async def _cancel_inflight(self, rt: _TaskRuntime) -> None:
        rt.task.status = TaskStatus(state=TaskState.CANCELED)
        await self._emit_status(rt, final=True)
        self._persist(rt.task)

    # ── Persistence ────────────────────────────────────────────────────

    def _task_path(self, task_id: str) -> Path:
        return TASK_DATA_DIR / task_id / "task.json"

    def _persist(self, task: Task) -> None:
        path = self._task_path(task.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.write_text(
                json.dumps(task.model_dump(by_alias=True, mode="json"), indent=2, default=str)
            )
        except OSError as exc:
            logger.warning("failed to persist a2a task %s: %s", task.id, exc)

    def _load_persisted(self, task_id: str) -> Optional[Task]:
        path = self._task_path(task_id)
        if not path.exists():
            return None
        try:
            return Task.model_validate_json(path.read_text())
        except Exception as exc:
            logger.warning("failed to load a2a task %s: %s", task_id, exc)
            return None

    # ── Discovery (used by Agent Card builder) ─────────────────────────

    def discoverable_skills(self) -> List[Dict]:
        """Return skill descriptors for the Agent Card."""
        from ..models.a2a_models import (
            CHAT_SKILL_ID,
            workflow_skill_id,
        )

        skills: List[Dict] = [
            {
                "id": CHAT_SKILL_ID,
                "name": "Chat",
                "description": "Single-turn chat with the platform's default model.",
                "tags": ["chat", "llm"],
                "input_modes": ["text"],
                "output_modes": ["text"],
            }
        ]
        try:
            workflows = self.workflows.list_workflows()
        except Exception as exc:
            logger.warning("failed to enumerate workflows for agent card: %s", exc)
            workflows = []
        for wf in workflows:
            skills.append(
                {
                    "id": workflow_skill_id(wf["id"]),
                    "name": wf["name"],
                    "description": wf.get("description") or f"Workflow {wf['id']}",
                    "tags": ["workflow", "multi-agent"],
                    "input_modes": ["text", "data"],
                    "output_modes": ["data"],
                }
            )
        return skills
