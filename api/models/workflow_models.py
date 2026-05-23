"""
Workflow Engine Data Models

Pydantic models for multi-agent workflow definitions, context management,
and execution tracking. Supports both v1 (system_prompt string) and v2
(structured `prompt` block) schema.
"""

import uuid
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

# ── Step Config ────────────────────────────────────────────────────────────


class StepConfig(BaseModel):
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    retries: Optional[int] = None
    retry_delay: Optional[int] = None
    timeout: Optional[int] = None
    # Phase 3 — per-step Ollama keep_alive override. When set, takes priority
    # over WorkflowDefaults.keep_alive and the arch-detected default.
    # Accepts the same forms Ollama does: "0", "30m", "1h", "-1" (forever),
    # or a number of seconds as a string. None = inherit from defaults/arch.
    keep_alive: Optional[str] = None


# ── v2: Structured Prompt + Hook Spec ──────────────────────────────────────


class StepPrompt(BaseModel):
    """Five-part prompt block (v2 schema)."""

    role_ref: Optional[str] = None
    role_inline: Optional[str] = None
    task: str
    constraints: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_role(self):
        if self.role_ref and self.role_inline:
            raise ValueError("only one of role_ref or role_inline may be set")
        if not self.role_ref and not self.role_inline:
            raise ValueError("StepPrompt requires role_ref or role_inline")
        return self


class HookSpec(BaseModel):
    """A single hook entry in the step's `hooks` block."""

    name: str
    config: Dict[str, Any] = Field(default_factory=dict)


class StepHooks(BaseModel):
    """Per-step hook registrations."""

    before_step: List[HookSpec] = Field(default_factory=list)
    transform_prompt: List[HookSpec] = Field(default_factory=list)
    after_step: List[HookSpec] = Field(default_factory=list)
    validate_output: List[HookSpec] = Field(default_factory=list)
    on_failure: List[HookSpec] = Field(default_factory=list)


# ── Composite step config (kind=parallel, kind=loop) ───────────────────────


class ParallelExecutionConfig(BaseModel):
    """Execution semantics for a `kind: parallel` step.

    Modes (`docs/plans/2026-05-23-multi-agent-workflow-patterns-spec.md` §3):

      * auto                          — engine selects based on branch model set
      * multi_model_concurrent        — heterogeneous branches; concurrent dispatch
      * single_model_concurrent       — same model, concurrent slots (needs
                                        OLLAMA_NUM_PARALLEL > 1 on the daemon)
      * single_model_pseudo_parallel  — same model, sequential dispatch with
                                        prompt-cache reuse between branches
      * sharded                       — single persona × N input shards (Phase 2b)

    For single-model modes the engine validates at runtime that every branch
    resolves to the same model name; mismatch raises a clean error rather than
    silently degrading to multi_model_concurrent.

    When mode is `auto` the engine picks `single_model_pseudo_parallel` if all
    branches resolve to the same model and `multi_model_concurrent` otherwise.
    """

    mode: Literal[
        "auto",
        "multi_model_concurrent",
        "single_model_concurrent",
        "single_model_pseudo_parallel",
    ] = "multi_model_concurrent"
    max_concurrency: int = 4
    failure_policy: Literal["fail_fast", "continue_on_partial"] = "fail_fast"
    timeout_per_branch: Optional[int] = None


class LoopTermination(BaseModel):
    """Predicate evaluated after each loop iteration to decide whether to stop.

    `gate` — boolean expression over the iteration's workspace. Supported ops:
        ==, !=, >, <, >=, <=, in, not in, and, or, not. References use the
        same dotted-path syntax as AgentStep.inputs (e.g. `critic.approved`
        resolves to workspace.{loop_id}.iterations.{n}.critic.approved).

    `max_iterations` is enforced by the loop step itself, not by this predicate.
    """

    type: Literal["gate"] = "gate"
    gate: str
    on_max_iterations: Literal["emit_best", "fail"] = "emit_best"


# ── A2A external delegation (kind: a2a) ────────────────────────────────────


class A2AAuth(BaseModel):
    """Authentication config for a `kind: a2a` step.

    Only `bearer` is supported in Phase 3a. The actual token is never embedded
    in the YAML — operators reference an env var name and the engine reads it
    at request time. mTLS / OAuth / API key headers land in follow-ups.
    """

    type: Literal["bearer", "none"] = "none"
    # Name of an env var that holds the bearer token (e.g. INTEL_API_TOKEN).
    # Resolved at execution time; missing var raises a clean step failure.
    token_env: Optional[str] = None

    @model_validator(mode="after")
    def _validate_token_env(self):
        if self.type == "bearer" and not self.token_env:
            raise ValueError("A2AAuth(type=bearer) requires token_env")
        return self


# ── Agent Step ─────────────────────────────────────────────────────────────


class AgentStep(BaseModel):
    """A unit of work in a workflow.

    The `kind` discriminator selects execution semantics:

      * llm       — single LLM call (default; backwards-compatible)
      * parallel  — fan-out to `branches`, then `gather` synthesizes results
      * loop      — re-run `body` until `until` predicate is satisfied or
                    `max_iterations` is reached
      * a2a       — delegate to an external A2A-protocol agent

    Spec: docs/plans/2026-05-23-multi-agent-workflow-patterns-spec.md
    """

    id: str
    name: str
    kind: Literal["llm", "parallel", "loop", "a2a"] = "llm"
    model: Optional[str] = None
    role: Optional[str] = None
    # Phase 4 — operator-supplied estimate of the model's GGUF size in GB.
    # Used by Architecture.feasible() at validate time and by the scheduler
    # at preview time. Optional for backwards compatibility; when missing the
    # feasibility check is a pass-through (Phase 4b will auto-derive from
    # MODEL_REGISTRY when not set). Common values: 7B Q4_K_M ≈ 4.5 GB,
    # 13B Q4_K_M ≈ 8 GB, 32B Q4_K_M ≈ 20 GB, 70B Q4_K_M ≈ 40 GB.
    est_size_gb: Optional[float] = None

    # v1 field
    system_prompt: Optional[str] = None
    # v2 field
    prompt: Optional[StepPrompt] = None

    inputs: List[str] = Field(default_factory=list)
    outputs: List[str] = Field(min_length=1)
    output_schema: Optional[Dict[str, Any]] = None
    hooks: StepHooks = Field(default_factory=StepHooks)
    config: StepConfig = Field(default_factory=StepConfig)
    # DAG dependency declaration — a list of upstream step ids this
    # step waits on. Drives the composer's edge wiring + the engine's
    # topological-sort hooks. Empty list = independent step (engine
    # falls back to YAML order). Adding this here (was missing pre
    # this commit) makes the API actually serialize the field
    # operators write in their YAML; the composer was previously
    # seeing every step with depends_on=None and rendering a stacked
    # blob instead of a connected flow.
    depends_on: List[str] = Field(default_factory=list)

    # ── kind: parallel ────────────────────────────────────────────────
    # Child steps that fan out from this parent. Each branch is itself a full
    # AgentStep (recursive), gets its own workspace namespace under
    # workspace.{parent.id}.branches.{branch.id}, and may have its own DAG via
    # `depends_on` referencing sibling branch ids.
    branches: Optional[List["AgentStep"]] = None
    # The synthesis step that runs after all branches complete. Reads each
    # branch's outputs (referenced as e.g. `extract_schema.fields`) and writes
    # to workspace.{parent.id}.{key} — i.e. the parent's declared outputs.
    gather: Optional["AgentStep"] = None
    execution: Optional[ParallelExecutionConfig] = None

    # ── kind: loop ────────────────────────────────────────────────────
    # Steps run on each iteration, in order. Body steps see prior iterations
    # via `$loop.previous_iteration.{step_id}.{key}` and may also reference
    # the loop's own declared `inputs` (which are resolved once on iter 0).
    body: Optional[List["AgentStep"]] = None
    until: Optional[LoopTermination] = None
    max_iterations: int = 5

    # ── kind: a2a ─────────────────────────────────────────────────────
    # URL to the remote agent's Agent Card (typically ends in
    # /.well-known/agent.json). The engine fetches this once per step
    # execution, validates the requested skill is advertised, then dispatches
    # the JSON-RPC `tasks/send` (or `tasks/sendSubscribe` when `streaming`).
    agent_card_url: Optional[str] = None
    # Advertised skill id to invoke on the remote agent.
    skill: Optional[str] = None
    # Optional auth config; bearer-token via env-var only in Phase 3a.
    auth: Optional[A2AAuth] = None
    # Whether to use SSE streaming (tasks/sendSubscribe). When false the
    # engine issues tasks/send and reads the final Task result.
    streaming: bool = False
    # Hard wall-clock cap on the whole step, in seconds. None = no cap (the
    # underlying HTTP client still has its own connect/read timeouts).
    timeout: Optional[int] = None

    @model_validator(mode="after")
    def _validate_kind_shape(self):
        # Non-a2a kinds must not declare a2a fields.
        if self.kind != "a2a" and (self.agent_card_url or self.skill or self.auth):
            raise ValueError(
                f"AgentStep(kind={self.kind}, id={self.id!r}) must not declare "
                f"agent_card_url/skill/auth (those are kind=a2a only)"
            )

        if self.kind == "llm":
            if not self.system_prompt and not self.prompt:
                raise ValueError(
                    "AgentStep(kind=llm) requires either prompt or system_prompt"
                )
            if self.system_prompt and self.prompt:
                raise ValueError(
                    "AgentStep has both `prompt` and `system_prompt` — use one"
                )
            if self.system_prompt is not None and not self.system_prompt.strip():
                raise ValueError("system_prompt must not be empty")
            if self.branches or self.gather or self.body or self.until:
                raise ValueError(
                    f"AgentStep(kind=llm) must not declare branches/gather/body/until "
                    f"(got id={self.id!r})"
                )
        elif self.kind == "parallel":
            if not self.branches or len(self.branches) < 2:
                raise ValueError(
                    f"AgentStep(kind=parallel, id={self.id!r}) requires at least 2 branches"
                )
            if self.gather is None:
                raise ValueError(
                    f"AgentStep(kind=parallel, id={self.id!r}) requires a gather step"
                )
            if self.system_prompt or self.prompt:
                raise ValueError(
                    f"AgentStep(kind=parallel, id={self.id!r}) must not declare a "
                    f"prompt — the gather step holds the synthesis prompt"
                )
            if self.body or self.until:
                raise ValueError(
                    f"AgentStep(kind=parallel, id={self.id!r}) must not declare body/until"
                )
            # Branch IDs must be unique within the parent.
            branch_ids = [b.id for b in self.branches]
            if len(set(branch_ids)) != len(branch_ids):
                raise ValueError(
                    f"AgentStep(kind=parallel, id={self.id!r}) has duplicate branch ids: "
                    f"{[b for b in branch_ids if branch_ids.count(b) > 1]}"
                )
            # The gather step's outputs must match the parent's declared outputs
            # exactly — gather is the unit that materializes the parent's contract.
            if set(self.gather.outputs) != set(self.outputs):
                raise ValueError(
                    f"AgentStep(kind=parallel, id={self.id!r}) outputs {sorted(self.outputs)} "
                    f"do not match gather step outputs {sorted(self.gather.outputs)}"
                )
        elif self.kind == "loop":
            if not self.body or len(self.body) < 1:
                raise ValueError(
                    f"AgentStep(kind=loop, id={self.id!r}) requires at least 1 body step"
                )
            if self.until is None:
                raise ValueError(
                    f"AgentStep(kind=loop, id={self.id!r}) requires `until` termination"
                )
            if self.system_prompt or self.prompt:
                raise ValueError(
                    f"AgentStep(kind=loop, id={self.id!r}) must not declare a prompt"
                )
            if self.branches or self.gather:
                raise ValueError(
                    f"AgentStep(kind=loop, id={self.id!r}) must not declare branches/gather"
                )
            if self.max_iterations < 1:
                raise ValueError(
                    f"AgentStep(kind=loop, id={self.id!r}) max_iterations must be >= 1"
                )
            # Body step IDs must be unique.
            body_ids = [s.id for s in self.body]
            if len(set(body_ids)) != len(body_ids):
                raise ValueError(
                    f"AgentStep(kind=loop, id={self.id!r}) has duplicate body step ids"
                )
            # On loop termination, each of the loop's declared outputs is
            # taken from the last body step's workspace by NAME. Every loop
            # output must therefore be produced by the last body step —
            # this makes the loop's contract knowable at validate time.
            last_body = self.body[-1]
            missing = set(self.outputs) - set(last_body.outputs)
            if missing:
                raise ValueError(
                    f"AgentStep(kind=loop, id={self.id!r}) outputs "
                    f"{sorted(missing)} are not produced by the last body "
                    f"step '{last_body.id}' (which produces {last_body.outputs})"
                )
        elif self.kind == "a2a":
            if not self.agent_card_url:
                raise ValueError(
                    f"AgentStep(kind=a2a, id={self.id!r}) requires agent_card_url"
                )
            if not self.skill:
                raise ValueError(f"AgentStep(kind=a2a, id={self.id!r}) requires skill")
            if self.system_prompt or self.prompt:
                raise ValueError(
                    f"AgentStep(kind=a2a, id={self.id!r}) must not declare a "
                    f"prompt — the remote agent owns its own prompt"
                )
            if self.branches or self.gather or self.body or self.until:
                raise ValueError(
                    f"AgentStep(kind=a2a, id={self.id!r}) must not declare "
                    f"branches/gather/body/until"
                )
            if self.model or self.role:
                raise ValueError(
                    f"AgentStep(kind=a2a, id={self.id!r}) must not declare "
                    f"model/role — the remote agent selects its own model"
                )
        return self


# ── Workflow Definition ────────────────────────────────────────────────────


class WorkflowDefaults(BaseModel):
    role: str = "general"
    temperature: float = 0.7
    max_tokens: int = 4096
    retries: int = 2
    retry_delay: int = 5
    # Phase 3 — workflow-level keep_alive default. None = use the arch-detected
    # default (NVIDIA: "0" to free VRAM between steps; unified: "30m" to amortize
    # the high reload cost on systems where the swap is RAM-resident anyway).
    keep_alive: Optional[str] = None
    # Phase 5b — workflow-level opt-out for pre-warm. Some workflows want
    # fresh loads on every step (cold-cache benchmarks, freshness audits,
    # GPU-pressure-sensitive runs). Default None = arch-detected behavior
    # via arch.transition_plan() applies. True = engine never fires pre-warm
    # for this workflow.
    disable_pre_warm: Optional[bool] = None


class WorkflowDefinition(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    version: Optional[str] = None
    schema_version: int = 1
    context: Dict[str, Any] = Field(default_factory=dict)
    schemas: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    defaults: WorkflowDefaults = Field(default_factory=WorkflowDefaults)
    steps: List[AgentStep] = Field(min_length=1)

    @field_validator("steps")
    @classmethod
    def steps_not_empty(cls, v):
        if len(v) == 0:
            raise ValueError("Workflow must have at least one step")
        return v


# ── Workflow Context (unchanged from v1) ───────────────────────────────────


class WorkflowContext(BaseModel):
    seed: Dict[str, Any] = Field(default_factory=dict)
    workspace: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    shared: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def get_seed(self, key: str) -> Any:
        return self.seed.get(key)

    def set_workspace(self, step_id: str, key: str, value: Any) -> None:
        if step_id not in self.workspace:
            self.workspace[step_id] = {}
        self.workspace[step_id][key] = value

    def get_workspace(self, step_id: str, key: str) -> Any:
        return self.workspace.get(step_id, {}).get(key)

    def set_shared(self, key: str, value: Any) -> None:
        self.shared[key] = value

    def get_shared(self, key: str) -> Any:
        return self.shared.get(key)

    def resolve_input(self, input_ref: str) -> Any:
        parts = input_ref.split(".", 1)
        if len(parts) != 2:
            return None
        namespace, key = parts
        if namespace == "seed":
            return self.get_seed(key)
        elif namespace == "shared":
            return self.get_shared(key)
        else:
            return self.get_workspace(namespace, key)


# ── Step Result (unchanged) ────────────────────────────────────────────────


class StepResult(BaseModel):
    model_config = {"protected_namespaces": ()}
    step_id: str
    status: str = "pending"
    model_used: Optional[str] = None
    duration_seconds: Optional[float] = None
    token_count: Dict[str, int] = Field(
        default_factory=lambda: {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }
    )
    retries: int = 0
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    # Phase 2 — Architecture-aware observability. All optional; populated when
    # the executor has access to Ollama timing + arch.snapshot(). Older runs
    # serialized before Phase 2 deserialize cleanly because every field defaults.
    load_duration_ms: Optional[float] = None
    prompt_eval_duration_ms: Optional[float] = None
    eval_duration_ms: Optional[float] = None
    total_duration_ms: Optional[float] = None
    arch_name: Optional[str] = None
    pressure_before: Optional[Dict[str, Any]] = None
    pressure_after: Optional[Dict[str, Any]] = None
    keep_alive_used: Optional[str] = None


# ── Run-Level Telemetry Summary (Phase 2 task 2.4) ────────────────────────


class RunTelemetrySummary(BaseModel):
    """Per-run aggregation of step-level telemetry.

    Computed once the run finishes (success OR failure) from the populated
    StepResult.* fields. Lets the UI answer questions like "how much of this
    run's wall-clock time was paid as model-swap cost?" without iterating the
    step list. None on runs that have no telemetry-populated steps.
    """

    total_cold_load_ms: float = 0.0
    cold_load_count: int = 0
    warm_step_count: int = 0
    total_eval_ms: float = 0.0
    total_prompt_eval_ms: float = 0.0
    arch_name: Optional[str] = None
    # Phase 5b — pre-warm summary fields. Aggregated from WorkflowRun.pre_warm_events
    # at run completion. `pre_warm_hits` = events where the consuming step's
    # load_duration was warm (<100 ms). `pre_warm_misses` = events where it
    # was cold (model evicted between pre-warm and use, or pre-warm itself failed).
    pre_warm_count: int = 0
    pre_warm_hits: int = 0
    pre_warm_misses: int = 0
    total_pre_warm_load_ms: float = 0.0


# ── Pre-Warm Event (Phase 5b) ─────────────────────────────────────────────


class PreWarmEvent(BaseModel):
    """One pre-warm dispatch.

    Recorded when the engine fires a daemon thread to load a model that the
    next tick will use. The thread updates the event in place with the load
    duration once Ollama returns. Hit/miss is resolved at run completion by
    walking the step_results: if the first downstream step that uses
    `model` shows `load_duration_ms < 100`, the pre-warm hit; otherwise it
    missed (evicted, or pre-warm failed).
    """

    model_config = {"protected_namespaces": ()}

    model: str
    dispatched_at: datetime
    completed_at: Optional[datetime] = None
    load_duration_ms: Optional[float] = None
    target_gpu_hint: Optional[int] = None  # from arch.transition_plan; advisory only
    error: Optional[str] = None
    # Resolved at run completion in workflow_engine._resolve_pre_warm_hits.
    hit: Optional[bool] = None
    hit_step_id: Optional[str] = None


# ── Workflow Run ──────────────────────────────────────────────────────────


class WorkflowRun(BaseModel):
    run_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    workflow_id: str
    status: str = "pending"
    context: WorkflowContext
    step_results: List[StepResult] = Field(default_factory=list)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
    telemetry_summary: Optional[RunTelemetrySummary] = None
    # Phase 5b — pre-warm dispatch log. Daemon threads update entries in
    # place under the engine's state_lock. Empty list on runs where the
    # arch said no pre-warm at every boundary, or where disable_pre_warm
    # was set in the workflow defaults.
    pre_warm_events: List[PreWarmEvent] = Field(default_factory=list)
