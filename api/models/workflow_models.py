"""
Workflow Engine Data Models

Pydantic models for multi-agent workflow definitions, context management,
and execution tracking. Supports both v1 (system_prompt string) and v2
(structured `prompt` block) schema.
"""

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

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


# ── Agent Step ─────────────────────────────────────────────────────────────


class AgentStep(BaseModel):
    id: str
    name: str
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

    @model_validator(mode="after")
    def _validate_prompt_shape(self):
        if not self.system_prompt and not self.prompt:
            raise ValueError(
                "AgentStep requires either prompt or system_prompt (v2 prompt block or v1 system_prompt)"
            )
        if self.system_prompt and self.prompt:
            raise ValueError(
                "AgentStep has both `prompt` and `system_prompt` — use one"
            )
        if self.system_prompt is not None and not self.system_prompt.strip():
            raise ValueError("system_prompt must not be empty")
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
