"""
A2A Service — Bridges the A2A protocol surface to Enclave's workflow engine
and chat router.

Concrete responsibilities:
  - Maintain in-memory and on-disk task state (mirrors workflow_engine's
    persistence layout under data/a2a/<task_id>/)
  - Translate inbound A2A Messages into either a chat completion or a
    workflow seed
  - Run work in a background asyncio task; broadcast intermediate events
    to every active SSE subscriber
  - Persist a per-task event log (events.jsonl) so disconnected clients
    can resume via tasks/resubscribe

Cancellation: tasks check a per-task asyncio.Event between steps; the chat
path is single-shot and only honors cancel before the LLM call returns.

Multi-subscriber model: each call to send_subscribe / resubscribe gets its
own asyncio.Queue. The runner emits to every queue + appends to a shared
in-memory event log + appends to the on-disk JSONL. Resubscribe replays
the log into a new queue, then attaches it for live tail.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator, Dict, List, Optional, Union

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


_Event = Union[TaskStatusUpdateEvent, TaskArtifactUpdateEvent]


@dataclass
class _TaskRuntime:
    """In-memory companion to a Task while it is running.

    `events` is the append-only log; `subscribers` is the live fan-out set.
    The runner appends to `events` and pushes to every queue in `subscribers`.
    Resubscribe replays `events` into a new queue, then registers it as a
    subscriber so the client gets the live tail.
    """

    task: Task
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    events: List[_Event] = field(default_factory=list)
    subscribers: List["asyncio.Queue[_Event]"] = field(default_factory=list)
    runner: Optional[asyncio.Task] = None
    terminal: bool = False


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
    ) -> AsyncIterator[_Event]:
        """
        Kick off a task in the background and yield SSE events until the
        terminal status (completed/failed/canceled) is observed.
        """
        task = self._create_task(task_id, session_id, message)
        rt = self._runtime[task.id]
        queue: "asyncio.Queue[_Event]" = asyncio.Queue()
        rt.subscribers.append(queue)
        rt.runner = asyncio.create_task(self._run_task(task, skill_id, message))
        return self._drain_queue_until_final(queue)

    async def resubscribe(self, task_id: str) -> AsyncIterator[_Event]:
        """
        Replay every event for a task and continue streaming live tail
        until terminal.

        - In-memory task: replay rt.events, then attach a new subscriber
          queue for the live tail.
        - Persisted-only task: replay events.jsonl from disk, then end.
        - Unknown task: raise KeyError so the router maps it to -32001.
        """
        rt = self._runtime.get(task_id)
        if rt is None:
            persisted = self._load_persisted_events(task_id)
            if persisted is None:
                raise KeyError(task_id)

            async def _replay_only() -> AsyncIterator[_Event]:
                for event in persisted:
                    yield event

            return _replay_only()

        queue: "asyncio.Queue[_Event]" = asyncio.Queue()
        # Snapshot the in-memory log; subsequent emissions go to `queue`
        # too via the subscribers list. Order: pre-existing events first,
        # then live tail. We register the subscriber BEFORE snapshotting
        # so we can't miss an event that lands between snapshot and attach.
        rt.subscribers.append(queue)
        snapshot = list(rt.events)

        async def _stream() -> AsyncIterator[_Event]:
            for event in snapshot:
                yield event
            if rt.terminal:
                # Drain anything that landed in `queue` after we registered
                # but is older than (or equal to) what's in snapshot. The
                # task is done; nothing new will arrive.
                try:
                    while True:
                        yield queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                return
            async for event in self._drain_queue_until_final(queue):
                # Skip events we already replayed from `snapshot`.
                if event in snapshot:
                    continue
                yield event

        return _stream()

    @staticmethod
    async def _drain_queue_until_final(
        queue: "asyncio.Queue[_Event]",
    ) -> AsyncIterator[_Event]:
        while True:
            event = await queue.get()
            yield event
            if isinstance(event, TaskStatusUpdateEvent) and event.final:
                break

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
        await self._broadcast(
            rt, TaskArtifactUpdateEvent(id=rt.task.id, artifact=artifact)
        )

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
            await self._broadcast(
                rt, TaskArtifactUpdateEvent(id=rt.task.id, artifact=artifact)
            )

        rt.task.metadata = (rt.task.metadata or {}) | {
            "workflow_run_id": run.run_id,
            "workflow_status": run.status,
        }

        if run.status == "failed":
            await self._fail(rt, run.error or "workflow failed")

    # ── State transitions ──────────────────────────────────────────────

    async def _emit_status(self, rt: _TaskRuntime, final: bool = False) -> None:
        event = TaskStatusUpdateEvent(
            id=rt.task.id, status=rt.task.status, final=final
        )
        await self._broadcast(rt, event)
        if final:
            rt.terminal = True

    async def _broadcast(self, rt: _TaskRuntime, event: _Event) -> None:
        """Append to event log + push to every subscriber + persist to disk."""
        rt.events.append(event)
        for queue in list(rt.subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # Subscribers use unbounded queues, but be defensive.
                pass
        self._append_event_log(rt.task.id, event)

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

    def _events_log_path(self, task_id: str) -> Path:
        return TASK_DATA_DIR / task_id / "events.jsonl"

    def _append_event_log(self, task_id: str, event: _Event) -> None:
        """Persist a single event so resubscribe-after-restart can replay."""
        path = self._events_log_path(task_id)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "kind": (
                    "status" if isinstance(event, TaskStatusUpdateEvent) else "artifact"
                ),
                "ts": datetime.now(timezone.utc).isoformat(),
                "event": event.model_dump(by_alias=True, mode="json"),
            }
            with path.open("a") as f:
                f.write(json.dumps(payload, default=str) + "\n")
        except OSError as exc:
            logger.warning("failed to append a2a event log %s: %s", task_id, exc)

    def _load_persisted_events(self, task_id: str) -> Optional[List[_Event]]:
        """
        Read the JSONL event log for a task no longer in memory.
        Returns None if the task has no log on disk; empty list if the log
        exists but is empty.
        """
        path = self._events_log_path(task_id)
        if not path.exists():
            return None
        events: List[_Event] = []
        try:
            with path.open() as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    record = json.loads(line)
                    payload = record.get("event") or {}
                    if record.get("kind") == "status":
                        events.append(TaskStatusUpdateEvent.model_validate(payload))
                    elif record.get("kind") == "artifact":
                        events.append(TaskArtifactUpdateEvent.model_validate(payload))
        except (OSError, json.JSONDecodeError, Exception) as exc:
            logger.warning("failed to read a2a event log %s: %s", task_id, exc)
            return None
        return events

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
