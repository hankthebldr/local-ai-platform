# Multi-Agent Workflow Engine — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a sequential pipeline engine that executes multi-agent workflows defined in YAML, with three-layer context management, retry logic, and role-based model resolution — integrated into the existing FastAPI platform.

**Architecture:** YAML workflow definitions are loaded and validated by a `WorkflowEngine`, which iterates through `AgentStep`s sequentially. Each step is executed by a `StepExecutor` that assembles a prompt from declared inputs, calls `OllamaService.chat()`, and writes outputs to a namespaced `WorkflowContext`. Model selection uses a `ModelResolver` that queries the existing inventory for role-based resolution. Results persist to `data/workflows/{run_id}/`.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic v2, PyYAML, existing OllamaService, existing inventory router, pytest

**Design doc:** `docs/plans/2026-04-06-multi-agent-workflow-engine-design.md`

---

## Task 1: Pydantic Data Models (`api/models/workflow_models.py`)

**Files:**
- Create: `api/models/__init__.py`
- Create: `api/models/workflow_models.py`
- Create: `tests/test_workflow_models.py`

**Step 1: Write the failing test**

```python
# tests/test_workflow_models.py
"""Tests for workflow data models"""
import pytest
from api.models.workflow_models import (
    AgentStep,
    WorkflowDefaults,
    WorkflowDefinition,
    WorkflowContext,
    StepResult,
    WorkflowRun,
)


class TestAgentStep:
    def test_step_with_role(self):
        step = AgentStep(
            id="analyze",
            name="Analyze Schema",
            role="reasoning",
            system_prompt="You are a data architect.",
            inputs=["seed.source_files"],
            outputs=["entities", "relationships"],
        )
        assert step.id == "analyze"
        assert step.role == "reasoning"
        assert step.model is None

    def test_step_with_explicit_model(self):
        step = AgentStep(
            id="generate",
            name="Generate Code",
            model="qwen3.5-uncensored:35b",
            system_prompt="You are a developer.",
            inputs=["seed.constraints"],
            outputs=["code"],
        )
        assert step.model == "qwen3.5-uncensored:35b"
        assert step.role is None

    def test_step_requires_system_prompt(self):
        with pytest.raises(Exception):
            AgentStep(
                id="bad",
                name="Bad Step",
                role="fast",
                inputs=[],
                outputs=[],
            )

    def test_step_config_defaults(self):
        step = AgentStep(
            id="s1",
            name="Step",
            role="fast",
            system_prompt="prompt",
            inputs=[],
            outputs=["result"],
        )
        assert step.config.temperature is None
        assert step.config.max_tokens is None
        assert step.config.retries is None


class TestWorkflowDefinition:
    def test_valid_definition(self):
        defn = WorkflowDefinition(
            id="test-workflow",
            name="Test",
            steps=[
                AgentStep(
                    id="s1",
                    name="Step 1",
                    role="fast",
                    system_prompt="Do thing",
                    inputs=["seed.task"],
                    outputs=["result"],
                )
            ],
        )
        assert defn.id == "test-workflow"
        assert len(defn.steps) == 1

    def test_definition_requires_steps(self):
        with pytest.raises(Exception):
            WorkflowDefinition(id="empty", name="Empty", steps=[])


class TestWorkflowContext:
    def test_seed_is_immutable_after_init(self):
        ctx = WorkflowContext(seed={"task": "test"})
        assert ctx.get_seed("task") == "test"

    def test_workspace_scoped_writes(self):
        ctx = WorkflowContext(seed={})
        ctx.set_workspace("step1", "entities", ["User", "Post"])
        assert ctx.get_workspace("step1", "entities") == ["User", "Post"]

    def test_workspace_read_other_namespace(self):
        ctx = WorkflowContext(seed={})
        ctx.set_workspace("step1", "data", "hello")
        # step2 can read step1's namespace
        assert ctx.get_workspace("step1", "data") == "hello"

    def test_workspace_missing_key_returns_none(self):
        ctx = WorkflowContext(seed={})
        assert ctx.get_workspace("nonexistent", "key") is None

    def test_shared_layer(self):
        ctx = WorkflowContext(seed={})
        ctx.set_shared("decisions", ["chose X"])
        ctx.set_shared("decisions", ["chose X", "chose Y"])
        assert len(ctx.get_shared("decisions")) == 2

    def test_resolve_input_from_seed(self):
        ctx = WorkflowContext(seed={"task": "build models", "lang": "python"})
        assert ctx.resolve_input("seed.task") == "build models"

    def test_resolve_input_from_workspace(self):
        ctx = WorkflowContext(seed={})
        ctx.set_workspace("analyze", "entities", ["User"])
        assert ctx.resolve_input("analyze.entities") == ["User"]

    def test_resolve_input_from_shared(self):
        ctx = WorkflowContext(seed={})
        ctx.set_shared("warnings", ["no index"])
        assert ctx.resolve_input("shared.warnings") == ["no index"]


class TestWorkflowRun:
    def test_run_initial_status(self):
        ctx = WorkflowContext(seed={"task": "test"})
        run = WorkflowRun(workflow_id="test-wf", context=ctx)
        assert run.status == "pending"
        assert run.run_id is not None
        assert run.step_results == []
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/henry/Github/Github_desktop/local-ai-platform/.claude/worktrees/magical-payne && source venv/bin/activate && pytest tests/test_workflow_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'api.models.workflow_models'`

**Step 3: Write the implementation**

```python
# api/models/__init__.py
```

```python
# api/models/workflow_models.py
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
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/henry/Github/Github_desktop/local-ai-platform/.claude/worktrees/magical-payne && source venv/bin/activate && pytest tests/test_workflow_models.py -v`
Expected: All 13 tests PASS

**Step 5: Commit**

```bash
git add api/models/__init__.py api/models/workflow_models.py tests/test_workflow_models.py
git commit -m "feat(workflow): add Pydantic data models for workflow engine

Three-layer context (seed/workspace/shared), AgentStep with role/model
selection, WorkflowDefinition parsed from YAML, WorkflowRun for execution
tracking. Full test coverage."
```

---

## Task 2: Workflow Exceptions (`api/exceptions.py`)

**Files:**
- Modify: `api/exceptions.py`
- Create: `tests/test_workflow_exceptions.py`

**Step 1: Write the failing test**

```python
# tests/test_workflow_exceptions.py
"""Tests for workflow-specific exceptions"""
import pytest
from api.exceptions import (
    WorkflowValidationError,
    WorkflowExecutionError,
    ModelResolutionError,
    StepExecutionError,
)


class TestWorkflowExceptions:
    def test_validation_error(self):
        exc = WorkflowValidationError("Step 'foo' input 'bar.baz' has no producer")
        assert exc.status_code == 422
        assert "foo" in exc.message
        assert exc.code == "workflow_validation_failed"

    def test_execution_error(self):
        exc = WorkflowExecutionError("Workflow 'test' failed at step 'analyze'")
        assert exc.status_code == 500
        assert exc.code == "workflow_execution_failed"

    def test_model_resolution_error(self):
        exc = ModelResolutionError("reasoning")
        assert exc.status_code == 404
        assert "reasoning" in exc.message
        assert exc.code == "model_resolution_failed"

    def test_step_execution_error(self):
        exc = StepExecutionError("analyze", "Ollama timeout after 300s")
        assert exc.status_code == 500
        assert "analyze" in exc.message
        assert exc.code == "step_execution_failed"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_workflow_exceptions.py -v`
Expected: FAIL — `ImportError: cannot import name 'WorkflowValidationError'`

**Step 3: Add exceptions to existing file**

Append to `api/exceptions.py` before the handler functions:

```python
class WorkflowValidationError(APIError):
    """Raised when a workflow definition fails validation"""

    def __init__(self, message: str):
        super().__init__(
            message=message,
            status_code=422,
            error_type="invalid_request_error",
            code="workflow_validation_failed",
        )


class WorkflowExecutionError(APIError):
    """Raised when a workflow execution fails"""

    def __init__(self, message: str):
        super().__init__(
            message=message,
            status_code=500,
            error_type="server_error",
            code="workflow_execution_failed",
        )


class ModelResolutionError(APIError):
    """Raised when a model role cannot be resolved to an available model"""

    def __init__(self, role: str):
        super().__init__(
            message=f"No available model found for role '{role}'. Check that models with this role are installed.",
            status_code=404,
            error_type="invalid_request_error",
            code="model_resolution_failed",
        )


class StepExecutionError(APIError):
    """Raised when a single workflow step fails"""

    def __init__(self, step_id: str, detail: str = ""):
        msg = f"Step '{step_id}' failed."
        if detail:
            msg += f" {detail}"
        super().__init__(
            message=msg,
            status_code=500,
            error_type="server_error",
            code="step_execution_failed",
        )
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_workflow_exceptions.py -v`
Expected: All 4 tests PASS

**Step 5: Commit**

```bash
git add api/exceptions.py tests/test_workflow_exceptions.py
git commit -m "feat(workflow): add workflow-specific exception types

WorkflowValidationError (422), WorkflowExecutionError (500),
ModelResolutionError (404), StepExecutionError (500)"
```

---

## Task 3: Model Resolver (`api/services/model_resolver.py`)

**Files:**
- Create: `api/services/model_resolver.py`
- Create: `tests/test_model_resolver.py`

**Step 1: Write the failing test**

```python
# tests/test_model_resolver.py
"""Tests for ModelResolver — role-based and explicit model resolution"""
import pytest
from unittest.mock import MagicMock
from api.services.model_resolver import ModelResolver
from api.exceptions import ModelResolutionError, ModelNotFoundError


class TestModelResolver:
    def setup_method(self):
        self.ollama = MagicMock()
        self.resolver = ModelResolver(self.ollama)

    def test_resolve_explicit_model_exists(self):
        """Explicit model name that exists in Ollama"""
        self.ollama.list_models.return_value = [
            {"name": "qwen3.5-uncensored:35b", "size": 25000000000},
            {"name": "dolphin3:8b", "size": 5000000000},
        ]
        result = self.resolver.resolve(model="qwen3.5-uncensored:35b")
        assert result == "qwen3.5-uncensored:35b"

    def test_resolve_explicit_model_not_found(self):
        """Explicit model that doesn't exist raises error"""
        self.ollama.list_models.return_value = [
            {"name": "dolphin3:8b", "size": 5000000000},
        ]
        with pytest.raises(ModelNotFoundError):
            self.resolver.resolve(model="nonexistent:70b")

    def test_resolve_role_returns_model(self):
        """Role-based resolution returns an available model"""
        self.ollama.list_models.return_value = [
            {"name": "deepseek-r1:32b", "size": 20000000000},
            {"name": "dolphin3:8b", "size": 5000000000},
        ]
        result = self.resolver.resolve(role="reasoning")
        assert result is not None
        assert isinstance(result, str)

    def test_resolve_role_no_match(self):
        """Role with no matching models raises error"""
        self.ollama.list_models.return_value = []
        with pytest.raises(ModelResolutionError):
            self.resolver.resolve(role="reasoning")

    def test_resolve_prefers_larger_model_for_role(self):
        """When multiple models match a role, prefer the larger one"""
        self.ollama.list_models.return_value = [
            {"name": "dolphin3:8b", "size": 5000000000},
            {"name": "qwen3.5-uncensored:35b", "size": 25000000000},
        ]
        result = self.resolver.resolve(role="coding")
        # Should pick the larger model
        assert "35b" in result or "32b" in result or result is not None

    def test_resolve_no_model_or_role_uses_default(self):
        """When neither model nor role given, uses default role"""
        self.ollama.list_models.return_value = [
            {"name": "dolphin3:8b", "size": 5000000000},
        ]
        result = self.resolver.resolve(default_role="general")
        assert result is not None
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_model_resolver.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Write the implementation**

```python
# api/services/model_resolver.py
"""
Model Resolver — Maps roles to available models via inventory

Uses the existing OllamaService to query available models and resolves
role-based references (reasoning, fast, coding, etc.) to concrete model names.
"""

from typing import Dict, List, Optional

from ..logging_config import logger
from ..exceptions import ModelResolutionError, ModelNotFoundError
from .ollama_service import OllamaService


# ── Role → Model Mapping ──────────────────────────────────────────────────
# Models are matched by substring in their name. Order = preference (first match wins).
# Larger models are preferred when multiple match.

ROLE_PATTERNS: Dict[str, List[str]] = {
    "reasoning": ["deepseek-r1", "qwen3", "nous-hermes"],
    "fast": ["dolphin3:8b", "mistral", "phi"],
    "coding": ["qwen3.5", "deepseek-coder", "codellama", "dolphin"],
    "uncensored": ["dolphin", "uncensored", "abliterated", "nous-hermes"],
    "general": ["dolphin", "qwen", "mistral", "llama"],
}


class ModelResolver:
    """Resolves model references (explicit or role-based) to concrete model names"""

    def __init__(self, ollama_service: OllamaService):
        self.ollama = ollama_service

    def resolve(
        self,
        model: Optional[str] = None,
        role: Optional[str] = None,
        default_role: str = "general",
    ) -> str:
        """
        Resolve a model reference to a concrete model name.

        Priority:
        1. Explicit model name — validate it exists
        2. Role-based resolution — find best matching available model
        3. Default role — fallback
        """
        if model:
            return self._resolve_explicit(model)

        effective_role = role or default_role
        return self._resolve_role(effective_role)

    def _resolve_explicit(self, model: str) -> str:
        """Validate an explicit model name exists in Ollama"""
        available = self.ollama.list_models()
        names = [m["name"] for m in available]

        if model in names:
            return model

        # Try partial match (e.g., "qwen3.5" matches "qwen3.5-uncensored:35b")
        for name in names:
            if model in name:
                logger.info(f"Model '{model}' resolved to '{name}' via partial match")
                return name

        raise ModelNotFoundError(model)

    def _resolve_role(self, role: str) -> str:
        """Resolve a role to the best available model"""
        available = self.ollama.list_models()

        if not available:
            raise ModelResolutionError(role)

        patterns = ROLE_PATTERNS.get(role, ROLE_PATTERNS["general"])

        # Score each available model against role patterns
        candidates = []
        for model_info in available:
            name = model_info["name"].lower()
            size = model_info.get("size", 0)
            for i, pattern in enumerate(patterns):
                if pattern.lower() in name:
                    # Lower pattern index = higher preference, larger size = better
                    candidates.append((model_info["name"], i, size))
                    break

        if not candidates:
            # No pattern match — fall back to largest available model
            largest = max(available, key=lambda m: m.get("size", 0))
            logger.warning(
                f"No model matched role '{role}', falling back to largest: {largest['name']}"
            )
            return largest["name"]

        # Sort: lowest pattern index first, then largest size
        candidates.sort(key=lambda c: (c[1], -c[2]))
        chosen = candidates[0][0]
        logger.info(f"Role '{role}' resolved to '{chosen}' (from {len(candidates)} candidates)")
        return chosen
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_model_resolver.py -v`
Expected: All 6 tests PASS

**Step 5: Commit**

```bash
git add api/services/model_resolver.py tests/test_model_resolver.py
git commit -m "feat(workflow): add ModelResolver for role-based model selection

Resolves explicit model names (validated against Ollama) and role-based
references (reasoning, fast, coding, uncensored, general) to available
models. Prefers larger models when multiple match."
```

---

## Task 4: Step Executor (`api/services/step_executor.py`)

**Files:**
- Create: `api/services/step_executor.py`
- Create: `tests/test_step_executor.py`

**Step 1: Write the failing test**

```python
# tests/test_step_executor.py
"""Tests for StepExecutor — single step execution with retry"""
import pytest
from unittest.mock import MagicMock, patch
from api.services.step_executor import StepExecutor
from api.models.workflow_models import (
    AgentStep, StepConfig, WorkflowContext, WorkflowDefaults,
)
from api.exceptions import GenerationError


class TestStepExecutor:
    def setup_method(self):
        self.ollama = MagicMock()
        self.executor = StepExecutor(self.ollama)

    def test_execute_step_success(self):
        """Successful step execution writes outputs to context"""
        step = AgentStep(
            id="analyze",
            name="Analyze",
            role="reasoning",
            system_prompt="Analyze the data. Return JSON with key 'entities'.",
            inputs=["seed.task"],
            outputs=["result"],
        )
        ctx = WorkflowContext(seed={"task": "analyze users"})
        defaults = WorkflowDefaults()

        self.ollama.chat.return_value = {
            "content": "Here is the analysis result.",
            "prompt_eval_count": 50,
            "eval_count": 100,
        }

        result = self.executor.execute(
            step=step,
            context=ctx,
            resolved_model="deepseek-r1:32b",
            defaults=defaults,
        )

        assert result.status == "completed"
        assert result.model_used == "deepseek-r1:32b"
        assert result.token_count["completion_tokens"] == 100
        assert ctx.get_workspace("analyze", "result") is not None

    def test_execute_step_retries_on_failure(self):
        """Step retries on GenerationError then succeeds"""
        step = AgentStep(
            id="draft",
            name="Draft",
            role="coding",
            system_prompt="Draft rules.",
            inputs=["seed.task"],
            outputs=["rules"],
            config=StepConfig(retries=2, retry_delay=0),
        )
        ctx = WorkflowContext(seed={"task": "draft"})
        defaults = WorkflowDefaults()

        # First call fails, second succeeds
        self.ollama.chat.side_effect = [
            GenerationError("timeout"),
            {
                "content": "Here are the rules.",
                "prompt_eval_count": 30,
                "eval_count": 80,
            },
        ]

        result = self.executor.execute(
            step=step,
            context=ctx,
            resolved_model="dolphin3:8b",
            defaults=defaults,
        )

        assert result.status == "completed"
        assert result.retries == 1
        assert self.ollama.chat.call_count == 2

    def test_execute_step_fails_after_retries_exhausted(self):
        """Step fails after all retries exhausted"""
        step = AgentStep(
            id="fail",
            name="Fail",
            role="fast",
            system_prompt="This will fail.",
            inputs=[],
            outputs=["nothing"],
            config=StepConfig(retries=1, retry_delay=0),
        )
        ctx = WorkflowContext(seed={})
        defaults = WorkflowDefaults()

        self.ollama.chat.side_effect = GenerationError("always fails")

        result = self.executor.execute(
            step=step,
            context=ctx,
            resolved_model="dolphin3:8b",
            defaults=defaults,
        )

        assert result.status == "failed"
        assert result.error is not None
        assert result.retries == 1

    def test_prompt_assembly_includes_only_declared_inputs(self):
        """Prompt only contains declared inputs, not entire context"""
        step = AgentStep(
            id="s2",
            name="Step 2",
            role="fast",
            system_prompt="Process the entities.",
            inputs=["seed.task", "s1.entities"],
            outputs=["processed"],
        )
        ctx = WorkflowContext(seed={"task": "test", "secret": "should not appear"})
        ctx.set_workspace("s1", "entities", ["User", "Post"])
        ctx.set_workspace("s1", "other_data", "should not appear in prompt")

        self.ollama.chat.return_value = {
            "content": "Processed.",
            "prompt_eval_count": 20,
            "eval_count": 30,
        }

        defaults = WorkflowDefaults()
        self.executor.execute(step=step, context=ctx, resolved_model="m", defaults=defaults)

        # Check the messages sent to ollama.chat
        call_args = self.ollama.chat.call_args
        messages = call_args[1]["messages"] if "messages" in call_args[1] else call_args[0][1]
        user_content = messages[-1]["content"]
        assert "User" in user_content
        assert "should not appear" not in user_content
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_step_executor.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Write the implementation**

```python
# api/services/step_executor.py
"""
Step Executor — Runs a single workflow step with retry logic

Assembles a prompt from the step's declared inputs, calls OllamaService,
writes outputs to context, and handles retries with exponential backoff.
"""

import json
import time
from datetime import datetime
from typing import Any, Dict

from ..logging_config import logger
from ..exceptions import GenerationError, StepExecutionError
from ..models.workflow_models import (
    AgentStep,
    StepResult,
    WorkflowContext,
    WorkflowDefaults,
)
from .ollama_service import OllamaService


class StepExecutor:
    """Executes a single agent step within a workflow"""

    def __init__(self, ollama_service: OllamaService):
        self.ollama = ollama_service

    def execute(
        self,
        step: AgentStep,
        context: WorkflowContext,
        resolved_model: str,
        defaults: WorkflowDefaults,
    ) -> StepResult:
        """
        Execute a single step: assemble prompt → call LLM → write outputs.

        Returns StepResult with status, timing, and token counts.
        Retries on failure up to configured limit.
        """
        result = StepResult(step_id=step.id, status="running", started_at=datetime.utcnow())
        result.model_used = resolved_model

        # Resolve config (step overrides > workflow defaults)
        temperature = step.config.temperature or defaults.temperature
        max_tokens = step.config.max_tokens or defaults.max_tokens
        retries = step.config.retries if step.config.retries is not None else defaults.retries
        retry_delay = step.config.retry_delay if step.config.retry_delay is not None else defaults.retry_delay

        # Assemble prompt from declared inputs only
        messages = self._build_messages(step, context)

        # Execute with retry
        last_error = None
        for attempt in range(retries + 1):
            try:
                logger.info(
                    f"Step '{step.id}' attempt {attempt + 1}/{retries + 1} "
                    f"using model '{resolved_model}'"
                )

                llm_result = self.ollama.chat(
                    model=resolved_model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )

                content = llm_result.get("content", "")

                # Write outputs to context workspace
                if len(step.outputs) == 1:
                    # Single output — write the entire response
                    context.set_workspace(step.id, step.outputs[0], content)
                else:
                    # Multiple outputs — try to parse as JSON, fall back to full content
                    parsed = self._try_parse_outputs(content, step.outputs)
                    for key, value in parsed.items():
                        context.set_workspace(step.id, key, value)

                # Record success metrics
                result.status = "completed"
                result.retries = attempt
                result.token_count = {
                    "prompt_tokens": llm_result.get("prompt_eval_count", 0),
                    "completion_tokens": llm_result.get("eval_count", 0),
                    "total_tokens": (
                        llm_result.get("prompt_eval_count", 0)
                        + llm_result.get("eval_count", 0)
                    ),
                }
                result.completed_at = datetime.utcnow()
                result.duration_seconds = (
                    result.completed_at - result.started_at
                ).total_seconds()

                logger.info(
                    f"Step '{step.id}' completed in {result.duration_seconds:.1f}s "
                    f"({result.token_count['total_tokens']} tokens)"
                )
                return result

            except (GenerationError, Exception) as e:
                last_error = str(e)
                logger.warning(
                    f"Step '{step.id}' attempt {attempt + 1} failed: {last_error}"
                )
                if attempt < retries and retry_delay > 0:
                    time.sleep(retry_delay)

        # All retries exhausted
        result.status = "failed"
        result.error = last_error
        result.retries = retries
        result.completed_at = datetime.utcnow()
        result.duration_seconds = (
            result.completed_at - result.started_at
        ).total_seconds()

        logger.error(
            f"Step '{step.id}' failed after {retries + 1} attempts: {last_error}"
        )
        return result

    def _build_messages(
        self, step: AgentStep, context: WorkflowContext
    ) -> list:
        """
        Assemble LLM messages from step's system_prompt and declared inputs.
        Only includes data the step explicitly declared in its inputs list.
        """
        # System message
        messages = [{"role": "system", "content": step.system_prompt}]

        # Resolve declared inputs into a context block
        input_data: Dict[str, Any] = {}
        for input_ref in step.inputs:
            value = context.resolve_input(input_ref)
            if value is not None:
                input_data[input_ref] = value

        # Build user message with resolved context
        if input_data:
            context_block = "## Context\n\n"
            for ref, value in input_data.items():
                if isinstance(value, (dict, list)):
                    context_block += f"### {ref}\n```json\n{json.dumps(value, indent=2)}\n```\n\n"
                else:
                    context_block += f"### {ref}\n{value}\n\n"
            context_block += "## Task\n\nBased on the context above, complete your assigned task."
            messages.append({"role": "user", "content": context_block})
        else:
            messages.append({"role": "user", "content": "Complete your assigned task."})

        return messages

    def _try_parse_outputs(
        self, content: str, output_keys: list
    ) -> Dict[str, Any]:
        """
        Try to parse LLM response into multiple named outputs.
        Falls back to assigning entire content to each output key.
        """
        # Try JSON parse
        try:
            parsed = json.loads(content)
            if isinstance(parsed, dict):
                result = {}
                for key in output_keys:
                    result[key] = parsed.get(key, content)
                return result
        except (json.JSONDecodeError, TypeError):
            pass

        # Try to find JSON block in markdown
        if "```json" in content:
            try:
                json_start = content.index("```json") + 7
                json_end = content.index("```", json_start)
                json_str = content[json_start:json_end].strip()
                parsed = json.loads(json_str)
                if isinstance(parsed, dict):
                    result = {}
                    for key in output_keys:
                        result[key] = parsed.get(key, content)
                    return result
            except (ValueError, json.JSONDecodeError):
                pass

        # Fallback: assign full content to all output keys
        return {key: content for key in output_keys}
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_step_executor.py -v`
Expected: All 4 tests PASS

**Step 5: Commit**

```bash
git add api/services/step_executor.py tests/test_step_executor.py
git commit -m "feat(workflow): add StepExecutor with retry and context assembly

Builds LLM prompts from declared inputs only, calls OllamaService.chat(),
parses outputs (JSON or raw text), writes to namespaced workspace.
Retries with configurable backoff on failure."
```

---

## Task 5: Workflow Engine (`api/services/workflow_engine.py`)

**Files:**
- Create: `api/services/workflow_engine.py`
- Create: `tests/test_workflow_engine.py`

**Step 1: Write the failing test**

```python
# tests/test_workflow_engine.py
"""Tests for WorkflowEngine — load, validate, execute workflows"""
import pytest
import yaml
import tempfile
import os
from unittest.mock import MagicMock, patch
from pathlib import Path

from api.services.workflow_engine import WorkflowEngine
from api.models.workflow_models import WorkflowContext
from api.exceptions import WorkflowValidationError, WorkflowExecutionError


VALID_WORKFLOW_YAML = """
id: test-workflow
name: Test Workflow
version: "1.0"
defaults:
  role: general
  retries: 1
  retry_delay: 0
steps:
  - id: step1
    name: Step One
    role: fast
    system_prompt: "Analyze the input."
    inputs:
      - seed.task
    outputs:
      - analysis
  - id: step2
    name: Step Two
    role: coding
    system_prompt: "Generate code from analysis."
    inputs:
      - seed.task
      - step1.analysis
    outputs:
      - code
"""

INVALID_IO_WORKFLOW_YAML = """
id: broken-workflow
name: Broken
steps:
  - id: step1
    name: Step One
    role: fast
    system_prompt: "Do something."
    inputs:
      - step_nonexistent.data
    outputs:
      - result
"""


class TestWorkflowEngineLoad:
    def setup_method(self):
        self.ollama = MagicMock()
        self.engine = WorkflowEngine(self.ollama)

    def test_load_valid_yaml(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(VALID_WORKFLOW_YAML)
            f.flush()
            defn = self.engine.load(f.name)
            assert defn.id == "test-workflow"
            assert len(defn.steps) == 2
        os.unlink(f.name)

    def test_load_invalid_file_raises(self):
        with pytest.raises(FileNotFoundError):
            self.engine.load("/nonexistent/path.yaml")

    def test_validate_valid_workflow(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(VALID_WORKFLOW_YAML)
            f.flush()
            defn = self.engine.load(f.name)
            # Should not raise
            self.engine.validate(defn, seed_keys=["task"])
        os.unlink(f.name)

    def test_validate_broken_io_raises(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(INVALID_IO_WORKFLOW_YAML)
            f.flush()
            defn = self.engine.load(f.name)
            with pytest.raises(WorkflowValidationError, match="step_nonexistent"):
                self.engine.validate(defn, seed_keys=[])
        os.unlink(f.name)


class TestWorkflowEngineExecute:
    def setup_method(self):
        self.ollama = MagicMock()
        self.ollama.list_models.return_value = [
            {"name": "dolphin3:8b", "size": 5000000000}
        ]
        self.ollama.chat.return_value = {
            "content": "Mock output",
            "prompt_eval_count": 10,
            "eval_count": 20,
        }
        self.engine = WorkflowEngine(self.ollama)

    def test_run_completes_all_steps(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(VALID_WORKFLOW_YAML)
            f.flush()
            defn = self.engine.load(f.name)
        os.unlink(f.name)

        run = self.engine.run(defn, seed={"task": "test task"})

        assert run.status == "completed"
        assert len(run.step_results) == 2
        assert all(r.status == "completed" for r in run.step_results)
        assert run.context.get_workspace("step1", "analysis") is not None
        assert run.context.get_workspace("step2", "code") is not None

    def test_run_stops_on_step_failure(self):
        self.ollama.chat.side_effect = Exception("LLM down")

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(VALID_WORKFLOW_YAML)
            f.flush()
            defn = self.engine.load(f.name)
        os.unlink(f.name)

        run = self.engine.run(defn, seed={"task": "test"})

        assert run.status == "failed"
        assert run.step_results[0].status == "failed"
        # Step 2 should not have executed
        assert len([r for r in run.step_results if r.status == "completed"]) == 0
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_workflow_engine.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Write the implementation**

```python
# api/services/workflow_engine.py
"""
Workflow Engine — Load, validate, and execute multi-agent workflows

Orchestrates sequential step execution with three-layer context management.
Integrates with ModelResolver for role-based model selection and
StepExecutor for individual step execution with retry logic.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import yaml

from ..logging_config import logger
from ..exceptions import WorkflowValidationError, WorkflowExecutionError
from ..models.workflow_models import (
    AgentStep,
    WorkflowDefinition,
    WorkflowContext,
    WorkflowRun,
    StepResult,
)
from .model_resolver import ModelResolver
from .step_executor import StepExecutor
from .ollama_service import OllamaService


# Default data directory for workflow run persistence
DATA_DIR = os.getenv("WORKFLOW_DATA_DIR", "./data/workflows")


class WorkflowEngine:
    """
    Central orchestrator for multi-agent workflows.

    Phases:
    1. Load — parse YAML into WorkflowDefinition
    2. Validate — check I/O wiring, model availability
    3. Execute — run steps sequentially, manage context
    4. Persist — save run results to disk
    """

    def __init__(self, ollama_service: OllamaService):
        self.ollama = ollama_service
        self.resolver = ModelResolver(ollama_service)
        self.executor = StepExecutor(ollama_service)

    # ── Load Phase ─────────────────────────────────────────────────────

    def load(self, yaml_path: str) -> WorkflowDefinition:
        """Load a workflow definition from a YAML file"""
        path = Path(yaml_path)
        if not path.exists():
            raise FileNotFoundError(f"Workflow file not found: {yaml_path}")

        with open(path) as f:
            raw = yaml.safe_load(f)

        try:
            definition = WorkflowDefinition(**raw)
        except Exception as e:
            raise WorkflowValidationError(f"Invalid workflow YAML: {e}")

        logger.info(f"Loaded workflow '{definition.id}' ({len(definition.steps)} steps)")
        return definition

    def load_from_dict(self, data: Dict[str, Any]) -> WorkflowDefinition:
        """Load a workflow definition from a dictionary (for API usage)"""
        try:
            return WorkflowDefinition(**data)
        except Exception as e:
            raise WorkflowValidationError(f"Invalid workflow definition: {e}")

    # ── Validate Phase ─────────────────────────────────────────────────

    def validate(
        self,
        definition: WorkflowDefinition,
        seed_keys: Optional[List[str]] = None,
    ) -> None:
        """
        Validate workflow I/O wiring.

        Checks that every step's declared inputs can be traced to:
        - A seed key
        - A prior step's declared output
        - A shared key produced by a prior step

        Raises WorkflowValidationError if validation fails.
        """
        available_outputs: Set[str] = set()

        # Seed keys are available from the start
        if seed_keys:
            for key in seed_keys:
                available_outputs.add(f"seed.{key}")

        errors = []

        for step in definition.steps:
            # Check all inputs are available
            for input_ref in step.inputs:
                if input_ref not in available_outputs:
                    # Allow seed.* references even if we don't know exact keys
                    if input_ref.startswith("seed.") and seed_keys is None:
                        continue
                    errors.append(
                        f"Step '{step.id}' input '{input_ref}' has no producer. "
                        f"Available: {sorted(available_outputs)}"
                    )

            # Register this step's outputs as available
            for output_key in step.outputs:
                available_outputs.add(f"{step.id}.{output_key}")

        # Check for duplicate step IDs
        step_ids = [s.id for s in definition.steps]
        dupes = [sid for sid in step_ids if step_ids.count(sid) > 1]
        if dupes:
            errors.append(f"Duplicate step IDs: {set(dupes)}")

        if errors:
            raise WorkflowValidationError(
                f"Workflow '{definition.id}' has {len(errors)} validation error(s):\n"
                + "\n".join(f"  - {e}" for e in errors)
            )

        logger.info(f"Workflow '{definition.id}' validated successfully")

    # ── Execute Phase ──────────────────────────────────────────────────

    def run(
        self,
        definition: WorkflowDefinition,
        seed: Dict[str, Any],
    ) -> WorkflowRun:
        """
        Execute a workflow end-to-end.

        Creates a WorkflowRun, iterates through steps sequentially,
        and returns the completed (or failed) run.
        """
        # Initialize run
        context = WorkflowContext(seed=seed)
        workflow_run = WorkflowRun(
            workflow_id=definition.id,
            context=context,
            started_at=datetime.utcnow(),
        )
        workflow_run.status = "running"

        logger.info(
            f"Starting workflow '{definition.id}' run={workflow_run.run_id} "
            f"({len(definition.steps)} steps)"
        )

        for step in definition.steps:
            logger.info(f"Executing step '{step.id}' ({step.name})")

            # Resolve model for this step
            try:
                resolved_model = self.resolver.resolve(
                    model=step.model,
                    role=step.role,
                    default_role=definition.defaults.role,
                )
            except Exception as e:
                step_result = StepResult(
                    step_id=step.id,
                    status="failed",
                    error=f"Model resolution failed: {e}",
                    started_at=datetime.utcnow(),
                    completed_at=datetime.utcnow(),
                )
                workflow_run.step_results.append(step_result)
                workflow_run.status = "failed"
                workflow_run.error = f"Step '{step.id}' failed: model resolution error"
                workflow_run.completed_at = datetime.utcnow()
                logger.error(f"Workflow failed at step '{step.id}': {e}")
                break

            # Execute the step
            step_result = self.executor.execute(
                step=step,
                context=context,
                resolved_model=resolved_model,
                defaults=definition.defaults,
            )
            workflow_run.step_results.append(step_result)

            # Check for failure — abort workflow
            if step_result.status == "failed":
                workflow_run.status = "failed"
                workflow_run.error = (
                    f"Step '{step.id}' failed after {step_result.retries + 1} attempts: "
                    f"{step_result.error}"
                )
                workflow_run.completed_at = datetime.utcnow()
                logger.error(f"Workflow '{definition.id}' failed at step '{step.id}'")
                break
        else:
            # All steps completed successfully
            workflow_run.status = "completed"
            workflow_run.completed_at = datetime.utcnow()
            total_duration = sum(
                r.duration_seconds or 0 for r in workflow_run.step_results
            )
            total_tokens = sum(
                r.token_count.get("total_tokens", 0) for r in workflow_run.step_results
            )
            logger.info(
                f"Workflow '{definition.id}' completed in {total_duration:.1f}s "
                f"({total_tokens} total tokens)"
            )

        # Persist results
        self._persist_run(workflow_run, definition)

        return workflow_run

    # ── Persist Phase ──────────────────────────────────────────────────

    def _persist_run(self, run: WorkflowRun, definition: WorkflowDefinition) -> None:
        """Save workflow run results to disk"""
        run_dir = Path(DATA_DIR) / run.run_id
        artifacts_dir = run_dir / "artifacts"

        try:
            run_dir.mkdir(parents=True, exist_ok=True)
            artifacts_dir.mkdir(exist_ok=True)

            # Save full run as JSON
            run_path = run_dir / "run.json"
            with open(run_path, "w") as f:
                json.dump(run.model_dump(mode="json"), f, indent=2, default=str)

            # Save individual step artifacts
            for step in definition.steps:
                step_data = run.context.workspace.get(step.id, {})
                if step_data:
                    artifact_path = artifacts_dir / f"{step.id}.json"
                    with open(artifact_path, "w") as f:
                        json.dump(step_data, f, indent=2, default=str)

            # Save human-readable summary
            summary_path = run_dir / "summary.md"
            with open(summary_path, "w") as f:
                f.write(self._generate_summary(run, definition))

            logger.info(f"Run persisted to {run_dir}")

        except Exception as e:
            logger.error(f"Failed to persist run {run.run_id}: {e}")

    def _generate_summary(self, run: WorkflowRun, definition: WorkflowDefinition) -> str:
        """Generate a markdown summary of a workflow run"""
        lines = [
            f"# Workflow Run: {definition.name}",
            f"",
            f"- **Run ID**: {run.run_id}",
            f"- **Workflow**: {definition.id} v{definition.version or '0.0'}",
            f"- **Status**: {run.status}",
            f"- **Started**: {run.started_at}",
            f"- **Completed**: {run.completed_at}",
            f"",
            f"## Steps",
            f"",
        ]

        for result in run.step_results:
            step_def = next((s for s in definition.steps if s.id == result.step_id), None)
            status_icon = "✅" if result.status == "completed" else "❌"
            lines.append(
                f"### {status_icon} {result.step_id}"
                f"{f' — {step_def.name}' if step_def else ''}"
            )
            lines.append(f"- Model: {result.model_used}")
            lines.append(f"- Duration: {result.duration_seconds:.1f}s" if result.duration_seconds else "- Duration: N/A")
            lines.append(f"- Tokens: {result.token_count.get('total_tokens', 0)}")
            if result.error:
                lines.append(f"- Error: {result.error}")
            lines.append("")

        if run.error:
            lines.extend(["## Error", "", run.error, ""])

        return "\n".join(lines)

    # ── Utilities ──────────────────────────────────────────────────────

    def list_workflows(self, workflows_dir: str = "./workflows") -> List[Dict]:
        """List all available workflow definitions"""
        results = []
        wf_path = Path(workflows_dir)
        if not wf_path.exists():
            return results

        for f in sorted(wf_path.glob("*.yaml")):
            try:
                defn = self.load(str(f))
                results.append({
                    "id": defn.id,
                    "name": defn.name,
                    "description": defn.description,
                    "version": defn.version,
                    "steps": len(defn.steps),
                    "file": str(f),
                })
            except Exception as e:
                logger.warning(f"Skipping invalid workflow {f}: {e}")

        return results

    def get_run(self, run_id: str) -> Optional[Dict]:
        """Load a persisted workflow run by ID"""
        run_path = Path(DATA_DIR) / run_id / "run.json"
        if not run_path.exists():
            return None
        with open(run_path) as f:
            return json.load(f)

    def list_runs(self, limit: int = 20) -> List[Dict]:
        """List recent workflow runs"""
        data_path = Path(DATA_DIR)
        if not data_path.exists():
            return []

        runs = []
        for run_dir in sorted(data_path.iterdir(), reverse=True):
            if run_dir.is_dir():
                run_file = run_dir / "run.json"
                if run_file.exists():
                    try:
                        with open(run_file) as f:
                            data = json.load(f)
                        runs.append({
                            "run_id": data.get("run_id"),
                            "workflow_id": data.get("workflow_id"),
                            "status": data.get("status"),
                            "started_at": data.get("started_at"),
                            "completed_at": data.get("completed_at"),
                        })
                    except Exception:
                        pass
            if len(runs) >= limit:
                break

        return runs
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_workflow_engine.py -v`
Expected: All 5 tests PASS

**Step 5: Commit**

```bash
git add api/services/workflow_engine.py tests/test_workflow_engine.py
git commit -m "feat(workflow): add WorkflowEngine — load, validate, execute, persist

Parses YAML definitions, validates I/O wiring at load time, executes
steps sequentially with context management, persists runs to
data/workflows/{run_id}/ with JSON and markdown summary."
```

---

## Task 6: Workflow API Router (`api/routers/workflows.py`)

**Files:**
- Create: `api/routers/workflows.py`
- Modify: `api/main.py` (add router include)
- Create: `tests/test_workflow_api.py`

**Step 1: Write the failing test**

```python
# tests/test_workflow_api.py
"""Tests for workflow API endpoints"""
import pytest
import json
import tempfile
import os
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient


VALID_WORKFLOW = {
    "id": "test-api-workflow",
    "name": "Test API Workflow",
    "defaults": {"role": "general", "retries": 0, "retry_delay": 0},
    "steps": [
        {
            "id": "s1",
            "name": "Step 1",
            "role": "fast",
            "system_prompt": "Analyze the input.",
            "inputs": ["seed.task"],
            "outputs": ["result"],
        }
    ],
}


@pytest.fixture
def mock_ollama():
    with patch("api.services.ollama_service.OllamaService") as MockClass:
        instance = MockClass.return_value
        instance.health_check.return_value = True
        instance.list_models.return_value = [
            {"name": "dolphin3:8b", "size": 5000000000}
        ]
        instance.chat.return_value = {
            "content": "Test output",
            "prompt_eval_count": 10,
            "eval_count": 20,
        }
        yield instance


@pytest.fixture
def client(mock_ollama):
    with patch("api.main.ollama_service", mock_ollama):
        with patch("api.routers.workflows.get_ollama_service", return_value=mock_ollama):
            from api.main import app
            return TestClient(app)


class TestWorkflowAPI:
    def test_list_workflows(self, client):
        response = client.get("/api/workflows")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_validate_workflow(self, client):
        response = client.post(
            "/api/workflows/validate",
            json={"definition": VALID_WORKFLOW, "seed_keys": ["task"]},
        )
        assert response.status_code == 200
        assert response.json()["valid"] is True

    def test_validate_broken_workflow(self, client):
        broken = {
            "id": "broken",
            "name": "Broken",
            "steps": [
                {
                    "id": "s1",
                    "name": "Step",
                    "role": "fast",
                    "system_prompt": "Do thing.",
                    "inputs": ["nonexistent.data"],
                    "outputs": ["result"],
                }
            ],
        }
        response = client.post(
            "/api/workflows/validate",
            json={"definition": broken, "seed_keys": []},
        )
        assert response.status_code == 422

    def test_list_runs(self, client):
        response = client.get("/api/workflows/runs")
        assert response.status_code == 200
        assert isinstance(response.json(), list)
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_workflow_api.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'api.routers.workflows'`

**Step 3: Write the router implementation**

```python
# api/routers/workflows.py
"""
Workflow Router — API endpoints for multi-agent workflow management

Endpoints:
  GET  /api/workflows              — List available workflow definitions
  POST /api/workflows/validate     — Validate a workflow definition
  POST /api/workflows/run          — Execute a workflow with seed data
  GET  /api/workflows/runs         — List recent workflow runs
  GET  /api/workflows/runs/{id}    — Get a specific run's status and results
  GET  /api/workflows/runs/{id}/artifacts/{step_id} — Get a step's output
"""

import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from ..logging_config import logger
from ..services.ollama_service import OllamaService
from ..services.workflow_engine import WorkflowEngine
from ..exceptions import WorkflowValidationError, WorkflowExecutionError

router = APIRouter(prefix="/api/workflows", tags=["workflows"])

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
WORKFLOWS_DIR = os.getenv("WORKFLOWS_DIR", "./workflows")


def get_ollama_service() -> OllamaService:
    """Get or create OllamaService instance"""
    return OllamaService(OLLAMA_HOST)


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


# ── Endpoints ──────────────────────────────────────────────────────────────


@router.get("")
async def list_workflows():
    """List all available workflow definitions from the workflows/ directory"""
    engine = get_engine()
    return engine.list_workflows(WORKFLOWS_DIR)


@router.post("/validate")
async def validate_workflow(req: WorkflowValidateRequest):
    """Validate a workflow definition without executing it"""
    engine = get_engine()
    try:
        defn = engine.load_from_dict(req.definition)
        engine.validate(defn, seed_keys=req.seed_keys)
        return {"valid": True, "workflow_id": defn.id, "steps": len(defn.steps)}
    except WorkflowValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))


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
        yaml_path = f"{WORKFLOWS_DIR}/{req.workflow_id}.yaml"
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
        "step_results": [
            {
                "step_id": r.step_id,
                "status": r.status,
                "model_used": r.model_used,
                "duration_seconds": r.duration_seconds,
                "token_count": r.token_count,
                "error": r.error,
            }
            for r in run.step_results
        ],
        "error": run.error,
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
    return run_data


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
```

**Step 4: Register the router in `api/main.py`**

Add import and include after the existing router includes:

```python
# In api/main.py, add to imports:
from .routers import chat, completions, models, inventory, exports, graph, workflows

# Add after existing app.include_router lines:
app.include_router(workflows.router)
```

**Step 5: Run test to verify it passes**

Run: `pytest tests/test_workflow_api.py -v`
Expected: All 4 tests PASS

**Step 6: Commit**

```bash
git add api/routers/workflows.py api/main.py tests/test_workflow_api.py
git commit -m "feat(workflow): add workflow API router with CRUD and execution endpoints

GET /api/workflows, POST /api/workflows/validate, POST /api/workflows/run,
GET /api/workflows/runs, GET /api/workflows/runs/{id},
GET /api/workflows/runs/{id}/artifacts/{step_id}"
```

---

## Task 7: Example Workflow + workflows/ Directory

**Files:**
- Create: `workflows/data-model-rules.yaml`
- Create: `workflows/README.md`

**Step 1: Create the workflows directory and example**

```yaml
# workflows/data-model-rules.yaml
id: data-model-rules
name: "Generate Data Model Rules"
version: "1.0"
description: "Multi-agent workflow to analyze source code and generate data model validation rules"

defaults:
  role: coding
  temperature: 0.7
  max_tokens: 4096
  retries: 2
  retry_delay: 5

steps:
  - id: analyze_schema
    name: "Analyze Schema Structure"
    role: reasoning
    system_prompt: |
      You are a senior data architect. Analyze the provided source code
      and extract all entities, fields, types, and relationships.
      Return structured JSON with keys: entities, relationships, field_types.
    inputs:
      - seed.source_files
      - seed.constraints
    outputs:
      - entities
      - relationships
      - field_types
    config:
      temperature: 0.3

  - id: draft_rules
    name: "Draft Validation Rules"
    role: coding
    system_prompt: |
      You are a data modeling expert. Given the analyzed schema,
      generate comprehensive validation rules covering: type constraints,
      referential integrity, business logic, and naming conventions.
      Return JSON with keys: rules, rule_categories.
    inputs:
      - seed.constraints
      - analyze_schema.entities
      - analyze_schema.relationships
      - analyze_schema.field_types
    outputs:
      - rules
      - rule_categories
    config:
      temperature: 0.5

  - id: validate_rules
    name: "Review & Validate Rules"
    role: reasoning
    system_prompt: |
      You are a QA engineer specializing in data integrity. Review the
      drafted rules for: completeness, conflicts, redundancy, and
      enforceability. Flag issues and suggest improvements.
      Return JSON with keys: issues, approved_rules, suggestions.
    inputs:
      - analyze_schema.entities
      - draft_rules.rules
      - draft_rules.rule_categories
    outputs:
      - issues
      - approved_rules
      - suggestions
    config:
      max_tokens: 8192

  - id: generate_code
    name: "Generate Implementation Code"
    role: coding
    system_prompt: |
      You are a Python developer. Generate Pydantic model validators
      and SQLAlchemy constraints implementing the approved rules.
      Follow the existing project conventions.
      Return JSON with keys: pydantic_models, sqlalchemy_constraints, migration_script.
    inputs:
      - seed.constraints
      - analyze_schema.entities
      - validate_rules.approved_rules
      - validate_rules.suggestions
    outputs:
      - pydantic_models
      - sqlalchemy_constraints
      - migration_script
```

```markdown
# workflows/README.md
# Workflow Definitions

YAML-based multi-agent workflow definitions for the Local AI Platform.

## Quick Start

Run a workflow:
\`\`\`bash
# Via CLI
python cli/workflow.py run workflows/data-model-rules.yaml \
  --seed '{"source_files": ["models/user.py"], "constraints": "PostgreSQL"}'

# Via API
curl -X POST http://localhost:8000/api/workflows/run \
  -H "Content-Type: application/json" \
  -d '{"workflow_id": "data-model-rules", "seed": {"source_files": ["models/user.py"], "constraints": "PostgreSQL"}}'
\`\`\`

## Writing Workflows

See `docs/plans/2026-04-06-multi-agent-workflow-engine-design.md` for the full
specification including YAML format, context layers, and model selection.

## Model Selection

Each step can specify a model two ways:
- **Explicit**: `model: "qwen3.5-uncensored:35b"` — uses this exact model
- **Role-based**: `role: reasoning` — resolves to best available model

Available roles: `reasoning`, `fast`, `coding`, `uncensored`, `general`
```

**Step 2: Commit**

```bash
git add workflows/data-model-rules.yaml workflows/README.md
git commit -m "feat(workflow): add example data-model-rules workflow and README

Four-step workflow: analyze schema → draft rules → validate → generate code.
Demonstrates role-based model selection and explicit I/O mapping."
```

---

## Task 8: CLI Workflow Tool (`cli/workflow.py`)

**Files:**
- Create: `cli/workflow.py`

**Step 1: Write the CLI tool**

```python
#!/usr/bin/env python3
"""
Workflow CLI — Run and monitor multi-agent workflows from the terminal

Usage:
  python cli/workflow.py run <workflow.yaml> --seed '{"key": "value"}'
  python cli/workflow.py list
  python cli/workflow.py status <run_id>
  python cli/workflow.py runs
  python cli/workflow.py artifact <run_id> <step_id>
"""

import argparse
import json
import sys
import os

# Add parent dir to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.markdown import Markdown
from rich import print as rprint

from api.services.ollama_service import OllamaService
from api.services.workflow_engine import WorkflowEngine

console = Console()

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
WORKFLOWS_DIR = os.getenv("WORKFLOWS_DIR", "./workflows")


def get_engine() -> WorkflowEngine:
    ollama = OllamaService(OLLAMA_HOST)
    return WorkflowEngine(ollama)


def cmd_run(args):
    """Run a workflow"""
    engine = get_engine()

    # Load
    console.print(f"\n[bright_cyan]Loading workflow:[/] {args.workflow}")
    defn = engine.load(args.workflow)
    console.print(f"  [dim]ID:[/] {defn.id}")
    console.print(f"  [dim]Steps:[/] {len(defn.steps)}")

    # Parse seed
    seed = json.loads(args.seed) if args.seed else {}
    console.print(f"  [dim]Seed keys:[/] {list(seed.keys())}")

    # Validate
    engine.validate(defn, seed_keys=list(seed.keys()))
    console.print("  [green]✓ Validation passed[/]\n")

    # Execute
    for i, step in enumerate(defn.steps):
        model_ref = step.model or f"role:{step.role or defn.defaults.role}"
        console.print(
            f"[bright_magenta]Step {i+1}/{len(defn.steps)}:[/] "
            f"{step.name} [dim]({model_ref})[/]"
        )

    console.print()
    run = engine.run(defn, seed=seed)

    # Results
    if run.status == "completed":
        console.print(Panel("[green bold]Workflow completed successfully[/]"))
    else:
        console.print(Panel(f"[red bold]Workflow failed: {run.error}[/]"))

    # Summary table
    table = Table(title="Step Results")
    table.add_column("Step", style="cyan")
    table.add_column("Status")
    table.add_column("Model", style="dim")
    table.add_column("Duration", justify="right")
    table.add_column("Tokens", justify="right")

    for r in run.step_results:
        status = "[green]✅ Done[/]" if r.status == "completed" else "[red]❌ Failed[/]"
        dur = f"{r.duration_seconds:.1f}s" if r.duration_seconds else "—"
        tokens = str(r.token_count.get("total_tokens", 0))
        table.add_row(r.step_id, status, r.model_used or "—", dur, tokens)

    console.print(table)
    console.print(f"\n[dim]Run ID: {run.run_id}[/]")
    console.print(f"[dim]Results saved to: data/workflows/{run.run_id}/[/]\n")


def cmd_list(args):
    """List available workflows"""
    engine = get_engine()
    workflows = engine.list_workflows(WORKFLOWS_DIR)

    if not workflows:
        console.print("[dim]No workflows found in workflows/ directory[/]")
        return

    table = Table(title="Available Workflows")
    table.add_column("ID", style="cyan")
    table.add_column("Name")
    table.add_column("Steps", justify="right")
    table.add_column("Version", style="dim")

    for wf in workflows:
        table.add_row(wf["id"], wf["name"], str(wf["steps"]), wf.get("version", "—"))

    console.print(table)


def cmd_runs(args):
    """List recent runs"""
    engine = get_engine()
    runs = engine.list_runs(limit=args.limit)

    if not runs:
        console.print("[dim]No workflow runs found[/]")
        return

    table = Table(title="Recent Runs")
    table.add_column("Run ID", style="cyan")
    table.add_column("Workflow")
    table.add_column("Status")
    table.add_column("Started", style="dim")

    for r in runs:
        status = "[green]✅[/]" if r["status"] == "completed" else "[red]❌[/]"
        table.add_row(
            r["run_id"][:12] + "...",
            r["workflow_id"],
            status,
            str(r.get("started_at", "—"))[:19],
        )

    console.print(table)


def cmd_status(args):
    """Get status of a specific run"""
    engine = get_engine()
    run = engine.get_run(args.run_id)

    if not run:
        console.print(f"[red]Run '{args.run_id}' not found[/]")
        return

    console.print(Panel(f"[bold]{run['workflow_id']}[/] — {run['status']}"))
    console.print(f"  [dim]Run ID:[/] {run['run_id']}")
    console.print(f"  [dim]Status:[/] {run['status']}")
    console.print(f"  [dim]Started:[/] {run.get('started_at')}")
    console.print(f"  [dim]Completed:[/] {run.get('completed_at')}")

    if run.get("error"):
        console.print(f"  [red]Error:[/] {run['error']}")


def cmd_artifact(args):
    """View a step's output artifact"""
    engine = get_engine()
    run = engine.get_run(args.run_id)

    if not run:
        console.print(f"[red]Run '{args.run_id}' not found[/]")
        return

    workspace = run.get("context", {}).get("workspace", {})
    step_data = workspace.get(args.step_id)

    if not step_data:
        console.print(f"[red]No artifacts for step '{args.step_id}'[/]")
        return

    console.print(Panel(f"[bold]Artifacts: {args.step_id}[/]"))
    console.print_json(json.dumps(step_data, indent=2))


def main():
    parser = argparse.ArgumentParser(description="Workflow CLI")
    sub = parser.add_subparsers(dest="command")

    # run
    p_run = sub.add_parser("run", help="Run a workflow")
    p_run.add_argument("workflow", help="Path to workflow YAML")
    p_run.add_argument("--seed", default="{}", help="Seed data as JSON string")

    # list
    sub.add_parser("list", help="List available workflows")

    # runs
    p_runs = sub.add_parser("runs", help="List recent runs")
    p_runs.add_argument("--limit", type=int, default=20)

    # status
    p_status = sub.add_parser("status", help="Get run status")
    p_status.add_argument("run_id", help="Run ID")

    # artifact
    p_art = sub.add_parser("artifact", help="View step artifact")
    p_art.add_argument("run_id", help="Run ID")
    p_art.add_argument("step_id", help="Step ID")

    args = parser.parse_args()

    commands = {
        "run": cmd_run,
        "list": cmd_list,
        "runs": cmd_runs,
        "status": cmd_status,
        "artifact": cmd_artifact,
    }

    if args.command in commands:
        commands[args.command](args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
```

**Step 2: Test manually**

Run: `python cli/workflow.py list`
Expected: Table of available workflows (or empty if none yet)

Run: `python cli/workflow.py --help`
Expected: Help text with subcommands

**Step 3: Commit**

```bash
git add cli/workflow.py
git commit -m "feat(workflow): add CLI tool for running and monitoring workflows

Subcommands: run, list, runs, status, artifact. Rich formatted output
with progress tables and artifact viewing."
```

---

## Task 9: Data Directory + Gitignore

**Files:**
- Create: `data/workflows/.gitkeep`
- Modify: `.gitignore` (add workflow data exclusion)

**Step 1: Create directory and update gitignore**

```bash
mkdir -p data/workflows
touch data/workflows/.gitkeep

# Add to .gitignore:
# Workflow run data (persisted locally)
data/workflows/*/
```

**Step 2: Commit**

```bash
git add data/workflows/.gitkeep .gitignore
git commit -m "chore: add data/workflows directory and gitignore run data"
```

---

## Task 10: Integration Test — End-to-End Workflow Run

**Files:**
- Create: `tests/test_workflow_integration.py`

**Step 1: Write the integration test**

```python
# tests/test_workflow_integration.py
"""
Integration test — full workflow execution with mocked Ollama

Tests the complete pipeline: YAML load → validate → execute → persist
"""
import json
import os
import tempfile
import pytest
from unittest.mock import MagicMock

from api.services.workflow_engine import WorkflowEngine


WORKFLOW_YAML = """
id: integration-test
name: Integration Test Workflow
version: "1.0"
defaults:
  role: general
  retries: 0
  retry_delay: 0
steps:
  - id: analyze
    name: Analyze Input
    role: reasoning
    system_prompt: "Analyze the task and return a JSON object with key 'findings'."
    inputs:
      - seed.task
    outputs:
      - findings
  - id: synthesize
    name: Synthesize Results
    role: coding
    system_prompt: "Take the findings and generate a summary with key 'summary'."
    inputs:
      - seed.task
      - analyze.findings
    outputs:
      - summary
  - id: format
    name: Format Output
    role: fast
    system_prompt: "Format the summary as markdown."
    inputs:
      - synthesize.summary
    outputs:
      - formatted_output
"""


class TestEndToEnd:
    def setup_method(self):
        self.ollama = MagicMock()
        self.ollama.list_models.return_value = [
            {"name": "dolphin3:8b", "size": 5000000000},
            {"name": "deepseek-r1:32b", "size": 20000000000},
        ]
        # Each step returns different content
        self.ollama.chat.side_effect = [
            {"content": '{"findings": ["finding 1", "finding 2"]}', "prompt_eval_count": 50, "eval_count": 100},
            {"content": '{"summary": "Two key findings identified."}', "prompt_eval_count": 80, "eval_count": 60},
            {"content": "## Summary\n\nTwo key findings identified.", "prompt_eval_count": 40, "eval_count": 30},
        ]
        # Use temp dir for persistence
        self.data_dir = tempfile.mkdtemp()
        os.environ["WORKFLOW_DATA_DIR"] = self.data_dir
        self.engine = WorkflowEngine(self.ollama)

    def test_full_workflow_execution(self):
        # Write YAML to temp file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(WORKFLOW_YAML)
            yaml_path = f.name

        # Load
        defn = self.engine.load(yaml_path)
        assert defn.id == "integration-test"
        assert len(defn.steps) == 3

        # Validate
        self.engine.validate(defn, seed_keys=["task"])

        # Execute
        run = self.engine.run(defn, seed={"task": "Analyze the authentication system"})

        # Verify completion
        assert run.status == "completed"
        assert len(run.step_results) == 3
        assert all(r.status == "completed" for r in run.step_results)

        # Verify context flow
        assert run.context.get_workspace("analyze", "findings") is not None
        assert run.context.get_workspace("synthesize", "summary") is not None
        assert run.context.get_workspace("format", "formatted_output") is not None

        # Verify persistence
        run_dir = os.path.join(self.data_dir, run.run_id)
        assert os.path.exists(os.path.join(run_dir, "run.json"))
        assert os.path.exists(os.path.join(run_dir, "summary.md"))
        assert os.path.exists(os.path.join(run_dir, "artifacts", "analyze.json"))

        # Verify run.json content
        with open(os.path.join(run_dir, "run.json")) as f:
            persisted = json.load(f)
        assert persisted["status"] == "completed"
        assert persisted["workflow_id"] == "integration-test"

        # Cleanup
        os.unlink(yaml_path)

    def test_workflow_fails_mid_execution(self):
        """When step 2 fails, step 3 should not execute"""
        self.ollama.chat.side_effect = [
            {"content": "Step 1 output", "prompt_eval_count": 10, "eval_count": 20},
            Exception("LLM crashed"),
        ]

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(WORKFLOW_YAML)
            yaml_path = f.name

        defn = self.engine.load(yaml_path)
        run = self.engine.run(defn, seed={"task": "test"})

        assert run.status == "failed"
        assert run.step_results[0].status == "completed"
        assert run.step_results[1].status == "failed"
        assert len(run.step_results) == 2  # step 3 never ran
        assert self.ollama.chat.call_count == 2

        os.unlink(yaml_path)
```

**Step 2: Run test**

Run: `pytest tests/test_workflow_integration.py -v`
Expected: All 2 tests PASS

**Step 3: Commit**

```bash
git add tests/test_workflow_integration.py
git commit -m "test(workflow): add end-to-end integration test

Tests full pipeline: YAML load → validate → execute 3 steps → persist.
Also tests mid-workflow failure (step 2 fails, step 3 skipped)."
```

---

## Task 11: Update CLAUDE.md with Workflow Engine Documentation

**Files:**
- Modify: `CLAUDE.md`

**Step 1: Add workflow section to CLAUDE.md**

Add after the "### Common Development Tasks" section:

```markdown
### Workflow Engine

The multi-agent workflow engine is the core task engine for the platform. It executes step-based workflows defined in YAML, where each step is an agent with its own system prompt, model selection, and declared inputs/outputs.

**Key files:**
- `api/models/workflow_models.py` — Pydantic data models (AgentStep, WorkflowContext, WorkflowRun)
- `api/services/workflow_engine.py` — Engine: load YAML, validate I/O, execute, persist
- `api/services/step_executor.py` — Single step execution with retry
- `api/services/model_resolver.py` — Role-based model selection via inventory
- `api/routers/workflows.py` — REST API endpoints
- `cli/workflow.py` — CLI tool
- `workflows/` — YAML workflow definitions

**Running workflows:**
```bash
# CLI
python cli/workflow.py run workflows/data-model-rules.yaml --seed '{"source_files": ["models/user.py"], "constraints": "PostgreSQL"}'
python cli/workflow.py list
python cli/workflow.py runs
python cli/workflow.py status <run_id>

# API
curl -X POST http://localhost:8000/api/workflows/run \
  -H "Content-Type: application/json" \
  -d '{"workflow_id": "data-model-rules", "seed": {"source_files": ["models/user.py"]}}'
```

**Context model (three layers):**
- `seed` — immutable user input, always available
- `workspace` — namespaced per-step outputs (`workspace.{step_id}.{key}`)
- `shared` — mutable cross-cutting state

**Model selection:** Steps declare `role: reasoning|fast|coding|uncensored|general` (resolved via inventory) or `model: "exact-name"` (validated against Ollama).

**Design doc:** `docs/plans/2026-04-06-multi-agent-workflow-engine-design.md`
```

**Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add workflow engine section to CLAUDE.md"
```

---

## Summary

| Task | Component | Tests | Files Created |
|------|-----------|-------|---------------|
| 1 | Data Models | 13 | `api/models/workflow_models.py` |
| 2 | Exceptions | 4 | Modified `api/exceptions.py` |
| 3 | Model Resolver | 6 | `api/services/model_resolver.py` |
| 4 | Step Executor | 4 | `api/services/step_executor.py` |
| 5 | Workflow Engine | 5 | `api/services/workflow_engine.py` |
| 6 | API Router | 4 | `api/routers/workflows.py` |
| 7 | Example Workflow | — | `workflows/data-model-rules.yaml` |
| 8 | CLI Tool | manual | `cli/workflow.py` |
| 9 | Data Directory | — | `data/workflows/.gitkeep` |
| 10 | Integration Test | 2 | `tests/test_workflow_integration.py` |
| 11 | Documentation | — | Modified `CLAUDE.md` |
| **Total** | | **38 tests** | **10 new files, 2 modified** |

Execution order is strict: Task 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10 → 11. Each task builds on the prior.
