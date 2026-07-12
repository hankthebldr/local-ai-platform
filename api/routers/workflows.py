"""
Workflow Router — API endpoints for multi-agent workflow management

Endpoints:
  GET  /api/workflows              — List available workflow definitions
  POST /api/workflows/validate     — Validate a workflow definition
  POST /api/workflows/run          — Execute a workflow with seed data
  POST /api/workflows/save         — Persist a definition as workflows/{id}.yaml
  GET  /api/workflows/runs         — List recent workflow runs
  GET  /api/workflows/runs/{id}    — Get a specific run's status and results
  GET  /api/workflows/runs/{id}/artifacts/{step_id} — Get a step's output
  GET  /api/workflows/{id}         — Full parsed WorkflowDefinition
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

import yaml
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..logging_config import logger
from ..services.ollama_service import OllamaService
from ..services.workflow_engine import WorkflowEngine
from ..exceptions import WorkflowValidationError

router = APIRouter(prefix="/api/workflows", tags=["workflows"])

_TERMINAL_STATUSES = {"completed", "failed", "canceled"}


async def _sse_generator(bus, run_id: str, since: int):
    """Async generator that replays the run log then tails live events via subscribe().

    Yields SSE-formatted strings. Emits stream.end and returns after the first
    terminal run.status event so the response completes for finished runs.
    """
    existing = bus.read_log(run_id, since=since)
    last_seq = existing[-1].seq if existing else since
    yield f"event: stream.hello\ndata: {json.dumps({'last_seq': last_seq})}\n\n"

    async for ev in bus.subscribe(run_id, since=since):
        payload = json.dumps(ev.model_dump(mode="json"))
        yield f"id: {ev.seq}\nevent: {ev.type}\ndata: {payload}\n\n"
        if ev.type == "run.status" and ev.data.get("status") in _TERMINAL_STATUSES:
            yield "event: stream.end\ndata: {}\n\n"
            return


OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
WORKFLOWS_DIR = os.getenv("WORKFLOWS_DIR", "./workflows")


def get_ollama_service() -> OllamaService:
    """Get or create OllamaService instance"""
    return OllamaService(OLLAMA_HOST)


def _collect_step_kinds(defn) -> Dict[str, str]:
    """Walk a WorkflowDefinition and return {step_id: kind} for every step,
    including children of composite kinds (parallel branches/gather, loop body,
    ralph body, orchestrator workers). Used to decorate step_results in API
    responses so the UI can show a kind chip without re-parsing YAML.
    """
    mapping: Dict[str, str] = {}

    def _walk(step):
        mapping[step.id] = step.kind
        for child in getattr(step, "branches", None) or []:
            _walk(child)
        gather = getattr(step, "gather", None)
        if gather is not None:
            _walk(gather)
        for child in getattr(step, "body", None) or []:
            _walk(child)
        for worker in (getattr(step, "workers", None) or {}).values():
            _walk(worker)

    for step in defn.steps:
        _walk(step)
    return mapping


def _decorate_step_results(
    step_results: List[Dict[str, Any]], kinds: Dict[str, str]
) -> List[Dict[str, Any]]:
    """Add `kind` to each step_result projection. Unknown step_ids (composite
    children whose synthetic ids aren't in the YAML) default to 'llm' so the
    UI can render a chip uniformly. Idempotent: pre-set kinds win."""
    out = []
    for r in step_results:
        merged = dict(r)
        if "kind" not in merged:
            merged["kind"] = kinds.get(merged.get("step_id"), "llm")
        out.append(merged)
    return out


def _try_kinds_for_workflow_id(
    engine: "WorkflowEngine", workflow_id: Optional[str]
) -> Dict[str, str]:
    """Best-effort kind lookup by workflow_id. Returns {} when the workflow
    YAML can't be found (renamed/deleted/private overlay shifted) — the UI
    just renders no chips in that case."""
    if not workflow_id:
        return {}
    try:
        yaml_path = engine.resolve_workflow_path(workflow_id, WORKFLOWS_DIR)
        if not yaml_path:
            return {}
        defn = engine.load(yaml_path)
        return _collect_step_kinds(defn)
    except Exception as exc:  # noqa: BLE001
        logger.debug("kind-decoration skipped for %s: %s", workflow_id, exc)
        return {}


def get_engine() -> WorkflowEngine:
    """Get or create WorkflowEngine instance"""
    return WorkflowEngine(get_ollama_service())


# ── Request/Response Models ────────────────────────────────────────────────


class WorkflowRunRequest(BaseModel):
    """Request to execute a workflow"""

    workflow_id: Optional[str] = None  # ID to load from workflows/ dir
    definition: Optional[Dict[str, Any]] = None  # inline definition
    seed: Dict[str, Any] = Field(default_factory=dict)


class WorkflowValidateRequest(BaseModel):
    """Request to validate a workflow definition"""

    definition: Dict[str, Any]
    seed_keys: Optional[List[str]] = None


class ComposerAssistRequest(BaseModel):
    """Phase 2c.3 — partial AgentStep the composer is editing.

    Sent on every field edit so the composer can render "logical companion"
    suggestions inline. Tolerant of incomplete shape: we only need
    ``role`` / ``tools`` / ``skills`` / ``archetype`` to compute
    suggestions; the rest is ignored.
    """

    step: Dict[str, Any]


class WorkflowSaveRequest(BaseModel):
    """Request to persist a workflow definition as YAML."""

    definition: Dict[str, Any]
    overwrite: bool = False  # explicit consent to clobber an existing file


class ApprovalRequest(BaseModel):
    """Operator decision for a paused HITL approval gate (Task 13).

    A `kind: code` step with an approval policy pauses the run at
    ``status="awaiting_approval"`` with a ``pending_gate``. The operator
    resolves it by POSTing one of:
      * approve — run the proposed code as-is.
      * edit    — run ``edited_code`` instead (must be supplied).
      * reject  — fail the step; ``reason`` is surfaced in the error.
    """

    action: Literal["approve", "edit", "reject"]
    edited_code: Optional[str] = None
    reason: Optional[str] = None


# ── Endpoints ──────────────────────────────────────────────────────────────


@router.get("")
async def list_workflows():
    """List all available workflow definitions from the workflows/ directory"""
    engine = get_engine()
    return engine.list_workflows(WORKFLOWS_DIR)


@router.post("/validate")
async def validate_workflow(req: WorkflowValidateRequest):
    """Validate a workflow definition without executing it.

    Phase 5 — when the workflow declares ``required_plugins`` /
    ``required_mcps`` or any step's ``tools`` / ``skills`` list, the
    response carries extension warnings (registered-but-unreachable MCP,
    missing-skill plugin) so operators can fix them before run. Errors
    still raise 422.
    """
    engine = get_engine()
    try:
        defn = engine.load_from_dict(req.definition)
        engine.validate(defn, seed_keys=req.seed_keys)
    except WorkflowValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))

    body = {"valid": True, "workflow_id": defn.id, "steps": len(defn.steps)}
    ext = getattr(engine, "_last_extension_result", None)
    if ext is not None and ext.has_warnings:
        body["warnings"] = {
            "plugin": ext.plugin_warnings,
            "mcp": ext.mcp_warnings,
            "skill": ext.skill_warnings,
        }
    # Phase 2b — co-scheduler optimization recommendations. Always non-fatal
    # at this point (any errors would have raised 422 above); the composer
    # renders these inline so the operator can decide whether to apply.
    cs = getattr(engine, "_last_co_scheduling_result", None)
    if cs is not None and cs.recommendations:
        body["optimization_recommendations"] = [
            r.model_dump() for r in cs.recommendations
        ]
    return body


@router.post("/composer/assist")
async def composer_assist(req: ComposerAssistRequest):
    """Phase 2c.3 — suggest archetype companions for a partial step.

    The composer calls this on every field edit. Given a partial
    AgentStep (any subset of ``role`` / ``tools`` / ``skills`` /
    ``archetype``), returns the inferred archetype + the
    companion-MCPs / companion-skills the operator hasn't declared yet +
    a suggested role (only when the step has no role of its own).

    Tolerant: malformed step payloads return an empty-suggestion shape
    rather than a 422, so the composer keeps working as the user types.
    """
    from ..services.archetypes import suggest_companions

    raw = req.step or {}
    # Coerce just enough of the payload into AgentStep shape — the helper only
    # consults role / tools / skills / archetype. We provide harmless defaults
    # for the required fields (id / name / outputs) so partial composer drafts
    # validate.
    # Bypass the llm-kind shape requirement (needs prompt/system_prompt) by
    # supplying a placeholder; suggest_companions only reads role / tools /
    # skills / archetype so the placeholder never reaches the operator.
    skeleton: Dict[str, Any] = {
        "id": raw.get("id") or "draft",
        "name": raw.get("name") or "draft",
        "outputs": raw.get("outputs") or ["draft"],
        "system_prompt": raw.get("system_prompt") or "draft",
    }
    for key in ("role", "tools", "skills", "archetype", "model"):
        if key in raw:
            skeleton[key] = raw[key]
    try:
        from ..models.workflow_models import AgentStep

        step = AgentStep.model_validate(skeleton)
    except Exception:
        return {
            "inferred_archetype": None,
            "suggested_role": None,
            "suggested_mcps": [],
            "suggested_skills": [],
            "warnings": [],
        }
    return suggest_companions(step)


@router.post("/save")
async def save_workflow(req: WorkflowSaveRequest):
    """Persist a validated workflow definition to workflows/{id}.yaml.

    Used by the no-code composer's Save action. Validates the definition
    first; refuses to clobber an existing file unless overwrite=true. The
    workflow_id is taken from the definition payload itself (no path
    parameter, so traversal is structurally impossible).
    """
    engine = get_engine()
    # Validate before writing; engine.load_from_dict raises on bad input.
    try:
        defn = engine.load_from_dict(req.definition)
        engine.validate(defn)
    except WorkflowValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # Defense in depth: re-check the workflow id is filename-safe even
    # though Pydantic already enforced its shape.
    wf_id = defn.id
    if not wf_id or not all(c.isalnum() or c in "_-" for c in wf_id):
        raise HTTPException(
            status_code=400, detail="invalid workflow id (alphanum/_/- only)"
        )

    workflows_root = Path(WORKFLOWS_DIR).resolve()
    workflows_root.mkdir(parents=True, exist_ok=True)
    target = (workflows_root / f"{wf_id}.yaml").resolve()
    try:
        target.relative_to(workflows_root)
    except ValueError:
        raise HTTPException(status_code=400, detail="path outside workflows directory")

    if target.exists() and not req.overwrite:
        raise HTTPException(
            status_code=409,
            detail=f"workflow '{wf_id}' already exists; pass overwrite=true to replace",
        )

    # Round-trip through Pydantic so we serialize the validated, normalized
    # form rather than whatever shape the client sent.
    yaml_text = yaml.safe_dump(
        defn.model_dump(mode="json", exclude_none=True),
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
    )
    target.write_text(yaml_text, encoding="utf-8")
    logger.info(f"Saved workflow '{wf_id}' to {target}")
    return {
        "saved": True,
        "workflow_id": wf_id,
        "path": (
            str(target.relative_to(Path.cwd()))
            if target.is_relative_to(Path.cwd())
            else str(target)
        ),
        "bytes": len(yaml_text),
    }


# ── Single-step ad-hoc test ──────────────────────────────────────────────


class StepTestRequest(BaseModel):
    """Run a single composer step against a free-form user prompt.

    The composer wires the dashboard chat input to this endpoint when a
    node is selected, so the operator can iterate on one step's
    `system_prompt` + `model`/`role` without saving + running the whole
    workflow. The request carries a step *definition* (not a step id) so
    unsaved canvas edits flow through unmodified.
    """

    step: Dict[str, Any]
    user_message: str
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    # LB1-U1 — explicit skill refs ("<plugin_id>.<skill_id>") injected
    # router-side before the model call, mirroring the skill_injector
    # builtin's explicit-mode semantics. Optional and additive: absent or
    # empty leaves test-step behavior byte-identical to before.
    skills: Optional[List[str]] = None


def _apply_skill_injection(
    system_prompt: str, user_message: str, skill_refs: List[str]
) -> tuple[str, str, List[Dict[str, Any]]]:
    """Router-side skill injection for test-step (engine files untouched).

    Delegates to the SkillInjectorHook builtin itself (explicit mode) on a
    synthetic HookContext, so the injected text can never drift from what a
    real workflow run produces — parity is pinned by
    tests/parity/test_skill_injection_parity.py. Returns the augmented
    (system, user) pair plus the SkillActivation records as dicts. Never
    raises: the builtin swallows its own failures (action=continue).
    """
    from types import SimpleNamespace

    from ..hooks.builtins.skill_injector import SkillInjectorHook
    from ..services.hook_bus import HookContext
    from ..services.prompt_composer import ComposedPrompt

    prompt = ComposedPrompt(system=system_prompt, user=user_message)
    result_handle = SimpleNamespace(skills_activated=[], extension_overhead_ms=0.0)
    ctx = HookContext(
        step=SimpleNamespace(id="test-step", skills=list(skill_refs)),
        prompt=prompt,
        step_result=result_handle,
    )
    SkillInjectorHook(mode="explicit")(ctx)
    activations = [a.model_dump() for a in result_handle.skills_activated]
    return prompt.system, prompt.user, activations


@router.post("/test-step")
async def test_step(req: StepTestRequest):
    from ..services.model_resolver import ModelResolver
    from ..exceptions import APIError

    step = req.step or {}
    system_prompt = (step.get("system_prompt") or "").strip()
    if not system_prompt:
        raise HTTPException(
            status_code=400,
            detail="step.system_prompt is required for test-step",
        )

    ollama = get_ollama_service()
    resolver = ModelResolver(ollama)
    try:
        resolved_model = resolver.resolve(
            model=step.get("model") or None,
            role=step.get("role") or None,
            default_role="general",
        )
    except APIError:
        raise

    user_message = req.user_message
    skills_activated: List[Dict[str, Any]] = []
    if req.skills:
        system_prompt, user_message, skills_activated = _apply_skill_injection(
            system_prompt, user_message, req.skills
        )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]
    temperature = req.temperature if req.temperature is not None else 0.7
    max_tokens = req.max_tokens if req.max_tokens is not None else 2048

    try:
        result = ollama.chat(
            model=resolved_model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except APIError:
        raise

    response = {
        "step_id": step.get("id"),
        "model": resolved_model,
        "content": result.get("content", ""),
        "usage": {
            "prompt_tokens": result.get("prompt_eval_count", 0),
            "completion_tokens": result.get("eval_count", 0),
            "total_tokens": (
                result.get("prompt_eval_count", 0) + result.get("eval_count", 0)
            ),
        },
    }
    # Only-add: the key appears only when the caller asked for injection, so
    # pre-existing test-step consumers see an unchanged payload.
    if req.skills:
        response["skills_activated"] = skills_activated
    # Surface model_fallback when the pinned model wasn't found (mirrors
    # /api/agents/{id}/chat shape so the dashboard can reuse its banner).
    pinned = step.get("model") or None
    if pinned and resolved_model != pinned:
        response["model_fallback"] = {
            "requested": pinned,
            "resolved": resolved_model,
            "reason": (
                f"Step's pinned model '{pinned}' is not installed. "
                f"Resolved to '{resolved_model}'. "
                f"Pull '{pinned}' for the step's preferred model."
            ),
        }
    return response


@router.post("/run")
async def run_workflow(req: WorkflowRunRequest, background_tasks: BackgroundTasks):
    """
    Execute a workflow with seed data.

    Provide either workflow_id (loads from workflows/ dir) or
    definition (inline YAML-equivalent dict).
    """
    engine = get_engine()

    # Load definition
    if req.definition:
        defn = engine.load_from_dict(req.definition)
    elif req.workflow_id:
        yaml_path = engine.resolve_workflow_path(req.workflow_id, WORKFLOWS_DIR)
        if not yaml_path:
            raise HTTPException(
                status_code=404,
                detail=f"Workflow '{req.workflow_id}' not found in public or private overlay",
            )
        defn = engine.load(yaml_path)
    else:
        raise HTTPException(
            status_code=400,
            detail="Provide either 'workflow_id' or 'definition'",
        )

    # Validate
    try:
        engine.validate(defn, seed_keys=list(req.seed.keys()) if req.seed else None)
    except WorkflowValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # Execute synchronously (future: background task option)
    run = engine.run(defn, seed=req.seed)

    return {
        "run_id": run.run_id,
        "workflow_id": run.workflow_id,
        "status": run.status,
        "started_at": str(run.started_at),
        "completed_at": str(run.completed_at),
        "step_results": _decorate_step_results(
            [
                {
                    "step_id": r.step_id,
                    "status": r.status,
                    "model_used": r.model_used,
                    "duration_seconds": r.duration_seconds,
                    "token_count": r.token_count,
                    "retries": r.retries,
                    "error": r.error,
                }
                for r in run.step_results
            ],
            _collect_step_kinds(defn),
        ),
        # Expose the three-layer context so the UI can render a context
        # inspector (seed = immutable input, workspace = per-step outputs,
        # shared = cross-cutting state).
        "context": {
            "seed": run.context.seed,
            "workspace": run.context.workspace,
            "shared": run.context.shared,
        },
        "error": run.error,
    }


@router.post("/run-async")
async def run_workflow_async(
    req: WorkflowRunRequest, background_tasks: BackgroundTasks
):
    """
    Kick off a workflow run in the background and return the run_id
    immediately. The caller polls /api/workflows/runs/{run_id} to watch
    step-by-step progress as the engine checkpoints after every step.

    Use this when you want live UI updates. The sync /run endpoint is
    still the right call for short workflows that return quickly.
    """
    import uuid as _uuid
    from datetime import datetime as _dt
    from ..models.workflow_models import WorkflowRun, WorkflowContext

    engine = get_engine()

    if req.definition:
        defn = engine.load_from_dict(req.definition)
    elif req.workflow_id:
        yaml_path = engine.resolve_workflow_path(req.workflow_id, WORKFLOWS_DIR)
        if not yaml_path:
            raise HTTPException(
                status_code=404,
                detail=f"Workflow '{req.workflow_id}' not found in public or private overlay",
            )
        defn = engine.load(yaml_path)
    else:
        raise HTTPException(
            status_code=400,
            detail="Provide either 'workflow_id' or 'definition'",
        )

    try:
        engine.validate(defn, seed_keys=list(req.seed.keys()) if req.seed else None)
    except WorkflowValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # Pre-create the run id + checkpoint a "queued" record so the client
    # can immediately poll /runs/{id}. The engine generates its own
    # internal run_id otherwise; we hand it in so the URL is stable.
    run_id = str(_uuid.uuid4())
    ctx = WorkflowContext(seed=dict(req.seed or {}))
    placeholder = WorkflowRun(
        run_id=run_id,
        workflow_id=defn.id,
        status="queued",
        context=ctx,
        started_at=_dt.utcnow(),
    )
    try:
        engine._checkpoint(placeholder)
    except Exception:
        pass

    def _run_in_background():
        from ..logging_config import logger as _logger

        try:
            engine.run(defn, seed=req.seed, run_id=run_id)
        except TypeError:
            # Older engine signature without run_id kwarg — fall back and
            # accept the engine's auto-generated id. The pre-checkpoint
            # placeholder is then orphaned (harmless; cleanup elsewhere).
            engine.run(defn, seed=req.seed)
        except Exception as e:
            _logger.error(f"Background workflow run {run_id} failed: {e}")

    background_tasks.add_task(_run_in_background)
    return {
        "run_id": run_id,
        "workflow_id": defn.id,
        "status": "queued",
        "poll_url": f"/api/workflows/runs/{run_id}",
    }


@router.get("/runs")
async def list_runs(limit: int = 20):
    """List recent workflow runs"""
    engine = get_engine()
    return engine.list_runs(limit=limit)


@router.get("/runs/{run_id}")
async def get_run(run_id: str):
    """Get full details of a specific workflow run"""
    engine = get_engine()
    run_data = engine.get_run(run_id)
    if not run_data:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    # Decorate step_results with their kind so the UI's Runs view can render
    # a per-step kind chip without re-fetching the workflow YAML. Best-effort
    # — if the workflow YAML can't be located, step_results are returned as-is.
    kinds = _try_kinds_for_workflow_id(engine, run_data.get("workflow_id"))
    if kinds and isinstance(run_data.get("step_results"), list):
        run_data = dict(run_data)
        run_data["step_results"] = _decorate_step_results(
            run_data["step_results"], kinds
        )
    return run_data


@router.get("/runs/{run_id}/stream")
async def stream_run(run_id: str, request: Request, since: int = 0):
    """Live SSE stream of a run's events. Honors Last-Event-ID / ?since= for resume."""
    from ..services.run_event_bus import get_run_event_bus

    bus = get_run_event_bus()

    last_event_id = request.headers.get("last-event-id")
    if last_event_id and last_event_id.isdigit():
        since = int(last_event_id)

    return StreamingResponse(
        _sse_generator(bus, run_id, since),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/runs/{run_id}/resume")
async def resume_run(run_id: str):
    """
    Resume a checkpointed workflow run that was interrupted mid-flight.

    Idempotent for terminal runs (returns the existing snapshot unchanged).
    For runs left in "running" state by a crash, picks up at the first
    step that doesn't have a "completed" StepResult.
    """
    engine = get_engine()
    try:
        run = engine.resume(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return {
        "run_id": run.run_id,
        "workflow_id": run.workflow_id,
        "status": run.status,
        "started_at": str(run.started_at),
        "completed_at": str(run.completed_at) if run.completed_at else None,
        "step_results": _decorate_step_results(
            [
                {
                    "step_id": r.step_id,
                    "status": r.status,
                    "model_used": r.model_used,
                    "duration_seconds": r.duration_seconds,
                    "token_count": r.token_count,
                    "retries": r.retries,
                    "error": r.error,
                }
                for r in run.step_results
            ],
            _try_kinds_for_workflow_id(engine, run.workflow_id),
        ),
        "context": {
            "seed": run.context.seed,
            "workspace": run.context.workspace,
            "shared": run.context.shared,
        },
        "error": run.error,
        "resumed": True,
    }


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: str):
    """Request cancellation of an in-flight workflow run.

    Cooperative: the engine checks for cancellation at each step
    boundary, so an LLM call already in flight will complete before
    the run terminates. Calling this on a terminal run is a no-op
    (returns the current status).
    """
    engine = get_engine()
    # Surface 404 for runs we've never seen; let other errors propagate.
    snapshot = engine.get_run(run_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="run not found")
    current = (snapshot.get("status") or "").lower()
    if current in {"completed", "failed", "canceled", "error"}:
        return {
            "run_id": run_id,
            "status": current,
            "accepted": False,
            "reason": f"run already terminal: {current}",
        }
    newly_marked = engine.request_cancel(run_id)
    return {
        "run_id": run_id,
        "status": "cancel_requested",
        "accepted": newly_marked,
        "reason": None if newly_marked else "cancel already pending",
    }


def _valid_run_id(run_id: str) -> bool:
    """Run ids are engine-minted uuid4 hex/strings. Constrain to a filename-
    safe charset so a crafted id can never traverse out of the run store
    (``get_run`` joins it onto DATA_DIR). Mirrors the ``/{workflow_id}`` guard.
    """
    return bool(run_id) and all(c.isalnum() or c in "_-" for c in run_id)


@router.post("/runs/{run_id}/resume-from-failed")
def resume_from_failed(run_id: str):
    """Re-dispatch a FAILED run from its first non-completed step (CH-1).

    Plain ``/resume`` is a no-op on a failed run — ``engine.resume`` short-
    circuits on terminal status (completed/failed/canceled) and returns the
    snapshot unchanged. The Fix&Resume loop needs the opposite: after the
    operator edits the failing step and re-saves, flip the run back to
    ``running`` (so ``resume`` re-executes) and resume. Modeled byte-for-byte
    on ``resolve_approval``'s flip-then-resume: set ``status="running"``,
    ``engine._checkpoint``, then ``engine.resume(run_id)`` with no explicit
    definition so the engine reloads the SAVED workflow yaml (picking up the
    operator's edits). Completed steps keep their earlier outputs; only the
    failed tail re-runs.

    Add-only. Idempotency mirrors ``cancel_run``/``resolve_approval``: a
    missing run is 404; a run that isn't failed is 409 (only failed runs can
    resume-from-failed — a completed/running run has nothing to re-dispatch).

    Composite step kinds (parallel/loop/ralph/orchestrator) resume natively —
    the engine executes them from the reloaded definition, and the composer's
    composite hydration (GP-1a / P0-2, landed) keeps the round-tripped yaml
    faithful, so composite Fix&Resume is safe.
    """
    if not _valid_run_id(run_id):
        raise HTTPException(status_code=400, detail="invalid run id")

    engine = get_engine()
    snapshot = engine.get_run(run_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="run not found")

    current = (snapshot.get("status") or "").lower()
    if current not in {"failed", "error"}:
        raise HTTPException(
            status_code=409,
            detail=f"run is not failed (status={current or 'unknown'}); "
            "only a failed run can resume-from-failed",
        )

    from ..models.workflow_models import WorkflowRun

    run = WorkflowRun.model_validate(snapshot)
    # Flip off the terminal state so resume() re-dispatches instead of short-
    # circuiting. Checkpoint first so a crash between flip and resume leaves a
    # consistent (running) snapshot the plain /resume path can still pick up.
    run.status = "running"
    engine._checkpoint(run)

    try:
        # definition=None → engine reloads ./workflows/<workflow_id>.yaml, so
        # the operator's just-saved edits to the failing step take effect.
        resumed = engine.resume(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return {
        "run_id": resumed.run_id,
        "workflow_id": resumed.workflow_id,
        "status": resumed.status,
        "error": resumed.error,
        "resumed_from_failed": True,
    }


@router.post("/runs/{run_id}/approvals/{gate_id}")
def resolve_approval(run_id: str, gate_id: str, body: ApprovalRequest):
    """Resolve a paused HITL approval gate, then resume the run (Task 13).

    Records the operator's decision onto the persisted ``pending_gate``,
    checkpoints, and resumes. On resume the engine re-dispatches the gated
    ``kind: code`` step; its executor reads the recorded decision and either
    runs (approve / edit) or fails the step (reject).

    Idempotent like ``cancel_run``: a missing run is 404; a gate that doesn't
    match ``gate_id`` or has already been decided is 409.

    Definition handling mirrors ``resume_run`` exactly — we call
    ``engine.resume(run_id)`` with no explicit definition, so the engine
    reloads the workflow from ``./workflows/<workflow_id>.yaml`` (resume needs
    the definition to re-dispatch the remaining steps).
    """
    engine = get_engine()
    snapshot = engine.get_run(run_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="run not found")

    gate = snapshot.get("pending_gate") or {}
    if not gate or gate.get("gate_id") != gate_id:
        raise HTTPException(
            status_code=409,
            detail="no pending gate with that id (already resolved?)",
        )
    if gate.get("decision") is not None:
        raise HTTPException(status_code=409, detail="gate already resolved")

    # An "edit" that supplies no code would silently fall back to running the
    # originally-proposed code (code.py only swaps when edited_code is truthy),
    # which is a surprising no-op. Reject it explicitly.
    if body.action == "edit" and not (body.edited_code or "").strip():
        raise HTTPException(
            status_code=422, detail="action 'edit' requires non-empty edited_code"
        )

    from ..models.workflow_models import WorkflowRun

    run = WorkflowRun.model_validate(snapshot)
    decision = {"approve": "approved", "edit": "edited", "reject": "rejected"}[
        body.action
    ]
    run.pending_gate.decision = decision
    run.pending_gate.reason = body.reason
    if body.action == "edit":
        run.pending_gate.edited_code = body.edited_code
    # Flip off the paused state so resume() re-dispatches the gated step.
    # "awaiting_approval" is already non-terminal (resume only short-circuits
    # on completed/failed/canceled), but "running" matches what resume() sets
    # internally and keeps the persisted snapshot consistent if resume throws.
    run.status = "running"
    engine._checkpoint(run)

    step_id = run.pending_gate.step_id

    from ..services.run_event_bus import get_run_event_bus

    get_run_event_bus().publish(
        run_id,
        "gate.resolved",
        {"gate_id": gate_id, "response": decision},
        step_id=step_id,
    )

    try:
        resumed = engine.resume(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return {
        "run_id": run_id,
        "gate_id": gate_id,
        "action": body.action,
        "status": resumed.status,
    }


@router.get("/runs/{run_id}/artifacts/{step_id}")
async def get_artifact(run_id: str, step_id: str):
    """Get a specific step's output artifacts"""
    engine = get_engine()
    run_data = engine.get_run(run_id)
    if not run_data:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

    workspace = run_data.get("context", {}).get("workspace", {})
    step_data = workspace.get(step_id)
    if not step_data:
        raise HTTPException(
            status_code=404,
            detail=f"No artifacts for step '{step_id}' in run '{run_id}'",
        )

    return {"step_id": step_id, "run_id": run_id, "outputs": step_data}


# ── Workflow memory inspection (Phase 4 stores: playbook / semantic / episodic) ───
#
# Lightweight read-only inspector for the durable memory stores written by
# kind=consolidate steps and read back via the $memory.* accessor. Powers the
# "Workflow Memory" panel in the Memory tab so operators can see what their
# ralph loops and consolidate steps have actually accumulated.


def _memory_store() -> "MemoryStore":  # noqa: F821
    """Construct a MemoryStore against the live MEMORY_DATA_DIR. We don't reuse
    the engine's store because the engine is request-scoped and constructing a
    bare store is essentially free (just a path)."""
    from ..services.memory_store import MemoryStore

    return MemoryStore()


@router.get("/memory/playbooks")
async def list_playbook_files():
    """List all playbook files with name + size + modified timestamp."""
    return {"playbooks": _memory_store().list_playbooks()}


@router.get("/memory/playbooks/{name}")
async def read_playbook_file(name: str):
    """Return the markdown body of a named playbook (or empty when missing)."""
    body = _memory_store().read_playbook(name)
    return {"name": name, "body": body, "exists": bool(body)}


@router.get("/memory/semantic")
async def list_semantic_files():
    """List all semantic-concept files with name + size + modified timestamp."""
    return {"semantic": _memory_store().list_semantic()}


@router.get("/memory/semantic/{concept}")
async def read_semantic_file(concept: str):
    """Return the markdown body of a named semantic concept."""
    body = _memory_store().read_semantic(concept)
    return {"name": concept, "body": body, "exists": bool(body)}


@router.get("/memory/episodic")
async def list_episodic_files():
    """List all episodic log keys with record count, size, modified timestamp."""
    return {"episodic": _memory_store().list_episodic()}


@router.get("/memory/episodic/{key}")
async def read_episodic_file(key: str, limit: int = 50):
    """Return the most recent `limit` records from an episodic log."""
    store = _memory_store()
    records = store.read_episodic(key, limit=limit)
    return {"name": key, "records": records, "count": len(records)}


# NOTE: Dynamic catch-all route kept at the END so /runs, /validate, /run, etc
# match their static handlers first. Moving this up shadows /api/workflows/runs.
@router.get("/{workflow_id}")
async def get_workflow(workflow_id: str):
    """Return the full parsed WorkflowDefinition (steps, hooks, prompts).

    Used by the UI to render the hook/role chips on the pipeline. The
    list endpoint returns only summaries; this one returns everything.

    Honors the private-overlay convention: a workflow with the same id
    in workflows-private/ wins over the public workflows/ copy. Lets
    the Runs tab render run details for private workflows without
    needing to ship them in the public repo.
    """

    if not workflow_id or not all(c.isalnum() or c in "_-" for c in workflow_id):
        raise HTTPException(status_code=400, detail="invalid workflow id")
    engine = get_engine()
    # Delegate the public/private overlay lookup to the engine — it owns
    # the resolution semantics and is shared by the run + resume code paths.
    yaml_path = engine.resolve_workflow_path(workflow_id, WORKFLOWS_DIR)
    if not yaml_path:
        raise HTTPException(
            status_code=404,
            detail=f"Workflow '{workflow_id}' not found in public or private overlay",
        )
    try:
        defn = engine.load(yaml_path)
    except FileNotFoundError:
        raise HTTPException(
            status_code=404, detail=f"workflow '{workflow_id}' not found"
        )
    except WorkflowValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return defn.model_dump(mode="json")


@router.get("/{workflow_id}/schedule-preview")
async def schedule_preview(workflow_id: str):
    """Phase 4 — return the per-tick schedule the engine would run on the
    current architecture, plus any feasibility issues.

    Read-only. Useful for operator inspection ("would these steps run in
    parallel on the BD790i?") and as the data source for a future Memory
    tab visualization. The engine itself is still sequential in Phase 4a;
    this endpoint reports what Phase 4b will do.
    """
    if not workflow_id or not all(c.isalnum() or c in "_-" for c in workflow_id):
        raise HTTPException(status_code=400, detail="invalid workflow id")
    engine = get_engine()
    yaml_path = engine.resolve_workflow_path(workflow_id, WORKFLOWS_DIR)
    if not yaml_path:
        raise HTTPException(
            status_code=404,
            detail=f"Workflow '{workflow_id}' not found in public or private overlay",
        )
    try:
        defn = engine.load(yaml_path)
    except WorkflowValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))

    from ..services.scheduler import Scheduler

    preview = Scheduler().preview(defn)
    return {
        "workflow_id": workflow_id,
        "arch_name": preview.arch_name,
        "ticks": preview.ticks,
        "feasibility_issues": [
            {
                "step_id": i.step_id,
                "est_size_gb": i.est_size_gb,
                "arch_budget_gb": i.arch_budget_gb,
                "reason": i.reason,
            }
            for i in preview.feasibility_issues
        ],
        "notes": preview.notes,
    }


@router.get("/{workflow_id}/runs")
async def list_workflow_runs(workflow_id: str, limit: int = 20):
    """Runs for ONE workflow, newest first (CH-1 read-model seam).

    The generic ``/runs`` endpoint lists every run across all workflows; this
    scopes to a single workflow so the composer can paint a last-run health
    chip and a workflow-scoped History without pulling the whole run index.
    Read-only, no engine mutation, no network egress.

    This is the canonical read-model seam the Operate plane's run-index unit
    (U5) is amended to CONSUME rather than re-implement its own ``/runs``
    filter (see the CH-1 ↔ U5 binding in the hardening spec).
    """
    if not workflow_id or not all(c.isalnum() or c in "_-" for c in workflow_id):
        raise HTTPException(status_code=400, detail="invalid workflow id")
    limit = max(1, min(int(limit), 200))
    engine = get_engine()
    # Over-scan then filter+cap: list_runs returns cross-workflow summaries, so
    # widen the scan window so a busy fleet doesn't starve this workflow's rows.
    scan = engine.list_runs(limit=max(limit * 10, 200))
    runs = [r for r in scan if r.get("workflow_id") == workflow_id][:limit]
    return {"workflow_id": workflow_id, "count": len(runs), "runs": runs}
