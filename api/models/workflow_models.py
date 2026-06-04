"""
Workflow Engine Data Models

Pydantic models for multi-agent workflow definitions, context management,
and execution tracking. Supports both v1 (system_prompt string) and v2
(structured `prompt` block) schema.
"""

import uuid
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import (
    BaseModel,
    Field,
    PrivateAttr,
    field_validator,
    model_validator,
)

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
      * sharded                       — single persona × N input shards. The
                                        step declares ONE branch (the persona)
                                        + a sharder; the engine clones the
                                        persona per shard and runs them
                                        sequentially (single-model). The gather
                                        step reads all shard results via the
                                        `$shards` accessor.

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
        "sharded",
    ] = "multi_model_concurrent"
    max_concurrency: int = 4
    failure_policy: Literal["fail_fast", "continue_on_partial"] = "fail_fast"
    timeout_per_branch: Optional[int] = None

    # ── single_model_pseudo_parallel mode only ─────────────────────────
    # When true, the composer re-orders each branch's prompt so the shared
    # `context` block leads (byte-identical across branches) and the divergent
    # role/task/constraints follow. This lets Ollama's prompt cache reuse the
    # KV state for the shared prefix between sequential branches on the same
    # model — ~70% latency reduction on branches 2..N for prefix-heavy
    # workflows. No effect outside single_model_pseudo_parallel mode (the
    # other modes either reload the model or genuinely parallelize, so a
    # byte-stable prefix wouldn't help). Default off — opt-in per parallel step.
    prefix_lock: bool = False

    # ── sharded mode only ──────────────────────────────────────────────
    # How to split the input. See api/services/sharders.py.
    sharder: Optional[Literal["by_file", "by_chunk", "by_token_window"]] = None
    # Context ref (e.g. "ingest.documents", "seed.report") whose value is the
    # data to shard. Resolved at execution time like any step input.
    shard_input: Optional[str] = None
    # Per-shard sizing: items-per-shard (by_chunk on a list), chars-per-shard
    # (by_chunk on a string), or tokens-per-window (by_token_window).
    shard_size: Optional[int] = None
    # Hard cap on shard count — the tail beyond this is dropped. Protects
    # against a huge input fanning out into thousands of LLM calls.
    max_shards: int = 32

    @model_validator(mode="after")
    def _validate_sharded(self):
        if self.mode == "sharded":
            if not self.sharder:
                raise ValueError(
                    "ParallelExecutionConfig(mode=sharded) requires a `sharder`"
                )
            if not self.shard_input or not self.shard_input.strip():
                raise ValueError(
                    "ParallelExecutionConfig(mode=sharded) requires `shard_input`"
                )
        elif self.sharder or self.shard_input:
            raise ValueError(
                f"ParallelExecutionConfig sharder/shard_input only apply to "
                f"mode=sharded (got mode={self.mode!r})"
            )
        # prefix_lock only helps the pseudo-parallel cache-reuse path; for the
        # concurrent modes the model state isn't shared between calls, and for
        # sharded the engine already runs sequential same-model. `auto` is
        # allowed because it can resolve to pseudo_parallel at runtime.
        if self.prefix_lock and self.mode not in (
            "auto",
            "single_model_pseudo_parallel",
        ):
            raise ValueError(
                f"ParallelExecutionConfig prefix_lock=True only applies to "
                f"mode=single_model_pseudo_parallel (or auto); got mode={self.mode!r}"
            )
        return self


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

    Supported schemes: `none`, `bearer` (Authorization: Bearer <token>), and
    `api_key` (a configurable header, default `X-API-Key`). The actual secret
    is never embedded in the YAML — operators reference an env var name and the
    engine reads it at request time. mTLS / OAuth land in follow-ups.
    """

    type: Literal["bearer", "api_key", "none"] = "none"
    # Name of an env var that holds the secret (e.g. INTEL_API_TOKEN).
    # Resolved at execution time; missing var raises a clean step failure.
    token_env: Optional[str] = None
    # Header name for api_key auth. Ignored by bearer/none. Defaults to the
    # common X-API-Key; override for services that expect e.g. "Api-Key".
    header_name: str = "X-API-Key"

    @model_validator(mode="after")
    def _validate_token_env(self):
        if self.type in ("bearer", "api_key") and not self.token_env:
            raise ValueError(f"A2AAuth(type={self.type}) requires token_env")
        return self


# ── Orchestrator step (kind: orchestrator) ─────────────────────────────────


class OrchestratorBudget(BaseModel):
    """Hard caps on a `kind: orchestrator` step. Any limit hit fails the step
    cleanly; the lead's `complete` directive never being emitted within the
    budget is itself the failure signal."""

    max_workers_spawned: int = 8
    max_planner_turns: int = 12
    max_total_tokens: int = 200_000
    max_wall_seconds: int = 600


# ── Consolidate step (kind: consolidate) ───────────────────────────────────


class ConsolidateSpec(BaseModel):
    """Config for a `kind: consolidate` step — Dreaming-style memory.

    The step runs one LLM call (the consolidation prompt) over its declared
    inputs, then writes the model's output into a durable memory store. The
    same output is also written to the step's declared workspace outputs so
    downstream steps in the same run can read it.

    `target` selects the store; `target_name` is the file key within it
    (playbook/concept name, or episodic log key). `merge_strategy` only
    applies to the markdown stores (playbook/semantic); episodic always
    appends a new record.
    """

    role: Optional[str] = None
    model: Optional[str] = None
    target: Literal["playbook", "semantic", "episodic"]
    target_name: str
    merge_strategy: Literal[
        "replace", "append", "append_with_dedup"
    ] = "append_with_dedup"
    system_prompt: str

    @model_validator(mode="after")
    def _validate_consolidate(self):
        if not self.target_name or not self.target_name.strip():
            raise ValueError("ConsolidateSpec requires a non-empty target_name")
        if not self.system_prompt or not self.system_prompt.strip():
            raise ValueError("ConsolidateSpec requires a non-empty system_prompt")
        return self


# ── Ralph autonomous loop (kind: ralph) ────────────────────────────────────


class RalphHalt(BaseModel):
    """Halt conditions for a `kind: ralph` autonomous loop. The loop runs its
    `body` until ANY of these fires. A loop that never satisfies `goal_gate`
    within the budget terminates via one of the hard caps.

    `halt_file` is the operator's emergency brake — touch the file and the
    loop stops gracefully at the next iteration boundary (in-flight body
    steps finish, the journal is flushed). This is one of the three ralph
    safety rails; the others (branch isolation, read-only-until-promoted) are
    tool-execution concerns enforced by the enclave-code layer, not the engine.
    """

    max_iterations: int = 50
    max_wall_seconds: int = 28800  # 8h
    max_total_tokens: int = 5_000_000
    # Stop after this many consecutive iterations whose body failed. Resets to
    # zero on any fully-successful iteration. Guards against burning the whole
    # budget on a stuck loop.
    max_consecutive_failures: int = 3
    # Path to a sentinel file. If it exists at an iteration boundary, the loop
    # halts gracefully (success). None disables the check.
    halt_file: Optional[str] = None
    # Optional gate expression evaluated after each iteration (same grammar as
    # LoopTermination.gate). True = goal reached, stop with success. None means
    # the loop runs until a hard cap.
    goal_gate: Optional[str] = None


class RalphSpec(BaseModel):
    """Config for a `kind: ralph` step — the autonomous recursive loop.

    Ralph = plan → execute → verify → reflect, repeated until a halt condition.
    The body steps are regular AgentSteps (typically including a `consolidate`
    step that writes lessons to a playbook the plan step reads back via
    `$memory.*` — that's the self-learning loop).

    `journal_path` is an append-only JSONL of per-iteration records. It gives
    operators a human-readable audit trail and lets a restarted loop resume
    past already-journaled iterations rather than re-running from zero.
    """

    journal_path: str
    halt: RalphHalt = Field(default_factory=RalphHalt)

    @model_validator(mode="after")
    def _validate_ralph(self):
        if not self.journal_path or not self.journal_path.strip():
            raise ValueError("RalphSpec requires a non-empty journal_path")
        return self


# ── Code execution step (kind: code) ──────────────────────────────────────


class ResourceLimits(BaseModel):
    mem_mb: int = 1024
    cpus: float = 1.0
    pids: int = 256


class CodeStepConfig(BaseModel):
    """Config for a `kind: code` step — sandboxed code execution."""

    language: Literal["python"] = "python"
    source: Literal["inline", "from_input"] = "inline"
    code: Optional[str] = None
    code_input: Optional[str] = None
    files_in: List[str] = Field(default_factory=list)
    files_out: List[str] = Field(default_factory=list)
    timeout_s: int = 60
    limits: ResourceLimits = Field(default_factory=ResourceLimits)
    network: Literal["none", "allowlist"] = "none"
    approval: Literal["auto", "required", "tier_default"] = "tier_default"
    backend_override: Optional[Literal["subprocess", "container"]] = None
    promote: Literal["gated", "auto_on_green", "never"] = "gated"
    promote_predicate: Optional[str] = None


# ── Tool reference (Phase 5) ───────────────────────────────────────────────


class ToolRef(BaseModel):
    """Declarative reference to one tool a step may invoke.

    Exactly one of ``plugin`` or ``mcp`` must be set; each is a dotted ref:

      plugin: "<plugin_id>.<tool_id>"      # in-process Python tool
      mcp:    "<server_id>.<tool_name>"    # external MCP-protocol tool

    Pre-flight validation (Phase 5) walks every step's ``tools`` list at
    compile time and verifies the named plugin/MCP exists and exposes
    the named member. Engine-side dispatch (Phase 5 follow-up) reads
    these refs when wiring up the step's tool surface.
    """

    plugin: Optional[str] = None
    mcp: Optional[str] = None

    @model_validator(mode="after")
    def _exactly_one(self):
        set_count = sum(1 for v in (self.plugin, self.mcp) if v)
        if set_count == 0:
            raise ValueError("ToolRef must set exactly one of 'plugin' or 'mcp'")
        if set_count > 1:
            raise ValueError(
                "ToolRef must set only one of 'plugin' or 'mcp' (got both)"
            )
        ref = self.plugin or self.mcp
        # Dotted form so the validator can split into (owner, member).
        if "." not in ref or ref.startswith(".") or ref.endswith("."):
            raise ValueError(f"ToolRef must be '<id>.<member>' (got {ref!r})")
        return self


# ── Agent Step ─────────────────────────────────────────────────────────────


class AgentStep(BaseModel):
    """A unit of work in a workflow.

    The `kind` discriminator selects execution semantics:

      * llm           — single LLM call (default; backwards-compatible)
      * parallel      — fan-out to `branches`, then `gather` synthesizes results
      * loop          — re-run `body` until `until` predicate is satisfied or
                        `max_iterations` is reached
      * a2a           — delegate to an external A2A-protocol agent
      * orchestrator  — lead agent dynamically spawns workers from a catalog;
                        emits a text-protocol JSON directive each turn
      * consolidate   — distill inputs into durable cross-run memory
                        (playbook / semantic / episodic store)
      * ralph         — autonomous recursive loop (plan → execute → verify →
                        reflect) with a journal + halt conditions; self-learns
                        via a playbook the body reads/writes

    Spec: docs/plans/2026-05-23-multi-agent-workflow-patterns-spec.md
    """

    id: str
    name: str
    kind: Literal[
        "llm", "parallel", "loop", "a2a", "orchestrator", "consolidate", "ralph", "code"
    ] = "llm"
    model: Optional[str] = None
    role: Optional[str] = None
    # Phase 4 — operator-supplied estimate of the model's GGUF size in GB.
    # Used by Architecture.feasible() at validate time and by the scheduler
    # at preview time. Optional for backwards compatibility; when missing the
    # feasibility check is a pass-through (Phase 4b will auto-derive from
    # MODEL_REGISTRY when not set). Common values: 7B Q4_K_M ≈ 4.5 GB,
    # 13B Q4_K_M ≈ 8 GB, 32B Q4_K_M ≈ 20 GB, 70B Q4_K_M ≈ 40 GB.
    est_size_gb: Optional[float] = None
    # Phase 5.3 — GPU affinity hint for multi-GPU hosts. Honored only by
    # NvidiaMultiArchitecture.schedule_ready; ignored on unified / single-GPU /
    # CPU arches.
    #   None         — no preference; arch picks (typically "GPU with most free VRAM")
    #   "any"        — same as None
    #   "spread"     — explicit "let the scheduler distribute"
    #   "same_as:<step_id>" — co-locate with the named sibling step
    #   int (0..N-1) — pin to a specific GPU index
    gpu_affinity: Optional[Any] = None

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

    # ── Extension surface (Phase 5) ───────────────────────────────────
    # Declarative plugin / MCP tool refs the step intends to invoke. Used
    # by validate-time pre-flight to fail fast when a required plugin or
    # MCP server isn't installed/reachable. Engine-side dispatch (the
    # follow-up that wires step_executor through MCPRunnerPool) reads
    # this list to know which tools to expose to the LLM and which warm
    # runners to acquire for the step.
    tools: List[ToolRef] = Field(default_factory=list)
    # Skill refs the step explicitly opts into: "<plugin_id>.<skill_id>".
    # Empty list = inherit the workflow's skill_injection mode (auto =
    # keyword-trigger discovery; off = no skills; explicit = only the
    # skills named here). Validated at compile time.
    skills: List[str] = Field(default_factory=list)
    # Step archetype tag — declarative purpose hint (bash_script,
    # documentation, xsiam_analysis, …). The compiler can also infer
    # one from declared tools + role. Used by the resource-maximization
    # pass (Phase 2b) for in-archetype model substitution and by the
    # composer for companion suggestions. None = "no archetype declared
    # or inferred"; downstream code treats this as a generic step.
    archetype: Optional[str] = None

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

    # ── kind: orchestrator ────────────────────────────────────────────
    # The lead agent's prompt block. Becomes the planner's system prompt
    # augmented at runtime with a protocol description listing every worker
    # in the catalog plus the JSON-directive grammar.
    planner: Optional[StepPrompt] = None
    # Catalog of worker templates the lead may spawn. Map of worker_id ->
    # AgentStep template. Each template's `inputs` must be declared as
    # `seed.<name>` refs — the engine builds a child WorkflowContext for
    # each spawned worker with seed = the spawn directive's inputs.
    workers: Optional[Dict[str, "AgentStep"]] = None
    # Hard caps on the orchestration. Any cap hit fails the step.
    budget: Optional[OrchestratorBudget] = None

    # ── kind: consolidate ─────────────────────────────────────────────
    # Memory-consolidation config. The step runs its system_prompt over the
    # declared inputs, then writes the result into the named memory store.
    consolidate: Optional[ConsolidateSpec] = None

    # ── kind: ralph ───────────────────────────────────────────────────
    # Autonomous-loop config: journal path + halt conditions. The loop body
    # reuses the `body` field (shared with kind=loop).
    ralph: Optional[RalphSpec] = None

    # ── kind: code ────────────────────────────────────────────────────
    code: Optional[CodeStepConfig] = None

    @model_validator(mode="after")
    def _validate_kind_shape(self):
        # Phase 5.3 — gpu_affinity grammar
        if self.gpu_affinity is not None:
            aff = self.gpu_affinity
            if isinstance(aff, bool):
                # bool is a subclass of int in Python; reject explicitly
                raise ValueError(
                    f"AgentStep(id={self.id!r}).gpu_affinity must be a string "
                    "('any'|'spread'|'same_as:<id>') or an int, not bool"
                )
            if isinstance(aff, int):
                if aff < 0:
                    raise ValueError(
                        f"AgentStep(id={self.id!r}).gpu_affinity int must be >= 0 "
                        f"(got {aff})"
                    )
            elif isinstance(aff, str):
                if aff not in ("any", "spread") and not aff.startswith("same_as:"):
                    raise ValueError(
                        f"AgentStep(id={self.id!r}).gpu_affinity string must be "
                        f"'any', 'spread', or 'same_as:<id>' (got {aff!r})"
                    )
                if aff.startswith("same_as:") and len(aff) <= len("same_as:"):
                    raise ValueError(
                        f"AgentStep(id={self.id!r}).gpu_affinity 'same_as:' "
                        "needs a step id (e.g. 'same_as:step_a')"
                    )
            else:
                raise ValueError(
                    f"AgentStep(id={self.id!r}).gpu_affinity must be str or int "
                    f"(got {type(aff).__name__})"
                )

        # Non-a2a kinds must not declare a2a fields.
        if self.kind != "a2a" and (self.agent_card_url or self.skill or self.auth):
            raise ValueError(
                f"AgentStep(kind={self.kind}, id={self.id!r}) must not declare "
                f"agent_card_url/skill/auth (those are kind=a2a only)"
            )
        # Non-orchestrator kinds must not declare orchestrator fields.
        if self.kind != "orchestrator" and (
            self.planner or self.workers or self.budget
        ):
            raise ValueError(
                f"AgentStep(kind={self.kind}, id={self.id!r}) must not declare "
                f"planner/workers/budget (those are kind=orchestrator only)"
            )
        # Non-consolidate kinds must not declare a consolidate block.
        if self.kind != "consolidate" and self.consolidate is not None:
            raise ValueError(
                f"AgentStep(kind={self.kind}, id={self.id!r}) must not declare "
                f"a consolidate block (kind=consolidate only)"
            )
        # Non-ralph kinds must not declare a ralph block.
        if self.kind != "ralph" and self.ralph is not None:
            raise ValueError(
                f"AgentStep(kind={self.kind}, id={self.id!r}) must not declare "
                f"a ralph block (kind=ralph only)"
            )
        # Non-code kinds must not declare a code block.
        if self.kind != "code" and self.code is not None:
            raise ValueError(
                f"AgentStep(kind={self.kind}, id={self.id!r}) must not declare a "
                f"`code` block (only valid on kind=code)"
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
            is_sharded = self.execution is not None and self.execution.mode == "sharded"
            # Sharded mode declares exactly ONE branch (the persona the engine
            # clones per shard). Every other mode enumerates ≥2 branches.
            if is_sharded:
                if not self.branches or len(self.branches) != 1:
                    raise ValueError(
                        f"AgentStep(kind=parallel, id={self.id!r}, mode=sharded) "
                        f"requires exactly 1 branch (the persona cloned per shard)"
                    )
            elif not self.branches or len(self.branches) < 2:
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
        elif self.kind == "orchestrator":
            if self.planner is None:
                raise ValueError(
                    f"AgentStep(kind=orchestrator, id={self.id!r}) requires a "
                    f"planner block (the lead agent's persona)"
                )
            if not self.workers or len(self.workers) < 1:
                raise ValueError(
                    f"AgentStep(kind=orchestrator, id={self.id!r}) requires at "
                    f"least one worker template in `workers`"
                )
            if self.system_prompt or self.prompt:
                raise ValueError(
                    f"AgentStep(kind=orchestrator, id={self.id!r}) must not "
                    f"declare a prompt — the `planner` block holds the lead's prompt"
                )
            if self.branches or self.gather or self.body or self.until:
                raise ValueError(
                    f"AgentStep(kind=orchestrator, id={self.id!r}) must not "
                    f"declare branches/gather/body/until"
                )
            # Every worker template must declare its inputs as seed.<name>
            # so the engine can build a child WorkflowContext with seed =
            # the spawn directive's inputs. Anything else (e.g. workspace
            # refs to siblings) breaks the isolation invariant.
            for worker_id, worker in self.workers.items():
                # The worker_id key is what the planner emits in
                # spawn_worker directives — its AgentStep.id can differ.
                # Non-llm workers (a2a, parallel, etc) are allowed; the
                # engine recurses through _execute_one_step for them.
                non_seed = [
                    ref for ref in worker.inputs if ref and not ref.startswith("seed.")
                ]
                if non_seed:
                    raise ValueError(
                        f"AgentStep(kind=orchestrator, id={self.id!r}) worker "
                        f"{worker_id!r} has inputs not declared as seed.* "
                        f"({non_seed}); orchestrator workers receive inputs "
                        f"via the spawn directive, which the engine maps onto "
                        f"a child context's seed layer"
                    )
        elif self.kind == "consolidate":
            if self.consolidate is None:
                raise ValueError(
                    f"AgentStep(kind=consolidate, id={self.id!r}) requires a "
                    f"consolidate block"
                )
            if self.system_prompt or self.prompt:
                raise ValueError(
                    f"AgentStep(kind=consolidate, id={self.id!r}) must not declare "
                    f"a top-level prompt — the consolidation prompt lives in the "
                    f"consolidate block's system_prompt"
                )
            if self.branches or self.gather or self.body or self.until:
                raise ValueError(
                    f"AgentStep(kind=consolidate, id={self.id!r}) must not declare "
                    f"branches/gather/body/until"
                )
        elif self.kind == "ralph":
            if self.ralph is None:
                raise ValueError(
                    f"AgentStep(kind=ralph, id={self.id!r}) requires a ralph block"
                )
            if not self.body or len(self.body) < 1:
                raise ValueError(
                    f"AgentStep(kind=ralph, id={self.id!r}) requires at least 1 "
                    f"body step (the iteration's plan/execute/verify/reflect work)"
                )
            if self.system_prompt or self.prompt:
                raise ValueError(
                    f"AgentStep(kind=ralph, id={self.id!r}) must not declare a "
                    f"top-level prompt — the body steps hold the prompts"
                )
            if self.branches or self.gather or self.until:
                raise ValueError(
                    f"AgentStep(kind=ralph, id={self.id!r}) must not declare "
                    f"branches/gather/until"
                )
            # Body step IDs must be unique (same invariant as kind=loop).
            body_ids = [s.id for s in self.body]
            if len(set(body_ids)) != len(body_ids):
                raise ValueError(
                    f"AgentStep(kind=ralph, id={self.id!r}) has duplicate body step ids"
                )
            # The ralph step's declared outputs are materialized from whichever
            # body step produced them (last-producer-wins). Unlike kind=loop,
            # the meaningful output (e.g. `progress`) often comes from a middle
            # body step while the last step is `reflect`/journal — so every
            # declared output need only be produced by SOME body step.
            produced = set()
            for b in self.body:
                produced.update(b.outputs)
            missing = set(self.outputs) - produced
            if missing:
                raise ValueError(
                    f"AgentStep(kind=ralph, id={self.id!r}) outputs "
                    f"{sorted(missing)} are not produced by any body step "
                    f"(body produces {sorted(produced)})"
                )
        elif self.kind == "code":
            if self.code is None:
                raise ValueError(
                    f"AgentStep(kind=code, id={self.id!r}) requires a `code` config block"
                )
            if self.code.source == "inline" and not self.code.code:
                raise ValueError(
                    f"AgentStep(kind=code, id={self.id!r}) source=inline requires code.code"
                )
            if self.code.source == "from_input" and not self.code.code_input:
                raise ValueError(
                    f"AgentStep(kind=code, id={self.id!r}) source=from_input requires code.code_input"
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
    # ── Extension pre-flight (Phase 5 — MCP & Skills) ─────────────────
    # Plugins the workflow requires. Empty list = no plugin gating.
    # Missing required plugin → validate-time error; workflow refuses
    # to run. Lenient mode (default) treats missing-but-not-required as
    # a warning surfaced in the validate response.
    required_plugins: List[str] = Field(default_factory=list)
    # MCP servers the workflow requires. Missing-from-registry → error;
    # registered-but-unreachable → warning (error in STRICT mode).
    required_mcps: List[str] = Field(default_factory=list)
    # How keyword-triggered skills are injected per step.
    #   "auto"     — keyword triggers apply (default)
    #   "explicit" — only step-declared skills inject
    #   "manual"   — no auto-injection; step must call out skills
    #   "off"      — disable injection entirely for this workflow
    skill_injection: Literal["auto", "explicit", "manual", "off"] = "auto"
    # Phase 2b (MCP & Skills) — how the compiler responds when it detects
    # MCP / heavy-model contention. See api/services/co_scheduler.py.
    #   "off"             — no analysis
    #   "recommend"       — default; emit optimization_recommendations
    #   "warn_strict"     — promote suggestions to warnings (still runs)
    #   "reject"          — block compile on any contention step
    #   "auto_substitute" — apply recommend_smaller_model automatically
    #                       when available; leave the rest as recommendations
    co_scheduling_policy: Literal[
        "off", "recommend", "warn_strict", "reject", "auto_substitute"
    ] = "recommend"


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

    # The engine attaches a MemoryStore here at run start so steps can read
    # `$memory.*` inputs. PrivateAttr keeps it out of model_dump / run.json —
    # the store is a service handle, not run state. None means memory reads
    # resolve to "" (a workflow run with no memory wiring still works).
    _memory: Any = PrivateAttr(default=None)
    # Set by the engine around a sharded parallel step's gather call: the list
    # of per-shard output dicts. Resolves the `$shards` accessor. Transient —
    # set right before gather, cleared right after — so it's never serialized
    # and never leaks between steps. None means "$shards" → [].
    _shards: Any = PrivateAttr(default=None)

    def attach_memory(self, store: Any) -> None:
        self._memory = store

    def set_shards(self, shards: Any) -> None:
        self._shards = shards

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
        # Memory accessor: $memory.<target>.<name>
        #   $memory.playbook.<name>   → playbook markdown body
        #   $memory.semantic.<concept>→ semantic markdown body
        #   $memory.episodic.<key>    → recency digest of episodic records
        if input_ref.startswith("$memory."):
            return self._resolve_memory(input_ref)

        # Shards accessor (sharded parallel mode):
        #   $shards          → the full list of per-shard output dicts
        #   $shards.<key>    → list of that key pulled from each shard dict
        if input_ref == "$shards" or input_ref.startswith("$shards."):
            return self._resolve_shards(input_ref)

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

    def _resolve_memory(self, input_ref: str) -> Any:
        """Resolve a $memory.<target>.<name> reference against the attached
        MemoryStore. Returns "" when no store is attached or the entry is
        missing — memory reads are best-effort, never fatal."""
        if self._memory is None:
            return ""
        # Strip the "$memory." prefix, then split target / name on the first dot.
        rest = input_ref[len("$memory.") :]
        sub = rest.split(".", 1)
        if len(sub) != 2:
            return ""
        target, name = sub
        if target == "playbook":
            return self._memory.read_playbook(name)
        if target == "semantic":
            return self._memory.read_semantic(name)
        if target == "episodic":
            return self._memory.read_episodic_digest(name)
        return ""

    def _resolve_shards(self, input_ref: str) -> Any:
        """Resolve `$shards` / `$shards.<key>` for a sharded gather step.

        `$shards` → the full list of per-shard output dicts.
        `$shards.<key>` → the list of that key from each shard dict (missing
        keys contribute None). Returns [] when no shards are set (the gather
        ran outside a sharded context).
        """
        shards = self._shards or []
        if input_ref == "$shards":
            return shards
        key = input_ref[len("$shards.") :]
        return [(s.get(key) if isinstance(s, dict) else None) for s in shards]


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

    # ── Prompt provenance — "what prompt ran?" for the Runs UI. ──────
    # The actual text sent to the model for this step, captured from the
    # SAME composed prompt the model call used (never re-rendered). Both
    # are optional so pre-existing runs deserialize unchanged and non-LLM
    # step kinds (parallel/loop/orchestrator/ralph — which delegate the
    # real model call to their child steps) leave them None.
    #   rendered_prompt        — final user/content message string.
    #   rendered_system_prompt — final system message string, if any.
    # Each is capped at PROMPT_CAPTURE_MAX_CHARS with a trailing
    # "…[truncated]" marker; full text is stored when under the cap.
    rendered_prompt: Optional[str] = None
    rendered_system_prompt: Optional[str] = None

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

    # ── Phase 4 (MCP & Skills) — per-step extension instrumentation. ──
    # All optional/empty by default so pre-Phase-4 runs deserialize unchanged
    # and steps that don't touch extensions don't bloat the run record.
    skills_activated: List["SkillActivation"] = Field(default_factory=list)
    mcp_calls: List["MCPCall"] = Field(default_factory=list)
    plugin_tools_called: List["PluginToolCall"] = Field(default_factory=list)
    # Cumulative time the step spent on skill rendering + MCP round-trips +
    # plugin tool execution. Lets the operator ratio extension cost against
    # pure-inference time (eval_duration_ms) without summing the arrays.
    extension_overhead_ms: float = 0.0

    # Code-exec (kind: code) — all optional; None on non-code steps.
    code_exit_code: Optional[int] = None
    tier_used: Optional[int] = None
    peak_rss_mb: Optional[float] = None
    files_produced: List[str] = Field(default_factory=list)
    approval_status: Optional[Literal["auto", "approved", "edited", "rejected"]] = None
    promoted: Optional[bool] = None


# ── HITL Approval Gate (Task 11) ──────────────────────────────────────────


class GatePending(BaseModel):
    """A HITL approval gate awaiting an operator decision. Serialized on the run
    so a paused workflow survives restart and resumes by id."""

    gate_id: str
    run_id: str
    step_id: str
    step_kind: str
    proposed_code: str
    network: str
    files: List[str] = Field(default_factory=list)
    tier: int
    question: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    decision: Optional[Literal["approved", "edited", "rejected"]] = None
    edited_code: Optional[str] = None
    reason: Optional[str] = None


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


# ── Per-step instrumentation (Phase 4, MCP & Skills) ─────────────────────


class SkillActivation(BaseModel):
    """One skill body that was injected into a step's prompt.

    Captured by ``step_executor`` when a skill triggers — either by a
    keyword match (``trigger="keyword"`` plus the matched substring in
    ``trigger_match``) or because the step explicitly listed it
    (``trigger="explicit"``). ``injected_into`` distinguishes a system-
    prompt prepend from a message-level insertion. ``injected_chars`` is
    how much text the skill added (operators want to know when a single
    skill doubled their prompt size).
    """

    plugin_id: str
    skill_id: str
    trigger: Literal["keyword", "manual", "explicit"]
    trigger_match: Optional[str] = None
    injected_into: Literal["system", "messages"]
    injected_chars: int = 0


class MCPCall(BaseModel):
    """One tool call against an MCP server during a step.

    ``status`` is one of:
      * ``ok``      — server returned a result
      * ``error``   — JSON-RPC error frame (the server replied with an
                      error code); ``error_code`` / ``error_message``
                      hold the details
      * ``timeout`` — request deadline exceeded; the runner pool will
                      typically respawn for the next call

    ``request_size_bytes`` and ``response_size_bytes`` are the JSON payload
    lengths the engine wrote/read; useful for finding "this MCP call paid
    20 MB of round-trip" outliers in long-running RAG workflows.
    """

    server_id: str
    tool_name: str
    duration_ms: float = 0.0
    status: Literal["ok", "error", "timeout"] = "ok"
    request_size_bytes: int = 0
    response_size_bytes: int = 0
    error_code: Optional[str] = None
    error_message: Optional[str] = None


class PluginToolCall(BaseModel):
    """One Python plugin tool the step invoked.

    Plugin tools run in-process so we don't have a transport status —
    just ok/error. ``error_class`` captures the exception class name when
    a tool raised; useful for triaging the long-tail of plugin breakage
    without dumping a full stack trace into the run record.
    """

    plugin_id: str
    tool_id: str
    duration_ms: float = 0.0
    status: Literal["ok", "error"] = "ok"
    error_class: Optional[str] = None


# ── MCP Runner Stats (Phase 2) ────────────────────────────────────────────


class MCPRunnerStats(BaseModel):
    """Per-MCP-runner record attached to a WorkflowRun.

    One entry per (run_id, server_id) pair the workflow spawned. ``scope``
    is the lifecycle the engine used: ``step`` (spawned + closed within one
    step), ``region`` (held warm across a compiler-detected region of
    contiguous same-MCP steps), or ``workflow`` (held for the whole run —
    the initial integration shape; region scope lands in Phase 2b).

    The fields cover what an operator needs to triage MCP overhead in a
    run summary: how often the runner served requests, how much memory it
    held, how fast it responded, whether it exited cleanly.
    """

    server_id: str
    transport: Literal["stdio", "http"]
    pid: Optional[int] = None
    scope: Literal["step", "region", "workflow"] = "workflow"
    started_at: datetime
    closed_at: Optional[datetime] = None
    handshake_duration_ms: float = 0.0
    requests_handled: int = 0
    errors: int = 0
    peak_rss_mb: Optional[float] = None  # stdio only; None for HTTP
    avg_response_ms: float = 0.0
    exit_code: Optional[int] = None
    # Phase 3 — health monitor + circuit breaker visibility.
    health_check_failures: int = 0
    circuit_breaker_tripped: bool = False


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
    # HITL gate — set when a code step is awaiting operator approval; cleared
    # (set back to None) once the decision arrives or the step is skipped.
    pending_gate: Optional[GatePending] = None
    telemetry_summary: Optional[RunTelemetrySummary] = None
    # Phase 5b — pre-warm dispatch log. Daemon threads update entries in
    # place under the engine's state_lock. Empty list on runs where the
    # arch said no pre-warm at every boundary, or where disable_pre_warm
    # was set in the workflow defaults.
    pre_warm_events: List[PreWarmEvent] = Field(default_factory=list)
    # Phase 2 (MCP & Skills) — one entry per warm MCP runner the run used.
    # Populated by MCPRunnerPool.release_workflow() at run end. Empty when
    # the workflow declared no MCPs or when MCP routing wasn't enabled.
    mcp_runners: List[MCPRunnerStats] = Field(default_factory=list)
    # Phase 4 (MCP & Skills) — run-level extension usage rollup. Computed
    # once at run completion by ``aggregate_extension_stats(run)`` from the
    # per-step arrays so the UI doesn't have to walk every step result.
    skills_activated_total: int = 0
    mcp_invocations_total: int = 0
    plugin_tools_invoked_total: int = 0
    mcp_servers_used: List[str] = Field(default_factory=list)
    extension_overhead_seconds: float = 0.0


# ── Run-level aggregation (Phase 4, MCP & Skills) ─────────────────────────


def aggregate_extension_stats(run: "WorkflowRun") -> None:
    """Roll per-step ``skills_activated`` / ``mcp_calls`` / ``plugin_tools_called``
    arrays into the run-level totals on ``WorkflowRun``.

    Called once at run completion by ``workflow_engine.execute`` so the UI
    (and ``/api/workflows/runs/{id}``) can answer "how much of this run's
    wall-clock was extension overhead?" without walking every step result.
    Idempotent — re-running over a run with already-aggregated stats
    produces the same numbers.
    """
    run.skills_activated_total = sum(len(s.skills_activated) for s in run.step_results)
    run.mcp_invocations_total = sum(len(s.mcp_calls) for s in run.step_results)
    run.plugin_tools_invoked_total = sum(
        len(s.plugin_tools_called) for s in run.step_results
    )
    # Deduplicate while preserving stable order — set() loses iteration order
    # under hash randomization and the operator dashboard renders this list.
    seen: set = set()
    ordered: List[str] = []
    for s in run.step_results:
        for c in s.mcp_calls:
            if c.server_id not in seen:
                seen.add(c.server_id)
                ordered.append(c.server_id)
    run.mcp_servers_used = ordered
    run.extension_overhead_seconds = round(
        sum(s.extension_overhead_ms for s in run.step_results) / 1000.0, 3
    )
