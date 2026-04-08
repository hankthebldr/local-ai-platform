"""
Workflow Engine Data Models — Best-in-Class Multi-Agent Orchestration

Pydantic v2 models for:
- DAG-based workflow definitions with parallel execution
- Conditional branching and routing
- Structured output parsing (JSON schema, regex, sections)
- Quality gates between steps
- Jinja2 prompt templating
- Three-layer context with variable interpolation
- Checkpoint/resume support
- Execution planning and scheduling
"""

import copy
import threading
import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Set, Union

from pydantic import BaseModel, Field, PrivateAttr, field_validator


# ── Shared Utility ────────────────────────────────────────────────────────


def dot_walk(data: Any, path: str) -> Any:
    """Walk nested dicts/lists via dot notation: 'a.b.0.c'"""
    for part in path.split("."):
        if data is None:
            return None
        if isinstance(data, dict):
            data = data.get(part)
        elif isinstance(data, (list, tuple)):
            try:
                data = data[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            return None
    return data


# ── Enums ─────────────────────────────────────────────────────────────────


class StepStatus(str, Enum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"
    CANCELLED = "cancelled"


class OutputFormat(str, Enum):
    RAW = "raw"              # Full LLM output as-is
    JSON = "json"            # Parse as JSON object
    JSON_ARRAY = "json_array"  # Parse as JSON array
    MARKDOWN_SECTIONS = "markdown_sections"  # Split by ## headings
    REGEX = "regex"          # Extract via named capture groups
    KEY_VALUE = "key_value"  # Parse key: value lines
    CSV = "csv"              # Parse CSV/TSV tabular data


class GateOperator(str, Enum):
    CONTAINS = "contains"
    NOT_CONTAINS = "not_contains"
    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    GT = "gt"
    LT = "lt"
    GTE = "gte"
    LTE = "lte"
    MATCHES = "matches"       # Regex match
    NOT_EMPTY = "not_empty"
    IS_JSON = "is_json"
    LENGTH_GT = "length_gt"
    LENGTH_LT = "length_lt"
    HAS_KEY = "has_key"       # Dict has key
    ALL_KEYS = "all_keys"     # Dict has all listed keys


# ── Output Parser Config ──────────────────────────────────────────────────


class OutputParserConfig(BaseModel):
    """Configuration for structured output parsing"""
    format: OutputFormat = OutputFormat.RAW
    schema: Optional[Dict[str, Any]] = None  # JSON schema for validation
    regex_pattern: Optional[str] = None       # For REGEX format
    section_delimiter: Optional[str] = None   # For MARKDOWN_SECTIONS
    strict: bool = False                      # Fail step if parsing fails
    fallback: OutputFormat = OutputFormat.RAW  # Fallback format on parse failure


# ── Quality Gate ──────────────────────────────────────────────────────────


class QualityGate(BaseModel):
    """Validation check applied to step output before proceeding"""
    name: str
    field: str                                # Output field to check (dot notation)
    operator: GateOperator
    value: Optional[Any] = None               # Expected value (for comparison ops)
    message: Optional[str] = None             # Error message on failure
    severity: Literal["error", "warning"] = "error"  # error = abort, warning = log


# ── Condition ─────────────────────────────────────────────────────────────


class StepCondition(BaseModel):
    """Conditional execution — step runs only if condition is met"""
    ref: str                                  # Context reference (e.g., "step_a.status")
    operator: GateOperator = GateOperator.NOT_EMPTY
    value: Optional[Any] = None
    logic: Literal["all", "any"] = "all"      # For multiple conditions


# ── Loop Config ───────────────────────────────────────────────────────────


class LoopConfig(BaseModel):
    """Iterate a step over a collection from context"""
    over: str                                 # Context ref to iterate (e.g., "seed.files")
    as_var: str = "item"                      # Variable name in prompt template
    max_parallel: int = 1                     # Parallelism for loop iterations
    collect_as: Optional[str] = None          # Aggregate results under this key


# ── Step Config ───────────────────────────────────────────────────────────


class StepConfig(BaseModel):
    """Per-step configuration overrides"""
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    retries: Optional[int] = None
    retry_delay: Optional[int] = None         # Seconds between retries
    timeout: Optional[int] = None             # Max seconds for LLM call
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    seed: Optional[int] = None                # Deterministic generation


# ── Agent Step ────────────────────────────────────────────────────────────


class AgentStep(BaseModel):
    """A single agent step in a workflow DAG"""
    id: str
    name: str
    model: Optional[str] = None               # Explicit model name
    role: Optional[str] = None                # Role-based resolution
    system_prompt: str                        # Jinja2 template supported
    user_prompt: Optional[str] = None         # Optional explicit user prompt (Jinja2)
    inputs: List[str] = Field(default_factory=list)
    outputs: List[str] = Field(min_length=1)
    depends_on: List[str] = Field(default_factory=list)  # DAG edges (step IDs)
    config: StepConfig = Field(default_factory=StepConfig)
    output_parser: OutputParserConfig = Field(default_factory=OutputParserConfig)
    quality_gates: List[QualityGate] = Field(default_factory=list)
    condition: Optional[StepCondition] = None           # Skip if condition not met
    conditions: List[StepCondition] = Field(default_factory=list)  # Multiple conditions
    loop: Optional[LoopConfig] = None                   # Iterate over collection
    tags: List[str] = Field(default_factory=list)       # Metadata tags
    description: Optional[str] = None                   # Human-readable description
    cache_key: Optional[str] = None           # Cache identical inputs → reuse output

    @field_validator("system_prompt")
    @classmethod
    def system_prompt_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("system_prompt must not be empty")
        return v

    @property
    def all_conditions(self) -> List["StepCondition"]:
        """Merge singular condition and conditions list"""
        result = list(self.conditions)
        if self.condition:
            result.append(self.condition)
        return result


# ── Workflow Definition ───────────────────────────────────────────────────


class WorkflowDefaults(BaseModel):
    """Workflow-level default configuration"""
    role: str = "general"
    temperature: float = 0.7
    max_tokens: int = 4096
    retries: int = 2
    retry_delay: int = 5
    timeout: int = 300
    output_format: OutputFormat = OutputFormat.RAW


class WorkflowHook(BaseModel):
    """Webhook or callback triggered on workflow events"""
    event: str                                # e.g., "step.completed", "workflow.failed"
    url: Optional[str] = None                 # Webhook URL
    action: Optional[str] = None              # Built-in action name


class WorkflowMetadata(BaseModel):
    """Rich metadata for workflow definitions"""
    author: Optional[str] = None
    category: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    estimated_duration: Optional[int] = None  # Seconds
    cost_estimate: Optional[float] = None     # Estimated token cost


class WorkflowDefinition(BaseModel):
    """Complete workflow definition — DAG of agent steps"""
    id: str
    name: str
    description: Optional[str] = None
    version: Optional[str] = None
    defaults: WorkflowDefaults = Field(default_factory=WorkflowDefaults)
    steps: List[AgentStep] = Field(min_length=1)
    hooks: List[WorkflowHook] = Field(default_factory=list)
    metadata: WorkflowMetadata = Field(default_factory=WorkflowMetadata)
    max_parallel: int = 4                     # Max concurrent steps

    @field_validator("steps")
    @classmethod
    def steps_not_empty(cls, v: List[AgentStep]) -> List[AgentStep]:
        if len(v) == 0:
            raise ValueError("Workflow must have at least one step")
        return v


# ── Workflow Context (Three-Layer) ────────────────────────────────────────


class WorkflowContext(BaseModel):
    """
    Three-layer context management with variable interpolation.

    Layer 1 - seed: immutable user input
    Layer 2 - workspace: namespaced per-step outputs
    Layer 3 - shared: mutable cross-cutting state
    + metadata: execution metadata, timing, model info
    """
    seed: Dict[str, Any] = Field(default_factory=dict)
    workspace: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    shared: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    _snapshots: Dict[str, Dict[str, Any]] = PrivateAttr(default_factory=dict)
    _lock: threading.Lock = PrivateAttr(default_factory=threading.Lock)

    def get_seed(self, key: str) -> Any:
        return self.seed.get(key)

    def set_workspace(self, step_id: str, key: str, value: Any) -> None:
        with self._lock:
            if step_id not in self.workspace:
                self.workspace[step_id] = {}
            self.workspace[step_id][key] = value

    def get_workspace(self, step_id: str, key: str) -> Any:
        return self.workspace.get(step_id, {}).get(key)

    def get_step_outputs(self, step_id: str) -> Dict[str, Any]:
        return self.workspace.get(step_id, {})

    def set_shared(self, key: str, value: Any) -> None:
        with self._lock:
            self.shared[key] = value

    def get_shared(self, key: str) -> Any:
        return self.shared.get(key)

    def resolve_input(self, input_ref: str) -> Any:
        """
        Resolve an input reference to its value.
        Supports: 'seed.key', 'step_id.key', 'shared.key', 'metadata.key'
        Supports nested: 'step_id.key.subkey' via dot-walk
        """
        parts = input_ref.split(".", 1)
        if len(parts) != 2:
            return None
        namespace, key = parts
        if namespace == "seed":
            return dot_walk(self.seed, key)
        elif namespace == "shared":
            return dot_walk(self.shared, key)
        elif namespace == "metadata":
            return dot_walk(self.metadata, key)
        else:
            step_data = self.workspace.get(namespace, {})
            return dot_walk(step_data, key)

    def snapshot(self, name: str) -> None:
        """Create a named checkpoint of current context state"""
        self._snapshots[name] = {
            "seed": copy.deepcopy(self.seed),
            "workspace": copy.deepcopy(self.workspace),
            "shared": copy.deepcopy(self.shared),
            "metadata": copy.deepcopy(self.metadata),
        }

    def restore(self, name: str) -> bool:
        """Restore context from a named checkpoint"""
        snap = self._snapshots.get(name)
        if not snap:
            return False
        self.seed = snap["seed"]
        self.workspace = snap["workspace"]
        self.shared = snap["shared"]
        self.metadata = snap["metadata"]
        return True

    def to_template_vars(self) -> Dict[str, Any]:
        """Flatten context into a dict suitable for Jinja2 template rendering"""
        variables: Dict[str, Any] = {}
        variables["seed"] = self.seed
        variables["shared"] = self.shared
        variables["metadata"] = self.metadata
        for step_id, outputs in self.workspace.items():
            variables[step_id] = outputs
        return variables


# ── Step Result ───────────────────────────────────────────────────────────


class StepResult(BaseModel):
    """Result of executing a single workflow step"""
    model_config = {"protected_namespaces": ()}
    step_id: str
    status: StepStatus = StepStatus.PENDING
    model_used: Optional[str] = None
    duration_seconds: Optional[float] = None
    token_count: Dict[str, int] = Field(
        default_factory=lambda: {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    )
    retries: int = 0
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    gate_results: List[Dict[str, Any]] = Field(default_factory=list)
    cached: bool = False
    loop_index: Optional[int] = None
    raw_output: Optional[str] = None          # Full LLM response before parsing
    parsed_output: Optional[Dict[str, Any]] = None  # Structured parsed output


# ── Execution Plan ────────────────────────────────────────────────────────


class ExecutionBatch(BaseModel):
    """A batch of steps that can execute in parallel"""
    batch_index: int
    step_ids: List[str]
    depends_on_batches: List[int] = Field(default_factory=list)


class ExecutionPlan(BaseModel):
    """Computed execution plan — topologically sorted batches"""
    workflow_id: str
    total_steps: int
    total_batches: int
    batches: List[ExecutionBatch]
    step_order: List[str]                     # Flat topological order
    parallelism: int                          # Effective max parallel


# ── Workflow Run ──────────────────────────────────────────────────────────


class WorkflowRun(BaseModel):
    """A single execution instance of a workflow"""
    run_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    workflow_id: str
    status: RunStatus = RunStatus.PENDING
    context: WorkflowContext
    step_results: List[StepResult] = Field(default_factory=list)
    execution_plan: Optional[ExecutionPlan] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
    checkpoints: List[str] = Field(default_factory=list)
    total_tokens: int = 0
    total_duration: float = 0.0


# ── Event System ──────────────────────────────────────────────────────────


class WorkflowEvent(BaseModel):
    """Event emitted during workflow execution"""
    event_type: str                           # e.g., "step.started", "workflow.completed"
    run_id: str
    step_id: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    data: Dict[str, Any] = Field(default_factory=dict)
