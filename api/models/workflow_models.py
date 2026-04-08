"""
Workflow Engine Data Models

Pydantic models for multi-agent workflow definitions, context management,
and execution tracking.
"""

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


# ── Step Config ────────────────────────────────────────────────────────────


class StepConfig(BaseModel):
    """Per-step configuration overrides"""
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    retries: Optional[int] = None
    retry_delay: Optional[int] = None  # seconds
    timeout: Optional[int] = None  # seconds


# ── Agent Step ─────────────────────────────────────────────────────────────


class AgentStep(BaseModel):
    """A single agent step in a workflow"""
    id: str
    name: str
    model: Optional[str] = None  # explicit model name
    role: Optional[str] = None   # role-based resolution: reasoning, fast, coding, uncensored, general
    system_prompt: str
    inputs: List[str] = Field(default_factory=list)
    outputs: List[str] = Field(min_length=1)
    config: StepConfig = Field(default_factory=StepConfig)

    @field_validator("system_prompt")
    @classmethod
    def system_prompt_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("system_prompt must not be empty")
        return v


# ── Workflow Definition ────────────────────────────────────────────────────


class WorkflowDefaults(BaseModel):
    """Workflow-level default configuration"""
    role: str = "general"
    temperature: float = 0.7
    max_tokens: int = 4096
    retries: int = 2
    retry_delay: int = 5  # seconds


class WorkflowDefinition(BaseModel):
    """Complete workflow definition, parsed from YAML"""
    id: str
    name: str
    description: Optional[str] = None
    version: Optional[str] = None
    defaults: WorkflowDefaults = Field(default_factory=WorkflowDefaults)
    steps: List[AgentStep] = Field(min_length=1)

    @field_validator("steps")
    @classmethod
    def steps_not_empty(cls, v: List[AgentStep]) -> List[AgentStep]:
        if len(v) == 0:
            raise ValueError("Workflow must have at least one step")
        return v


# ── Workflow Context (Three-Layer) ─────────────────────────────────────────


class WorkflowContext(BaseModel):
    """
    Three-layer context management for workflow execution.

    Layer 1 - seed: immutable user input
    Layer 2 - workspace: namespaced per-step outputs
    Layer 3 - shared: mutable cross-cutting state
    """
    seed: Dict[str, Any] = Field(default_factory=dict)
    workspace: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    shared: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def get_seed(self, key: str) -> Any:
        """Read from the immutable seed layer"""
        return self.seed.get(key)

    def set_workspace(self, step_id: str, key: str, value: Any) -> None:
        """Write to a step's namespace in the workspace layer"""
        if step_id not in self.workspace:
            self.workspace[step_id] = {}
        self.workspace[step_id][key] = value

    def get_workspace(self, step_id: str, key: str) -> Any:
        """Read from any step's namespace in the workspace layer"""
        return self.workspace.get(step_id, {}).get(key)

    def set_shared(self, key: str, value: Any) -> None:
        """Write to the shared cross-cutting layer"""
        self.shared[key] = value

    def get_shared(self, key: str) -> Any:
        """Read from the shared layer"""
        return self.shared.get(key)

    def resolve_input(self, input_ref: str) -> Any:
        """
        Resolve an input reference to its value.
        Format: 'seed.key', 'step_id.key', or 'shared.key'
        """
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


# ── Step Result ────────────────────────────────────────────────────────────


class StepResult(BaseModel):
    """Result of executing a single workflow step"""
    model_config = {"protected_namespaces": ()}
    step_id: str
    status: str = "pending"  # pending, running, completed, failed
    model_used: Optional[str] = None
    duration_seconds: Optional[float] = None
    token_count: Dict[str, int] = Field(
        default_factory=lambda: {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    )
    retries: int = 0
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


# ── Workflow Run ───────────────────────────────────────────────────────────


class WorkflowRun(BaseModel):
    """A single execution instance of a workflow"""
    run_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    workflow_id: str
    status: str = "pending"  # pending, running, completed, failed
    context: WorkflowContext
    step_results: List[StepResult] = Field(default_factory=list)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
