# Workflow Prompt Framework Implementation Plan (Part A)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the Enclave workflow engine into a disciplined prompt-engineering framework with a 5-part prompt template, model-family adapters, 6-point hook lifecycle, declarative JSON-schema validation, and retry-with-feedback — without breaking existing v1 workflows.

**Architecture:** New `prompt_composer.py` assembles prompts from a Jinja 5-part template using role files from `prompts/roles/`. New `model_adapters.py` applies family-specific tweaks (dolphin/llama3/mistral/qwen/yi/uncensored-common). New `hook_bus.py` dispatches 6 lifecycle events. Six built-in hooks under `api/hooks/builtins/` handle JSON validation, refusal detection, retry-with-feedback, token budgeting, output logging, and few-shot injection. Custom hooks auto-discovered from `api/hooks/custom/`. Workflow YAML gains optional v2 schema (`schema_version: 2`, structured `prompt`, `output_schema`, `hooks` blocks). v1 workflows continue to run unchanged.

**Tech Stack:** Python 3.11, Pydantic v2, Jinja2, jsonschema, pytest, tiktoken (optional), existing Ollama backend.

**Spec:** `docs/superpowers/specs/2026-04-20-prompts-and-hooks-design.md` (Part A, sections A.3–A.10)

---

## File Structure

### Created
- `api/services/hook_bus.py` — Hook protocol + bus
- `api/services/prompt_composer.py` — 5-part prompt assembly
- `api/services/model_adapters.py` — Family-level adapter registry
- `api/hooks/__init__.py` — Auto-discovery entry
- `api/hooks/builtins/__init__.py`
- `api/hooks/builtins/json_schema.py`
- `api/hooks/builtins/refusal_detector.py`
- `api/hooks/builtins/retry_with_feedback.py`
- `api/hooks/builtins/token_budget.py`
- `api/hooks/builtins/few_shot_injector.py`
- `api/hooks/builtins/output_logger.py`
- `api/hooks/custom/__init__.py`
- `api/hooks/custom/.gitkeep`
- `prompts/roles/senior_data_architect.md`
- `prompts/roles/qa_engineer.md`
- `prompts/roles/python_developer.md`
- `prompts/templates/five_part.jinja`
- `tests/unit/test_hook_bus.py`
- `tests/unit/test_prompt_composer.py`
- `tests/unit/test_model_adapters.py`
- `tests/hooks/test_json_schema_hook.py`
- `tests/hooks/test_refusal_detector_hook.py`
- `tests/hooks/test_retry_with_feedback_hook.py`
- `tests/hooks/test_token_budget_hook.py`
- `tests/hooks/test_few_shot_injector_hook.py`
- `tests/hooks/test_output_logger_hook.py`
- `tests/integration/conftest.py` — FakeOllamaClient fixture
- `tests/integration/test_pipeline_happy_path.py`
- `tests/integration/test_retry_with_feedback_flow.py`
- `tests/integration/test_model_escalation.py`
- `tests/integration/test_token_budget_truncation.py`
- `tests/integration/test_custom_hook_discovery.py`
- `tests/integration/test_v1_legacy_regression.py`
- `tests/e2e/test_family_adapters_live.py`

### Modified
- `api/models/workflow_models.py` — Add v2 fields: `StepPrompt`, `HookSpec`, `schema_version`, `context`, `schemas`, `output_schema` on steps
- `api/services/step_executor.py` — Wire composer + adapter + hook bus; replace inline prompt assembly
- `api/services/workflow_engine.py` — Instantiate hook bus; pass to executor; fire `before_workflow`/`after_workflow`
- `cli/workflow.py` — Add `upgrade` subcommand
- `setup/requirements.txt` — Add `jinja2`, `jsonschema` (tiktoken optional)

---

## Task 1: Hook Protocol + Data Types

**Files:**
- Create: `api/services/hook_bus.py`
- Test: `tests/unit/test_hook_bus.py`

- [ ] **Step 1.1: Write the failing tests for HookContext / HookResult / Hook protocol**

`tests/unit/test_hook_bus.py`:
```python
import pytest
from dataclasses import FrozenInstanceError
from api.services.hook_bus import HookContext, HookResult, Hook


def test_hook_result_defaults_to_continue():
    result = HookResult(action="continue")
    assert result.action == "continue"
    assert result.mutations == {}
    assert result.feedback is None


def test_hook_result_with_feedback():
    result = HookResult(action="retry", feedback="missing key 'x'")
    assert result.action == "retry"
    assert result.feedback == "missing key 'x'"


def test_hook_result_action_rejects_invalid():
    # Literal enforcement is static but we assert runtime accepts valid values
    for action in ("continue", "retry", "fail", "skip"):
        HookResult(action=action)  # does not raise


def test_hook_context_default_fields():
    ctx = HookContext(workflow=None, step=None)
    assert ctx.attempt == 0
    assert ctx.prompt is None
    assert ctx.output is None
    assert ctx.parsed is None
    assert ctx.error is None


def test_hook_protocol_is_callable_with_ctx():
    class MyHook:
        name = "noop"
        stage = "after_step"
        def __call__(self, ctx: HookContext) -> HookResult:
            return HookResult(action="continue")

    hook: Hook = MyHook()
    result = hook(HookContext(workflow=None, step=None))
    assert result.action == "continue"
```

- [ ] **Step 1.2: Run tests to verify failure**

Run: `source venv/bin/activate && pytest tests/unit/test_hook_bus.py -v`
Expected: `ModuleNotFoundError: No module named 'api.services.hook_bus'`

- [ ] **Step 1.3: Create `api/services/hook_bus.py` with data types**

```python
"""
Hook Bus — Protocol, data types, and dispatch for the 6-point step lifecycle.

Stages (in execution order):
  before_workflow → before_step → transform_prompt → [model call]
    → after_step → validate_output → on_failure (only if rejected)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Protocol, runtime_checkable


Stage = Literal[
    "before_workflow",
    "before_step",
    "transform_prompt",
    "after_step",
    "validate_output",
    "on_failure",
]

Action = Literal["continue", "retry", "fail", "skip"]


@dataclass
class HookContext:
    """Mutable context passed to every hook invocation."""
    workflow: Any = None                  # WorkflowRun, forward-ref to avoid import cycle
    step: Any = None                      # AgentStep | None at workflow stage
    prompt: Any = None                    # ComposedPrompt | None, mutable at transform_prompt
    output: str | None = None             # raw model output, set after model call
    parsed: Any = None                    # set after successful validation
    error: Any = None                     # ValidationError | None, set at on_failure
    attempt: int = 0


@dataclass
class HookResult:
    """Hook return value. `action` drives dispatcher behavior."""
    action: Action = "continue"
    mutations: dict = field(default_factory=dict)
    feedback: str | None = None


@runtime_checkable
class Hook(Protocol):
    """Any callable with `name` and `stage` attributes matching this signature."""
    name: str
    stage: Stage
    def __call__(self, ctx: HookContext) -> HookResult: ...
```

- [ ] **Step 1.4: Run tests to verify they pass**

Run: `source venv/bin/activate && pytest tests/unit/test_hook_bus.py -v`
Expected: 5 passed.

- [ ] **Step 1.5: Commit**

```bash
git add api/services/hook_bus.py tests/unit/test_hook_bus.py
git commit -m "feat(workflow): add hook protocol and context/result data types"
```

---

## Task 2: HookBus Registration + Dispatch

**Files:**
- Modify: `api/services/hook_bus.py` (add `HookBus` class)
- Modify: `tests/unit/test_hook_bus.py` (add bus tests)

- [ ] **Step 2.1: Add failing tests for `HookBus`**

Append to `tests/unit/test_hook_bus.py`:
```python
from api.services.hook_bus import HookBus


def _make_hook(name, stage, action="continue", feedback=None, mutations=None):
    class _H:
        pass
    h = _H()
    h.name = name
    h.stage = stage
    def call(ctx):
        return HookResult(action=action, feedback=feedback, mutations=mutations or {})
    h.__call__ = call
    # make instance callable
    h_callable = lambda ctx, _h=h: _h.__call__(ctx)
    h_callable.name = name
    h_callable.stage = stage
    return h_callable


def test_bus_register_and_dispatch_single_hook():
    bus = HookBus()
    bus.register(_make_hook("a", "after_step"))
    ctx = HookContext()
    results = bus.dispatch("after_step", ctx)
    assert len(results) == 1
    assert results[0].action == "continue"


def test_bus_runs_hooks_in_registration_order():
    bus = HookBus()
    order = []
    def h(name):
        def _call(ctx):
            order.append(name)
            return HookResult(action="continue")
        _call.name = name
        _call.stage = "after_step"
        return _call
    bus.register(h("first"))
    bus.register(h("second"))
    bus.register(h("third"))
    bus.dispatch("after_step", HookContext())
    assert order == ["first", "second", "third"]


def test_bus_short_circuits_on_non_continue():
    bus = HookBus()
    order = []
    def h(name, action):
        def _call(ctx):
            order.append(name)
            return HookResult(action=action)
        _call.name = name
        _call.stage = "after_step"
        return _call
    bus.register(h("a", "continue"))
    bus.register(h("b", "fail"))
    bus.register(h("c", "continue"))
    results = bus.dispatch("after_step", HookContext())
    assert order == ["a", "b"]  # c never ran
    assert results[-1].action == "fail"


def test_bus_validate_output_requires_all_continue():
    bus = HookBus()
    bus.register(_make_hook("schema", "validate_output", action="continue"))
    bus.register(_make_hook("refusal", "validate_output", action="continue"))
    results = bus.dispatch("validate_output", HookContext())
    assert all(r.action == "continue" for r in results)


def test_bus_validate_output_stops_at_first_rejection():
    bus = HookBus()
    order = []
    def h(name, action):
        def _call(ctx):
            order.append(name)
            return HookResult(action=action)
        _call.name = name
        _call.stage = "validate_output"
        return _call
    bus.register(h("schema", "fail"))
    bus.register(h("refusal", "continue"))
    results = bus.dispatch("validate_output", HookContext())
    assert order == ["schema"]
    assert results[-1].action == "fail"


def test_bus_rejects_wrong_stage_registration():
    bus = HookBus()
    def h(ctx):
        return HookResult()
    h.name = "bad"
    h.stage = "nonsense_stage"
    with pytest.raises(ValueError, match="invalid stage"):
        bus.register(h)


def test_bus_custom_hooks_run_after_builtin_hooks():
    bus = HookBus()
    order = []
    def h(name, source):
        def _call(ctx):
            order.append(name)
            return HookResult(action="continue")
        _call.name = name
        _call.stage = "after_step"
        return _call
    bus.register(h("builtin1", "builtin"), source="builtin")
    bus.register(h("custom1", "custom"), source="custom")
    bus.register(h("builtin2", "builtin"), source="builtin")
    bus.dispatch("after_step", HookContext())
    assert order == ["builtin1", "builtin2", "custom1"]
```

- [ ] **Step 2.2: Run tests to verify failure**

Run: `pytest tests/unit/test_hook_bus.py -v`
Expected: 7 failing tests — `AttributeError: module 'api.services.hook_bus' has no attribute 'HookBus'`.

- [ ] **Step 2.3: Append `HookBus` implementation to `api/services/hook_bus.py`**

```python
# ── HookBus ────────────────────────────────────────────────────────────────

_VALID_STAGES = {
    "before_workflow", "before_step", "transform_prompt",
    "after_step", "validate_output", "on_failure",
}


class HookBus:
    """Registers and dispatches hooks by stage.

    Dispatch rules:
    - Same-stage hooks run in registration order.
    - Built-in hooks (source='builtin') run before custom hooks (source='custom').
    - First hook returning action != 'continue' short-circuits the remainder.
    """

    def __init__(self) -> None:
        self._hooks: dict[Stage, list[tuple[int, Hook]]] = {
            stage: [] for stage in _VALID_STAGES
        }
        # priority: 0 = builtin, 1 = custom — sorted ascending on dispatch
        self._counter = 0

    def register(self, hook, source: str = "builtin") -> None:
        stage = getattr(hook, "stage", None)
        if stage not in _VALID_STAGES:
            raise ValueError(f"invalid stage: {stage!r}")
        priority = 0 if source == "builtin" else 1
        self._counter += 1
        # tuple (priority, insertion_order, hook) — stable sort respects insertion
        self._hooks[stage].append((priority, self._counter, hook))

    def dispatch(self, stage: Stage, ctx: HookContext) -> list[HookResult]:
        if stage not in _VALID_STAGES:
            raise ValueError(f"invalid stage: {stage!r}")
        ordered = sorted(self._hooks[stage], key=lambda t: (t[0], t[1]))
        results: list[HookResult] = []
        for _priority, _order, hook in ordered:
            result = hook(ctx)
            results.append(result)
            # apply mutations to ctx
            for k, v in (result.mutations or {}).items():
                setattr(ctx, k, v)
            if result.action != "continue":
                break
        return results

    def clear(self) -> None:
        for stage in self._hooks:
            self._hooks[stage] = []
        self._counter = 0
```

- [ ] **Step 2.4: Run tests to verify they pass**

Run: `pytest tests/unit/test_hook_bus.py -v`
Expected: 12 passed (5 from Task 1 + 7 new).

- [ ] **Step 2.5: Commit**

```bash
git add api/services/hook_bus.py tests/unit/test_hook_bus.py
git commit -m "feat(workflow): add HookBus with ordered dispatch and short-circuit"
```

---

## Task 3: Hook Auto-Discovery from `api/hooks/custom/`

**Files:**
- Create: `api/hooks/__init__.py`
- Create: `api/hooks/builtins/__init__.py`
- Create: `api/hooks/custom/__init__.py`
- Create: `api/hooks/custom/.gitkeep`
- Modify: `api/services/hook_bus.py` — add `discover_and_register`
- Test: `tests/unit/test_hook_bus.py` — add discovery tests

- [ ] **Step 3.1: Add failing discovery test**

Append to `tests/unit/test_hook_bus.py`:
```python
import tempfile
import textwrap
from pathlib import Path


def test_discover_registers_hooks_from_directory(tmp_path, monkeypatch):
    hook_file = tmp_path / "my_custom.py"
    hook_file.write_text(textwrap.dedent("""
        from api.services.hook_bus import HookResult, register_hook

        @register_hook(stage="after_step", name="custom_noop")
        def noop(ctx):
            return HookResult(action="continue")
    """))

    bus = HookBus()
    bus.discover_and_register(tmp_path, source="custom")
    # Verify by dispatching — if registered, hook list has 1 entry
    assert len(bus._hooks["after_step"]) == 1
    # Dispatch works
    results = bus.dispatch("after_step", HookContext())
    assert len(results) == 1
    assert results[0].action == "continue"


def test_discover_skips_files_without_register_hook_decorator(tmp_path):
    (tmp_path / "not_a_hook.py").write_text("x = 1\n")
    bus = HookBus()
    bus.discover_and_register(tmp_path, source="custom")
    assert len(bus._hooks["after_step"]) == 0


def test_discover_ignores_dunder_files(tmp_path):
    (tmp_path / "__init__.py").write_text("x = 1\n")
    bus = HookBus()
    bus.discover_and_register(tmp_path, source="custom")
    assert all(len(v) == 0 for v in bus._hooks.values())
```

- [ ] **Step 3.2: Run tests to verify failure**

Run: `pytest tests/unit/test_hook_bus.py -v`
Expected: 3 new tests fail with `AttributeError: ... has no attribute 'register_hook'` or `... 'discover_and_register'`.

- [ ] **Step 3.3: Append `register_hook` decorator and `discover_and_register` to `api/services/hook_bus.py`**

```python
# ── Registration decorator + auto-discovery ────────────────────────────────

import importlib.util
import sys
from pathlib import Path as _Path

# Module-level registry of decorated hooks, keyed by absolute path of declaring file.
# Populated when files are imported; consumed by HookBus.discover_and_register.
_PENDING_HOOKS: list = []


def register_hook(stage: Stage, name: str):
    """Decorator to mark a function as a hook for auto-discovery."""
    if stage not in _VALID_STAGES:
        raise ValueError(f"invalid stage: {stage!r}")

    def _decorate(fn):
        fn.stage = stage
        fn.name = name
        _PENDING_HOOKS.append(fn)
        return fn

    return _decorate


def _extend_HookBus_discovery():
    def discover_and_register(self, directory, source: str = "custom") -> int:
        """Import every *.py file under `directory` (non-recursive) and register
        any functions decorated with @register_hook. Returns count registered."""
        directory = _Path(directory)
        if not directory.is_dir():
            return 0
        before = len(_PENDING_HOOKS)
        for py_file in sorted(directory.glob("*.py")):
            if py_file.name.startswith("__") or py_file.name == ".gitkeep":
                continue
            module_name = f"_hooks_auto_{py_file.stem}_{id(py_file)}"
            spec = importlib.util.spec_from_file_location(module_name, py_file)
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
        newly_added = _PENDING_HOOKS[before:]
        for hook in newly_added:
            self.register(hook, source=source)
        # Clear what we just registered so a second bus doesn't double-register
        del _PENDING_HOOKS[before:]
        return len(newly_added)
    HookBus.discover_and_register = discover_and_register

_extend_HookBus_discovery()
```

- [ ] **Step 3.4: Create empty package init files**

```bash
mkdir -p api/hooks/builtins api/hooks/custom
touch api/hooks/__init__.py api/hooks/builtins/__init__.py api/hooks/custom/__init__.py api/hooks/custom/.gitkeep
```

- [ ] **Step 3.5: Run tests to verify they pass**

Run: `pytest tests/unit/test_hook_bus.py -v`
Expected: 15 passed.

- [ ] **Step 3.6: Commit**

```bash
git add api/services/hook_bus.py api/hooks/ tests/unit/test_hook_bus.py
git commit -m "feat(workflow): add @register_hook decorator and hook auto-discovery"
```

---

## Task 4: ComposedPrompt Data Type

**Files:**
- Create: `api/services/prompt_composer.py` (data type only in this task)
- Test: `tests/unit/test_prompt_composer.py`

- [ ] **Step 4.1: Write failing tests for `ComposedPrompt`**

`tests/unit/test_prompt_composer.py`:
```python
import pytest
from api.services.prompt_composer import ComposedPrompt


def test_composed_prompt_has_required_fields():
    p = ComposedPrompt(
        system="You are X.",
        user="Do the thing.",
        params={"temperature": 0.3},
    )
    assert p.system == "You are X."
    assert p.user == "Do the thing."
    assert p.params == {"temperature": 0.3}


def test_composed_prompt_as_messages():
    p = ComposedPrompt(system="sys", user="usr", params={})
    assert p.as_messages() == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "usr"},
    ]


def test_composed_prompt_is_mutable():
    p = ComposedPrompt(system="sys", user="usr", params={})
    p.user = "new user content"
    assert p.user == "new user content"
```

- [ ] **Step 4.2: Run tests to verify failure**

Run: `pytest tests/unit/test_prompt_composer.py -v`
Expected: `ModuleNotFoundError: No module named 'api.services.prompt_composer'`.

- [ ] **Step 4.3: Create `api/services/prompt_composer.py` with `ComposedPrompt`**

```python
"""
Prompt Composer — Assembles 5-part prompts from workflow YAML.

Five parts: role, context, task, constraints, output_format.
Composition pipeline:
  load role → merge context → render template → return ComposedPrompt.

Model-family adapters mutate ComposedPrompt AFTER composition.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ComposedPrompt:
    """A prompt ready to send to an Ollama model."""
    system: str
    user: str
    params: dict[str, Any] = field(default_factory=dict)

    def as_messages(self) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": self.system},
            {"role": "user", "content": self.user},
        ]
```

- [ ] **Step 4.4: Run tests to verify they pass**

Run: `pytest tests/unit/test_prompt_composer.py -v`
Expected: 3 passed.

- [ ] **Step 4.5: Commit**

```bash
git add api/services/prompt_composer.py tests/unit/test_prompt_composer.py
git commit -m "feat(workflow): add ComposedPrompt data type"
```

---

## Task 5: Jinja 5-Part Template + Role Files

**Files:**
- Create: `prompts/templates/five_part.jinja`
- Create: `prompts/roles/senior_data_architect.md`
- Create: `prompts/roles/qa_engineer.md`
- Create: `prompts/roles/python_developer.md`

- [ ] **Step 5.1: Create the five-part Jinja template**

`prompts/templates/five_part.jinja`:
```jinja
{{ role }}

## Context
{{ context }}

## Task
{{ task }}

## Constraints
{% for c in constraints -%}
- {{ c }}
{% endfor %}
## Output Format
Return a single JSON object matching this schema. No prose, no markdown fences:
{{ output_schema_json }}
{% if few_shot_example %}

## Example
Input: {{ few_shot_example.input }}
Output: {{ few_shot_example.output_json }}
{% endif %}
```

- [ ] **Step 5.2: Create role files**

`prompts/roles/senior_data_architect.md`:
```markdown
You are a senior data architect with 15+ years designing production schemas
for high-throughput systems. You think in terms of entities, invariants,
normal forms, and referential integrity. You are precise, terse, and you
never guess — if source material is ambiguous, you flag it explicitly
rather than inventing structure.
```

`prompts/roles/qa_engineer.md`:
```markdown
You are a QA engineer specializing in data integrity. You review proposed
rules and validations for completeness, internal consistency, redundancy,
and enforceability. You flag conflicts and ambiguities rather than
silently accepting them.
```

`prompts/roles/python_developer.md`:
```markdown
You are a senior Python developer fluent in Pydantic v2 and SQLAlchemy 2.0.
You write focused, idiomatic code that follows existing project conventions.
You prefer composition over inheritance and avoid unnecessary abstractions.
You never use deprecated APIs.
```

- [ ] **Step 5.3: Commit**

```bash
git add prompts/templates/five_part.jinja prompts/roles/
git commit -m "feat(workflow): add 5-part Jinja template and seed role library"
```

---

## Task 6: PromptComposer — Template Rendering

**Files:**
- Modify: `api/services/prompt_composer.py` (add `PromptComposer` class)
- Modify: `tests/unit/test_prompt_composer.py` (add composer tests)
- Modify: `setup/requirements.txt` (add jinja2)

- [ ] **Step 6.1: Add `jinja2` to requirements and install**

Edit `setup/requirements.txt` — append the block:
```
# Prompt framework
jinja2>=3.1
jsonschema>=4.0
```

Run: `pip install jinja2 jsonschema`

- [ ] **Step 6.2: Add failing tests for `PromptComposer`**

Append to `tests/unit/test_prompt_composer.py`:
```python
import json
from pathlib import Path
from api.services.prompt_composer import PromptComposer


@pytest.fixture
def composer(tmp_path):
    roles_dir = tmp_path / "roles"
    roles_dir.mkdir()
    (roles_dir / "test_role.md").write_text("You are a test role.\n")
    templates_dir = tmp_path / "templates"
    templates_dir.mkdir()
    (templates_dir / "five_part.jinja").write_text(
        "{{ role }}\n\n## Context\n{{ context }}\n\n## Task\n{{ task }}\n\n"
        "## Constraints\n{% for c in constraints %}- {{ c }}\n{% endfor %}\n"
        "## Output Format\n{{ output_schema_json }}"
    )
    return PromptComposer(roles_dir=roles_dir, templates_dir=templates_dir)


def test_composer_uses_role_ref(composer):
    prompt = composer.compose(
        role_ref="test_role",
        role_inline=None,
        context="project context",
        task="do the thing",
        constraints=["no markdown"],
        output_schema={"type": "object"},
    )
    assert "You are a test role." in prompt.system
    assert "project context" in prompt.system
    assert "do the thing" in prompt.system
    assert "- no markdown" in prompt.system
    assert '"type": "object"' in prompt.system


def test_composer_uses_role_inline_when_no_ref(composer):
    prompt = composer.compose(
        role_ref=None,
        role_inline="You are inline.",
        context="ctx",
        task="t",
        constraints=[],
        output_schema={},
    )
    assert "You are inline." in prompt.system


def test_composer_raises_on_missing_role_ref(composer):
    with pytest.raises(FileNotFoundError):
        composer.compose(
            role_ref="does_not_exist",
            role_inline=None,
            context="", task="", constraints=[], output_schema={},
        )


def test_composer_raises_when_both_role_ref_and_inline_missing(composer):
    with pytest.raises(ValueError, match="role_ref or role_inline"):
        composer.compose(
            role_ref=None,
            role_inline=None,
            context="", task="", constraints=[], output_schema={},
        )


def test_composer_includes_few_shot_example_when_given(composer):
    prompt = composer.compose(
        role_ref="test_role",
        role_inline=None,
        context="",
        task="t",
        constraints=[],
        output_schema={"type": "object"},
        few_shot_example={"input": "in", "output": {"k": "v"}},
    )
    # Example rendered after output format
    # (template from fixture doesn't include example block; test with real template separately)
    assert "You are a test role." in prompt.system


def test_composer_builds_user_message_from_inputs(composer):
    prompt = composer.compose(
        role_ref="test_role",
        role_inline=None,
        context="", task="t", constraints=[],
        output_schema={},
        resolved_inputs={"source_files": ["models/user.py"], "constraints": "pg"},
    )
    # User message contains each input as a labeled block
    assert "source_files" in prompt.user
    assert "models/user.py" in prompt.user
    assert "constraints" in prompt.user
    assert "pg" in prompt.user


def test_composer_user_message_default_when_no_inputs(composer):
    prompt = composer.compose(
        role_ref="test_role",
        role_inline=None,
        context="", task="t", constraints=[],
        output_schema={},
    )
    assert prompt.user.strip() != ""
    assert "Complete" in prompt.user or "task" in prompt.user.lower()
```

- [ ] **Step 6.3: Run tests to verify failure**

Run: `pytest tests/unit/test_prompt_composer.py -v`
Expected: `AttributeError: ... has no attribute 'PromptComposer'`.

- [ ] **Step 6.4: Append `PromptComposer` to `api/services/prompt_composer.py`**

```python
# ── PromptComposer ─────────────────────────────────────────────────────────

import json as _json
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape


class PromptComposer:
    """Composes a 5-part prompt from role, context, task, constraints, schema."""

    def __init__(self, roles_dir: Path, templates_dir: Path):
        self.roles_dir = Path(roles_dir)
        self.templates_dir = Path(templates_dir)
        self._env = Environment(
            loader=FileSystemLoader(str(self.templates_dir)),
            autoescape=select_autoescape(disabled_extensions=("jinja",), default=False),
            trim_blocks=False,
            lstrip_blocks=False,
        )

    def compose(
        self,
        role_ref: str | None,
        role_inline: str | None,
        context: str,
        task: str,
        constraints: list[str],
        output_schema: dict,
        resolved_inputs: dict | None = None,
        few_shot_example: dict | None = None,
        template_name: str = "five_part.jinja",
        params: dict | None = None,
    ) -> ComposedPrompt:
        role_text = self._load_role(role_ref, role_inline)
        few_shot_rendered = None
        if few_shot_example:
            few_shot_rendered = {
                "input": few_shot_example.get("input", ""),
                "output_json": _json.dumps(few_shot_example.get("output", {}), indent=2),
            }

        template = self._env.get_template(template_name)
        system = template.render(
            role=role_text.strip(),
            context=context or "",
            task=task or "",
            constraints=constraints or [],
            output_schema_json=_json.dumps(output_schema or {}, indent=2),
            few_shot_example=few_shot_rendered,
        )

        user = self._build_user_message(resolved_inputs or {})
        return ComposedPrompt(system=system, user=user, params=params or {})

    def _load_role(self, ref: str | None, inline: str | None) -> str:
        if ref:
            path = self.roles_dir / f"{ref}.md"
            return path.read_text(encoding="utf-8")
        if inline:
            return inline
        raise ValueError("PromptComposer.compose requires role_ref or role_inline")

    def _build_user_message(self, inputs: dict) -> str:
        if not inputs:
            return "Complete your assigned task."
        lines = ["## Inputs\n"]
        for key, value in inputs.items():
            if isinstance(value, (dict, list)):
                lines.append(f"### {key}\n```json\n{_json.dumps(value, indent=2)}\n```\n")
            else:
                lines.append(f"### {key}\n{value}\n")
        lines.append("\nComplete your assigned task using the inputs above.")
        return "\n".join(lines)
```

- [ ] **Step 6.5: Run tests to verify they pass**

Run: `pytest tests/unit/test_prompt_composer.py -v`
Expected: 10 passed.

- [ ] **Step 6.6: Commit**

```bash
git add api/services/prompt_composer.py tests/unit/test_prompt_composer.py setup/requirements.txt
git commit -m "feat(workflow): add PromptComposer with Jinja 5-part rendering"
```

---

## Task 7: ModelAdapter Base + Default + Registry

**Files:**
- Create: `api/services/model_adapters.py`
- Test: `tests/unit/test_model_adapters.py`

- [ ] **Step 7.1: Write failing tests for `ModelAdapter` + `resolve_adapter`**

`tests/unit/test_model_adapters.py`:
```python
import pytest
from api.services.prompt_composer import ComposedPrompt
from api.services.model_adapters import (
    ModelAdapter,
    DefaultAdapter,
    resolve_adapter,
)


def _mk_prompt():
    return ComposedPrompt(system="sys", user="usr", params={"temperature": 0.5})


def test_default_adapter_leaves_prompt_unchanged():
    adapter = DefaultAdapter()
    prompt, params = adapter.prepare(_mk_prompt(), {"temperature": 0.5})
    assert prompt.system == "sys"
    assert prompt.user == "usr"
    assert params == {"temperature": 0.5}


def test_default_adapter_refusal_signatures_is_empty():
    assert DefaultAdapter().refusal_signatures() == []


def test_default_adapter_stop_sequences_is_empty():
    assert DefaultAdapter().stop_sequences() == []


def test_resolve_adapter_returns_default_for_unknown_model():
    adapter = resolve_adapter("some-unknown-model")
    assert isinstance(adapter, DefaultAdapter)
```

- [ ] **Step 7.2: Run tests to verify failure**

Run: `pytest tests/unit/test_model_adapters.py -v`
Expected: `ModuleNotFoundError: No module named 'api.services.model_adapters'`.

- [ ] **Step 7.3: Create `api/services/model_adapters.py` with base + default + registry**

```python
"""
Model-Family Adapters — Small per-family tweaks to prompts and Ollama params.

Lookup is keyed by substring match on the resolved Ollama model name.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .prompt_composer import ComposedPrompt


@dataclass
class ModelAdapter:
    """Base adapter. Subclasses override methods to add family behavior."""
    family: str = "default"

    def prepare(
        self, prompt: ComposedPrompt, params: dict[str, Any]
    ) -> tuple[ComposedPrompt, dict[str, Any]]:
        """Return possibly-mutated prompt + final Ollama params."""
        return prompt, params

    def refusal_signatures(self) -> list[str]:
        """Patterns refusal_detector uses for this family."""
        return []

    def stop_sequences(self) -> list[str]:
        return []


class DefaultAdapter(ModelAdapter):
    family = "default"


# ── Registry ────────────────────────────────────────────────────────────────

_FAMILY_PATTERNS: list[tuple[re.Pattern, type]] = []  # populated below


def _register(pattern: str, adapter_cls: type) -> None:
    _FAMILY_PATTERNS.append((re.compile(pattern, re.IGNORECASE), adapter_cls))


def resolve_adapter(model_name: str) -> ModelAdapter:
    """Return the adapter instance for a given Ollama model name."""
    for pat, cls in _FAMILY_PATTERNS:
        if pat.search(model_name):
            return cls()
    return DefaultAdapter()
```

- [ ] **Step 7.4: Run tests to verify they pass**

Run: `pytest tests/unit/test_model_adapters.py -v`
Expected: 4 passed.

- [ ] **Step 7.5: Commit**

```bash
git add api/services/model_adapters.py tests/unit/test_model_adapters.py
git commit -m "feat(workflow): add ModelAdapter base, DefaultAdapter, and registry"
```

---

## Task 8: Six Family Adapters (Dolphin, Llama3, Mistral, Qwen, Yi, UncensoredCommon)

**Files:**
- Modify: `api/services/model_adapters.py` (add 6 adapter classes + registry entries)
- Modify: `tests/unit/test_model_adapters.py` (add per-family tests)

- [ ] **Step 8.1: Write failing tests for each family adapter**

Append to `tests/unit/test_model_adapters.py`:
```python
def test_dolphin_adapter_prepends_no_nonsense_prefix():
    adapter = resolve_adapter("dolphin-mixtral:latest")
    prompt, _ = adapter.prepare(_mk_prompt(), {})
    assert prompt.system.startswith("You are a no-nonsense assistant")
    assert "sys" in prompt.system  # original still there


def test_dolphin_refusal_signatures_include_common_patterns():
    sigs = resolve_adapter("dolphin-mistral:7b").refusal_signatures()
    assert any("cannot" in s.lower() for s in sigs)


def test_llama3_adapter_sets_format_json():
    adapter = resolve_adapter("llama3:8b")
    _, params = adapter.prepare(_mk_prompt(), {})
    assert params.get("format") == "json"


def test_mistral_adapter_appends_json_only_reminder():
    adapter = resolve_adapter("mistral:latest")
    prompt, params = adapter.prepare(_mk_prompt(), {})
    assert "valid JSON only" in prompt.system.lower() or "json only" in prompt.system.lower()
    assert params.get("format") == "json"


def test_qwen_adapter_clamps_temperature_to_minimum():
    adapter = resolve_adapter("qwen2.5:7b")
    _, params = adapter.prepare(_mk_prompt(), {"temperature": 0.1})
    assert params["temperature"] >= 0.2


def test_qwen_adapter_keeps_higher_temperature():
    adapter = resolve_adapter("qwen2.5:7b")
    _, params = adapter.prepare(_mk_prompt(), {"temperature": 0.7})
    assert params["temperature"] == 0.7


def test_yi_adapter_appends_think_carefully():
    adapter = resolve_adapter("yi-34b:chat")
    prompt, _ = adapter.prepare(_mk_prompt(), {})
    assert "think carefully" in prompt.system.lower()


def test_uncensored_common_extends_num_predict():
    adapter = resolve_adapter("wizardlm-uncensored:13b")
    _, params = adapter.prepare(_mk_prompt(), {"num_predict": 1024})
    assert params["num_predict"] > 1024


def test_mythomax_routed_to_uncensored_common():
    adapter = resolve_adapter("mythomax:13b")
    assert type(adapter).__name__ == "UncensoredCommonAdapter"


def test_nous_hermes_routed_to_uncensored_common():
    adapter = resolve_adapter("nous-hermes2-mixtral")
    assert type(adapter).__name__ == "UncensoredCommonAdapter"
```

- [ ] **Step 8.2: Run tests to verify failure**

Run: `pytest tests/unit/test_model_adapters.py -v`
Expected: 10 new failures.

- [ ] **Step 8.3: Append family adapters to `api/services/model_adapters.py`**

```python
# ── Family adapters ─────────────────────────────────────────────────────────


class DolphinAdapter(ModelAdapter):
    family = "dolphin"
    _PREFIX = "You are a no-nonsense assistant. Answer directly, without preamble or hedging.\n\n"

    def prepare(self, prompt, params):
        new_prompt = ComposedPrompt(
            system=self._PREFIX + prompt.system,
            user=prompt.user,
            params=prompt.params,
        )
        return new_prompt, dict(params)

    def refusal_signatures(self):
        return ["I cannot", "I can't", "I'm sorry, but", "As an AI"]


class Llama3Adapter(ModelAdapter):
    family = "llama3"

    def prepare(self, prompt, params):
        new_params = dict(params)
        new_params["format"] = "json"
        return prompt, new_params

    def refusal_signatures(self):
        return ["I cannot", "I'm unable"]


class MistralAdapter(ModelAdapter):
    family = "mistral"
    _SUFFIX = "\n\nImportant: Respond in valid JSON only. No prose, no markdown fences."

    def prepare(self, prompt, params):
        new_prompt = ComposedPrompt(
            system=prompt.system + self._SUFFIX,
            user=prompt.user,
            params=prompt.params,
        )
        new_params = dict(params)
        new_params["format"] = "json"
        return new_prompt, new_params

    def refusal_signatures(self):
        return ["I cannot", "I'm not able"]


class QwenAdapter(ModelAdapter):
    family = "qwen"
    _TEMP_FLOOR = 0.2

    def prepare(self, prompt, params):
        new_params = dict(params)
        if "temperature" in new_params and new_params["temperature"] < self._TEMP_FLOOR:
            new_params["temperature"] = self._TEMP_FLOOR
        new_params["format"] = "json"
        return prompt, new_params

    def refusal_signatures(self):
        return ["抱歉", "I cannot", "I'm sorry"]


class YiAdapter(ModelAdapter):
    family = "yi"
    _SUFFIX = "\n\nThink carefully step-by-step, then respond."

    def prepare(self, prompt, params):
        new_prompt = ComposedPrompt(
            system=prompt.system + self._SUFFIX,
            user=prompt.user,
            params=prompt.params,
        )
        return new_prompt, dict(params)

    def refusal_signatures(self):
        return ["I cannot", "I'm unable"]


class UncensoredCommonAdapter(ModelAdapter):
    family = "uncensored_common"
    _EXTRA_TOKENS = 1024  # these models tend to truncate

    def prepare(self, prompt, params):
        new_params = dict(params)
        current = new_params.get("num_predict", 2048)
        new_params["num_predict"] = current + self._EXTRA_TOKENS
        return prompt, new_params

    def refusal_signatures(self):
        # Uncensored models rarely refuse; keep signatures minimal
        return []


# ── Register in priority order (first match wins) ──────────────────────────

_register(r"dolphin", DolphinAdapter)
_register(r"wizardlm|mythomax|nous-hermes", UncensoredCommonAdapter)
_register(r"llama[-_\s]?3|llama3", Llama3Adapter)
_register(r"mistral|mixtral", MistralAdapter)
_register(r"qwen", QwenAdapter)
_register(r"^yi-|:yi-|/yi-|\byi-", YiAdapter)
```

- [ ] **Step 8.4: Run tests to verify they pass**

Run: `pytest tests/unit/test_model_adapters.py -v`
Expected: 14 passed.

- [ ] **Step 8.5: Commit**

```bash
git add api/services/model_adapters.py tests/unit/test_model_adapters.py
git commit -m "feat(workflow): add six model-family adapters (dolphin/llama3/mistral/qwen/yi/uncensored)"
```

---

## Task 9: Built-in Hook — `json_schema`

**Files:**
- Create: `api/hooks/builtins/json_schema.py`
- Test: `tests/hooks/test_json_schema_hook.py`

- [ ] **Step 9.1: Ensure `tests/hooks/__init__.py` exists**

```bash
mkdir -p tests/hooks tests/integration tests/unit
touch tests/hooks/__init__.py tests/integration/__init__.py tests/unit/__init__.py
```

- [ ] **Step 9.2: Write failing test for `json_schema` hook**

`tests/hooks/test_json_schema_hook.py`:
```python
import json
import pytest
from api.services.hook_bus import HookContext
from api.hooks.builtins.json_schema import JsonSchemaHook


SCHEMA = {
    "type": "object",
    "required": ["name", "age"],
    "properties": {
        "name": {"type": "string"},
        "age": {"type": "integer"},
    },
}


def test_accepts_valid_json():
    hook = JsonSchemaHook(schema=SCHEMA)
    ctx = HookContext(output=json.dumps({"name": "x", "age": 9}))
    result = hook(ctx)
    assert result.action == "continue"
    assert ctx.parsed == {"name": "x", "age": 9}


def test_rejects_missing_required_key():
    hook = JsonSchemaHook(schema=SCHEMA)
    ctx = HookContext(output=json.dumps({"name": "x"}))
    result = hook(ctx)
    assert result.action == "fail"
    assert "age" in (result.feedback or "")


def test_rejects_wrong_type():
    hook = JsonSchemaHook(schema=SCHEMA)
    ctx = HookContext(output=json.dumps({"name": "x", "age": "nine"}))
    result = hook(ctx)
    assert result.action == "fail"


def test_rejects_malformed_json():
    hook = JsonSchemaHook(schema=SCHEMA)
    ctx = HookContext(output="{ not valid json")
    result = hook(ctx)
    assert result.action == "fail"
    assert "parse" in (result.feedback or "").lower() or "json" in (result.feedback or "").lower()


def test_strips_markdown_fences_when_configured():
    hook = JsonSchemaHook(schema=SCHEMA, strip_fences=True)
    wrapped = "```json\n" + json.dumps({"name": "x", "age": 9}) + "\n```"
    ctx = HookContext(output=wrapped)
    result = hook(ctx)
    assert result.action == "continue"
    assert ctx.parsed == {"name": "x", "age": 9}


def test_strips_leading_prose_when_configured():
    hook = JsonSchemaHook(schema=SCHEMA, strip_fences=True)
    prefixed = 'Sure, here is your JSON:\n{"name": "x", "age": 9}\n'
    ctx = HookContext(output=prefixed)
    result = hook(ctx)
    assert result.action == "continue"
    assert ctx.parsed == {"name": "x", "age": 9}


def test_strict_mode_rejects_wrapped_fences():
    hook = JsonSchemaHook(schema=SCHEMA, strip_fences=False, strict=True)
    wrapped = "```json\n" + json.dumps({"name": "x", "age": 9}) + "\n```"
    ctx = HookContext(output=wrapped)
    result = hook(ctx)
    assert result.action == "fail"


def test_hook_has_name_and_stage():
    hook = JsonSchemaHook(schema=SCHEMA)
    assert hook.name == "json_schema"
    assert hook.stage == "validate_output"
```

- [ ] **Step 9.3: Run tests to verify failure**

Run: `pytest tests/hooks/test_json_schema_hook.py -v`
Expected: 8 failures — module not found.

- [ ] **Step 9.4: Create `api/hooks/builtins/json_schema.py`**

```python
"""
json_schema hook — validates raw model output against a JSON schema.

Stage: validate_output. On success, sets ctx.parsed. On failure, returns
action='fail' with a concise feedback message suitable for retry prompting.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JSONSchemaError

from api.services.hook_bus import HookContext, HookResult


@dataclass
class JsonSchemaHook:
    schema: dict
    strict: bool = False
    strip_fences: bool = True

    name: str = "json_schema"
    stage: str = "validate_output"

    def __call__(self, ctx: HookContext) -> HookResult:
        raw = ctx.output or ""
        if not self.strict:
            candidate = self._extract_json_blob(raw)
        else:
            candidate = raw.strip()

        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError as e:
            return HookResult(
                action="fail",
                feedback=f"Your response could not be parsed as JSON: {e.msg}. Return a single JSON object only.",
            )

        try:
            Draft202012Validator(self.schema).validate(parsed)
        except JSONSchemaError as e:
            # Produce a terse path + message so the retry prompt stays short
            path = ".".join(str(p) for p in e.absolute_path) or "(root)"
            return HookResult(
                action="fail",
                feedback=f"Your response failed JSON schema validation at '{path}': {e.message}",
            )

        ctx.parsed = parsed
        return HookResult(action="continue")

    @staticmethod
    def _extract_json_blob(raw: str) -> str:
        """Pull JSON out of markdown fences or leading prose."""
        # 1) ```json ... ``` block
        m = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", raw, re.DOTALL)
        if m:
            return m.group(1)
        # 2) first balanced {...} or [...] in the string
        for opener, closer in (("{", "}"), ("[", "]")):
            start = raw.find(opener)
            if start == -1:
                continue
            depth = 0
            for i in range(start, len(raw)):
                ch = raw[i]
                if ch == opener:
                    depth += 1
                elif ch == closer:
                    depth -= 1
                    if depth == 0:
                        return raw[start:i+1]
        return raw.strip()
```

- [ ] **Step 9.5: Run tests to verify they pass**

Run: `pytest tests/hooks/test_json_schema_hook.py -v`
Expected: 8 passed.

- [ ] **Step 9.6: Commit**

```bash
git add api/hooks/builtins/json_schema.py tests/hooks/
git commit -m "feat(workflow): add json_schema validate_output hook"
```

---

## Task 10: Built-in Hook — `refusal_detector`

**Files:**
- Create: `api/hooks/builtins/refusal_detector.py`
- Test: `tests/hooks/test_refusal_detector_hook.py`

- [ ] **Step 10.1: Write failing tests**

`tests/hooks/test_refusal_detector_hook.py`:
```python
import pytest
from api.services.hook_bus import HookContext
from api.hooks.builtins.refusal_detector import RefusalDetectorHook


class FakeStep:
    def __init__(self, model_name):
        self.model_name = model_name


def test_detects_explicit_refusal():
    hook = RefusalDetectorHook(patterns=["I cannot", "As an AI"])
    ctx = HookContext(output="I cannot help with that request.")
    result = hook(ctx)
    assert result.action == "fail"
    assert "refused" in (result.feedback or "").lower()


def test_passes_non_refusal_content():
    hook = RefusalDetectorHook(patterns=["I cannot"])
    ctx = HookContext(output='{"answer": 42}')
    assert hook(ctx).action == "continue"


def test_case_insensitive_matching():
    hook = RefusalDetectorHook(patterns=["i cannot"])
    ctx = HookContext(output="I CANNOT do that")
    assert hook(ctx).action == "fail"


def test_empty_patterns_always_passes():
    hook = RefusalDetectorHook(patterns=[])
    ctx = HookContext(output="I cannot anything")
    assert hook(ctx).action == "continue"


def test_uses_family_defaults_when_flag_set(monkeypatch):
    from api.hooks.builtins import refusal_detector as mod

    class FakeAdapter:
        def refusal_signatures(self):
            return ["ZZZ-family-refusal"]

    def fake_resolve(name):
        return FakeAdapter()

    monkeypatch.setattr(mod, "resolve_adapter", fake_resolve)

    hook = RefusalDetectorHook(patterns=[], use_family_defaults=True)
    ctx = HookContext(
        output="ZZZ-family-refusal. No can do.",
        step=FakeStep("some-model"),
    )
    ctx.workflow = None
    assert hook(ctx).action == "fail"


def test_name_and_stage():
    hook = RefusalDetectorHook(patterns=[])
    assert hook.name == "refusal_detector"
    assert hook.stage == "validate_output"
```

- [ ] **Step 10.2: Run tests to verify failure**

Run: `pytest tests/hooks/test_refusal_detector_hook.py -v`
Expected: 6 failures — module not found.

- [ ] **Step 10.3: Create `api/hooks/builtins/refusal_detector.py`**

```python
"""
refusal_detector hook — flags model refusals so they can be re-prompted.

Stage: validate_output. This hook does NOT suppress content. It only detects
that the model declined to answer so on_failure can retry with reframing.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from api.services.hook_bus import HookContext, HookResult
from api.services.model_adapters import resolve_adapter


@dataclass
class RefusalDetectorHook:
    patterns: list[str] = field(default_factory=list)
    use_family_defaults: bool = False

    name: str = "refusal_detector"
    stage: str = "validate_output"

    def __call__(self, ctx: HookContext) -> HookResult:
        output = (ctx.output or "").lower()
        if not output:
            return HookResult(action="continue")

        all_patterns = list(self.patterns)
        if self.use_family_defaults and ctx.step is not None:
            model = getattr(ctx.step, "model_name", None) or getattr(ctx.step, "model", None)
            if model:
                all_patterns.extend(resolve_adapter(model).refusal_signatures())

        for pat in all_patterns:
            if pat and pat.lower() in output:
                return HookResult(
                    action="fail",
                    feedback="Model refused or declined the task. Reframe the request as a technical analysis and respond with the required JSON.",
                )
        return HookResult(action="continue")
```

- [ ] **Step 10.4: Run tests to verify they pass**

Run: `pytest tests/hooks/test_refusal_detector_hook.py -v`
Expected: 6 passed.

- [ ] **Step 10.5: Commit**

```bash
git add api/hooks/builtins/refusal_detector.py tests/hooks/test_refusal_detector_hook.py
git commit -m "feat(workflow): add refusal_detector validate_output hook"
```

---

## Task 11: Built-in Hook — `token_budget`

**Files:**
- Create: `api/hooks/builtins/token_budget.py`
- Test: `tests/hooks/test_token_budget_hook.py`

- [ ] **Step 11.1: Write failing tests**

`tests/hooks/test_token_budget_hook.py`:
```python
import pytest
from api.services.hook_bus import HookContext
from api.services.prompt_composer import ComposedPrompt
from api.hooks.builtins.token_budget import TokenBudgetHook


def test_passes_when_under_budget():
    hook = TokenBudgetHook(max_prompt_tokens=1000, reserve_for_output=500)
    prompt = ComposedPrompt(system="short", user="short", params={})
    ctx = HookContext(prompt=prompt)
    result = hook(ctx)
    assert result.action == "continue"
    assert ctx.prompt.system == "short"


def test_truncates_context_when_over_budget():
    hook = TokenBudgetHook(max_prompt_tokens=100, reserve_for_output=20)
    # Simulate a system prompt with a big Context block
    system = (
        "ROLE_TEXT\n\n## Context\n"
        + ("filler words " * 200)
        + "\n\n## Task\nDO THE TASK\n\n## Constraints\n- be terse"
    )
    prompt = ComposedPrompt(system=system, user="usr", params={})
    ctx = HookContext(prompt=prompt)
    result = hook(ctx)
    assert result.action == "continue"
    # Context block was shortened; task + constraints preserved
    assert "## Task" in ctx.prompt.system
    assert "DO THE TASK" in ctx.prompt.system
    assert "## Constraints" in ctx.prompt.system
    assert "be terse" in ctx.prompt.system
    # Total length reduced
    assert len(ctx.prompt.system) < len(system)


def test_never_truncates_task_or_constraints():
    hook = TokenBudgetHook(max_prompt_tokens=50, reserve_for_output=10)
    system = (
        "ROLE\n\n## Context\nsmall\n\n## Task\n"
        + ("do " * 100)
        + "\n\n## Constraints\n- rule one"
    )
    prompt = ComposedPrompt(system=system, user="usr", params={})
    ctx = HookContext(prompt=prompt)
    hook(ctx)
    # Task content preserved verbatim
    assert ("do " * 100) in ctx.prompt.system or "do do do" in ctx.prompt.system
    assert "- rule one" in ctx.prompt.system


def test_name_and_stage():
    hook = TokenBudgetHook()
    assert hook.name == "token_budget"
    assert hook.stage == "before_step"


def test_handles_missing_prompt_gracefully():
    hook = TokenBudgetHook(max_prompt_tokens=100, reserve_for_output=20)
    ctx = HookContext(prompt=None)
    result = hook(ctx)
    assert result.action == "continue"
```

- [ ] **Step 11.2: Run tests to verify failure**

Run: `pytest tests/hooks/test_token_budget_hook.py -v`
Expected: 5 failures — module not found.

- [ ] **Step 11.3: Create `api/hooks/builtins/token_budget.py`**

```python
"""
token_budget hook — estimates prompt tokens and truncates the Context section
when the prompt would exceed the configured budget.

Never truncates Task or Constraints — those are load-bearing.
Stage: before_step.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from api.services.hook_bus import HookContext, HookResult


def _estimate_tokens(text: str) -> int:
    """Cheap token estimate. Tries tiktoken, falls back to chars/4."""
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:
        # Rule-of-thumb: ~4 chars per token for English.
        return max(1, len(text) // 4)


@dataclass
class TokenBudgetHook:
    max_prompt_tokens: int = 3500
    reserve_for_output: int = 1024

    name: str = "token_budget"
    stage: str = "before_step"

    def __call__(self, ctx: HookContext) -> HookResult:
        if ctx.prompt is None:
            return HookResult(action="continue")

        budget = max(1, self.max_prompt_tokens - self.reserve_for_output)
        system = ctx.prompt.system or ""
        user = ctx.prompt.user or ""
        total = _estimate_tokens(system) + _estimate_tokens(user)

        if total <= budget:
            return HookResult(action="continue")

        # Truncate the Context block in system, keeping Task + Constraints intact
        new_system = self._truncate_context_block(system, budget - _estimate_tokens(user))
        ctx.prompt.system = new_system
        return HookResult(action="continue")

    @staticmethod
    def _truncate_context_block(system: str, allowed_tokens: int) -> str:
        """Shrink the '## Context' section to fit. Task/Constraints/OutputFormat untouched."""
        # Identify section boundaries
        context_match = re.search(r"(## Context\s*\n)(.*?)(?=\n## (?:Task|Constraints|Output Format)\b|$)", system, re.DOTALL)
        if not context_match:
            return system  # nothing to truncate
        before = system[: context_match.start(2)]
        after = system[context_match.end(2):]
        ctx_body = context_match.group(2)

        # Estimate remaining budget for context after subtracting fixed parts
        fixed_tokens = _estimate_tokens(before) + _estimate_tokens(after)
        remaining = max(100, allowed_tokens - fixed_tokens)
        # Character-based trim using chars-per-token heuristic
        chars_per_token = max(1, len(ctx_body) // max(1, _estimate_tokens(ctx_body)))
        max_chars = remaining * chars_per_token
        if len(ctx_body) > max_chars:
            ctx_body = ctx_body[:max_chars] + "\n…[truncated for token budget]…\n"
        return before + ctx_body + after
```

- [ ] **Step 11.4: Run tests to verify they pass**

Run: `pytest tests/hooks/test_token_budget_hook.py -v`
Expected: 5 passed.

- [ ] **Step 11.5: Commit**

```bash
git add api/hooks/builtins/token_budget.py tests/hooks/test_token_budget_hook.py
git commit -m "feat(workflow): add token_budget before_step hook"
```

---

## Task 12: Built-in Hook — `output_logger`

**Files:**
- Create: `api/hooks/builtins/output_logger.py`
- Test: `tests/hooks/test_output_logger_hook.py`

- [ ] **Step 12.1: Write failing tests**

`tests/hooks/test_output_logger_hook.py`:
```python
import json
import pytest
from api.services.hook_bus import HookContext
from api.services.prompt_composer import ComposedPrompt
from api.hooks.builtins.output_logger import OutputLoggerHook


class FakeStep:
    def __init__(self, sid):
        self.id = sid

class FakeWorkflow:
    def __init__(self, rid):
        self.run_id = rid


def test_logger_writes_jsonl_entry(tmp_path):
    logfile = tmp_path / "runs.jsonl"
    hook = OutputLoggerHook(log_path=logfile, include_prompt=False)
    ctx = HookContext(
        workflow=FakeWorkflow("run-1"),
        step=FakeStep("analyze"),
        output='{"ok": true}',
        parsed={"ok": True},
    )
    result = hook(ctx)
    assert result.action == "continue"
    lines = logfile.read_text().strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["run_id"] == "run-1"
    assert record["step_id"] == "analyze"
    assert record["raw_output"] == '{"ok": true}'
    assert record["parsed"] == {"ok": True}


def test_logger_includes_prompt_when_configured(tmp_path):
    logfile = tmp_path / "runs.jsonl"
    hook = OutputLoggerHook(log_path=logfile, include_prompt=True)
    ctx = HookContext(
        workflow=FakeWorkflow("r"),
        step=FakeStep("s"),
        prompt=ComposedPrompt(system="sys", user="usr", params={}),
        output="x",
    )
    hook(ctx)
    record = json.loads(logfile.read_text().strip())
    assert record["prompt"]["system"] == "sys"
    assert record["prompt"]["user"] == "usr"


def test_logger_excludes_prompt_by_default(tmp_path):
    logfile = tmp_path / "runs.jsonl"
    hook = OutputLoggerHook(log_path=logfile)
    ctx = HookContext(
        workflow=FakeWorkflow("r"),
        step=FakeStep("s"),
        prompt=ComposedPrompt(system="sys", user="usr", params={}),
        output="x",
    )
    hook(ctx)
    record = json.loads(logfile.read_text().strip())
    assert "prompt" not in record


def test_logger_appends_multiple_entries(tmp_path):
    logfile = tmp_path / "runs.jsonl"
    hook = OutputLoggerHook(log_path=logfile)
    for i in range(3):
        ctx = HookContext(
            workflow=FakeWorkflow(f"r{i}"),
            step=FakeStep("s"),
            output=f"out-{i}",
        )
        hook(ctx)
    assert len(logfile.read_text().strip().splitlines()) == 3


def test_logger_name_and_stage():
    hook = OutputLoggerHook(log_path="/tmp/x.jsonl")
    assert hook.name == "output_logger"
    assert hook.stage == "after_step"
```

- [ ] **Step 12.2: Run tests to verify failure**

Run: `pytest tests/hooks/test_output_logger_hook.py -v`
Expected: 5 failures.

- [ ] **Step 12.3: Create `api/hooks/builtins/output_logger.py`**

```python
"""
output_logger hook — appends per-step execution records to a JSONL file.

Stage: after_step.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from api.services.hook_bus import HookContext, HookResult


@dataclass
class OutputLoggerHook:
    log_path: str | Path = "data/logs/workflow_runs.jsonl"
    include_prompt: bool = False

    name: str = "output_logger"
    stage: str = "after_step"

    def __call__(self, ctx: HookContext) -> HookResult:
        path = Path(self.log_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        record: dict = {
            "ts": datetime.utcnow().isoformat(),
            "run_id": getattr(ctx.workflow, "run_id", None),
            "step_id": getattr(ctx.step, "id", None),
            "attempt": ctx.attempt,
            "raw_output": ctx.output,
            "parsed": ctx.parsed,
        }
        if self.include_prompt and ctx.prompt is not None:
            record["prompt"] = {
                "system": ctx.prompt.system,
                "user": ctx.prompt.user,
                "params": ctx.prompt.params,
            }

        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")
        return HookResult(action="continue")
```

- [ ] **Step 12.4: Run tests to verify they pass**

Run: `pytest tests/hooks/test_output_logger_hook.py -v`
Expected: 5 passed.

- [ ] **Step 12.5: Commit**

```bash
git add api/hooks/builtins/output_logger.py tests/hooks/test_output_logger_hook.py
git commit -m "feat(workflow): add output_logger after_step hook"
```

---

## Task 13: Built-in Hook — `few_shot_injector`

**Files:**
- Create: `api/hooks/builtins/few_shot_injector.py`
- Test: `tests/hooks/test_few_shot_injector_hook.py`

- [ ] **Step 13.1: Write failing tests**

`tests/hooks/test_few_shot_injector_hook.py`:
```python
import json
import pytest
from api.services.hook_bus import HookContext
from api.services.prompt_composer import ComposedPrompt
from api.hooks.builtins.few_shot_injector import FewShotInjectorHook


class FakeStep:
    def __init__(self, sid):
        self.id = sid


def _prompt_with_output_format():
    system = "ROLE\n\n## Context\nc\n\n## Task\nt\n\n## Constraints\n- x\n\n## Output Format\n{}\n"
    return ComposedPrompt(system=system, user="u", params={})


def test_injects_example_from_directory(tmp_path):
    ex_dir = tmp_path / "analyze"
    ex_dir.mkdir()
    (ex_dir / "01.json").write_text(json.dumps({
        "input": "sample input",
        "output": {"result": "ok"},
    }))
    hook = FewShotInjectorHook(example_dir=tmp_path, max_examples=1)
    ctx = HookContext(step=FakeStep("analyze"), prompt=_prompt_with_output_format())
    result = hook(ctx)
    assert result.action == "continue"
    assert "## Example" in ctx.prompt.system
    assert "sample input" in ctx.prompt.system
    assert '"result": "ok"' in ctx.prompt.system


def test_skip_when_no_examples(tmp_path):
    hook = FewShotInjectorHook(example_dir=tmp_path, max_examples=1)
    ctx = HookContext(step=FakeStep("unknown"), prompt=_prompt_with_output_format())
    original = ctx.prompt.system
    result = hook(ctx)
    assert result.action == "continue"
    assert ctx.prompt.system == original


def test_respects_max_examples(tmp_path):
    ex_dir = tmp_path / "sid"
    ex_dir.mkdir()
    for i in range(5):
        (ex_dir / f"{i:02}.json").write_text(json.dumps({"input": f"in{i}", "output": {"n": i}}))
    hook = FewShotInjectorHook(example_dir=tmp_path, max_examples=2)
    ctx = HookContext(step=FakeStep("sid"), prompt=_prompt_with_output_format())
    hook(ctx)
    system = ctx.prompt.system
    assert system.count("## Example") == 2


def test_name_and_stage():
    hook = FewShotInjectorHook(example_dir="/tmp", max_examples=1)
    assert hook.name == "few_shot_injector"
    assert hook.stage == "transform_prompt"
```

- [ ] **Step 13.2: Run tests to verify failure**

Run: `pytest tests/hooks/test_few_shot_injector_hook.py -v`
Expected: 4 failures.

- [ ] **Step 13.3: Create `api/hooks/builtins/few_shot_injector.py`**

```python
"""
few_shot_injector hook — appends example input/output pairs to the prompt.

Stage: transform_prompt. Opt-in per step via YAML `hooks.transform_prompt`.
Examples live in `{example_dir}/{step_id}/*.json` with shape:
  {"input": "...", "output": {...}}
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from api.services.hook_bus import HookContext, HookResult


@dataclass
class FewShotInjectorHook:
    example_dir: str | Path
    max_examples: int = 1

    name: str = "few_shot_injector"
    stage: str = "transform_prompt"

    def __call__(self, ctx: HookContext) -> HookResult:
        if ctx.prompt is None or ctx.step is None:
            return HookResult(action="continue")

        step_id = getattr(ctx.step, "id", None)
        if not step_id:
            return HookResult(action="continue")

        base = Path(self.example_dir) / step_id
        if not base.is_dir():
            return HookResult(action="continue")

        examples = sorted(base.glob("*.json"))[: self.max_examples]
        if not examples:
            return HookResult(action="continue")

        blocks = []
        for ex_path in examples:
            try:
                ex = json.loads(ex_path.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            blocks.append(
                "## Example\n"
                f"Input: {ex.get('input', '')}\n"
                f"Output: {json.dumps(ex.get('output', {}), indent=2)}"
            )

        if not blocks:
            return HookResult(action="continue")

        ctx.prompt.system = ctx.prompt.system.rstrip() + "\n\n" + "\n\n".join(blocks) + "\n"
        return HookResult(action="continue")
```

- [ ] **Step 13.4: Run tests to verify they pass**

Run: `pytest tests/hooks/test_few_shot_injector_hook.py -v`
Expected: 4 passed.

- [ ] **Step 13.5: Commit**

```bash
git add api/hooks/builtins/few_shot_injector.py tests/hooks/test_few_shot_injector_hook.py
git commit -m "feat(workflow): add few_shot_injector transform_prompt hook"
```

---

## Task 14: Built-in Hook — `retry_with_feedback`

**Files:**
- Create: `api/hooks/builtins/retry_with_feedback.py`
- Test: `tests/hooks/test_retry_with_feedback_hook.py`

- [ ] **Step 14.1: Write failing tests**

`tests/hooks/test_retry_with_feedback_hook.py`:
```python
import pytest
from api.services.hook_bus import HookContext
from api.services.prompt_composer import ComposedPrompt
from api.hooks.builtins.retry_with_feedback import RetryWithFeedbackHook


def _base_ctx(attempt=0, feedback="missing key 'foo'"):
    from api.hooks.builtins.retry_with_feedback import ValidationFailure
    prompt = ComposedPrompt(system="SYS", user="USR", params={})
    return HookContext(
        prompt=prompt,
        output='{"x": 1}',
        error=ValidationFailure(feedback=feedback),
        attempt=attempt,
    )


def test_first_failure_returns_retry_with_feedback_appended():
    hook = RetryWithFeedbackHook(max_attempts=2)
    ctx = _base_ctx(attempt=0)
    result = hook(ctx)
    assert result.action == "retry"
    assert "missing key 'foo'" in ctx.prompt.user
    assert "previous response" in ctx.prompt.user.lower() or "previous output" in ctx.prompt.user.lower()


def test_max_attempts_respected_returns_fail():
    hook = RetryWithFeedbackHook(max_attempts=2)
    ctx = _base_ctx(attempt=2)  # already at max
    result = hook(ctx)
    assert result.action == "fail"


def test_second_attempt_adds_example_when_enabled():
    hook = RetryWithFeedbackHook(max_attempts=2, include_example=True)
    ctx = _base_ctx(attempt=1)
    result = hook(ctx)
    assert result.action == "retry"
    assert "Example" in ctx.prompt.user or "example" in ctx.prompt.user


def test_no_example_when_disabled():
    hook = RetryWithFeedbackHook(max_attempts=2, include_example=False)
    ctx = _base_ctx(attempt=1)
    hook(ctx)
    # The injected user content should not contain a literal "Example:" header
    assert "## Example" not in ctx.prompt.user


def test_escalate_to_sets_mutation():
    hook = RetryWithFeedbackHook(max_attempts=2, escalate_to="reasoning")
    ctx = _base_ctx(attempt=1)
    result = hook(ctx)
    assert result.action == "retry"
    # escalate metadata is carried in mutations.shared or directly surfaced
    assert result.mutations.get("escalate_to") == "reasoning"


def test_name_and_stage():
    hook = RetryWithFeedbackHook()
    assert hook.name == "retry_with_feedback"
    assert hook.stage == "on_failure"
```

- [ ] **Step 14.2: Run tests to verify failure**

Run: `pytest tests/hooks/test_retry_with_feedback_hook.py -v`
Expected: 6 failures.

- [ ] **Step 14.3: Create `api/hooks/builtins/retry_with_feedback.py`**

```python
"""
retry_with_feedback hook — rewrites the user prompt with validation feedback
and (optionally) escalates to a larger model on subsequent attempts.

Stage: on_failure.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from api.services.hook_bus import HookContext, HookResult


@dataclass
class ValidationFailure:
    """Carrier used by validate_output hooks to communicate failure reasons."""
    feedback: str


@dataclass
class RetryWithFeedbackHook:
    max_attempts: int = 2
    include_example: bool = False
    escalate_to: str | None = None

    name: str = "retry_with_feedback"
    stage: str = "on_failure"

    def __call__(self, ctx: HookContext) -> HookResult:
        if ctx.attempt >= self.max_attempts:
            return HookResult(action="fail")

        feedback = ""
        if isinstance(ctx.error, ValidationFailure):
            feedback = ctx.error.feedback
        elif ctx.error:
            feedback = str(ctx.error)

        # Inject prior output + feedback into the user message
        prior = ctx.output or ""
        retry_block = (
            "\n\nYour previous response was rejected.\n"
            f"Previous output:\n{prior}\n\n"
            f"Validation error: {feedback}\n\n"
            "Return a new response that strictly satisfies the output schema. "
            "Do not include prose, markdown fences, or commentary."
        )

        if self.include_example and ctx.attempt >= 1:
            retry_block += (
                "\n\n## Example of a valid response shape\n"
                "{\n  \"<key_from_schema>\": <value>,\n  ...\n}\n"
            )

        if ctx.prompt is not None:
            ctx.prompt.user = (ctx.prompt.user or "") + retry_block

        mutations: dict = {}
        if self.escalate_to:
            mutations["escalate_to"] = self.escalate_to

        return HookResult(action="retry", mutations=mutations)
```

- [ ] **Step 14.4: Run tests to verify they pass**

Run: `pytest tests/hooks/test_retry_with_feedback_hook.py -v`
Expected: 6 passed.

- [ ] **Step 14.5: Commit**

```bash
git add api/hooks/builtins/retry_with_feedback.py tests/hooks/test_retry_with_feedback_hook.py
git commit -m "feat(workflow): add retry_with_feedback on_failure hook with optional escalation"
```

---

## Task 15: Extend `workflow_models.py` with v2 Schema Fields

**Files:**
- Modify: `api/models/workflow_models.py`
- Test: `tests/unit/test_workflow_models_v2.py` (new)

- [ ] **Step 15.1: Write failing tests for v2 model fields**

`tests/unit/test_workflow_models_v2.py`:
```python
import pytest
from api.models.workflow_models import (
    StepPrompt,
    HookSpec,
    AgentStep,
    WorkflowDefinition,
    WorkflowDefaults,
)


def test_step_prompt_requires_role_ref_or_inline():
    # valid with role_ref
    p = StepPrompt(role_ref="architect", task="t", constraints=["c"])
    assert p.role_ref == "architect"
    # valid with role_inline
    p = StepPrompt(role_inline="you are x", task="t", constraints=[])
    assert p.role_inline == "you are x"
    # invalid with neither
    with pytest.raises(ValueError, match="role_ref or role_inline"):
        StepPrompt(task="t", constraints=[])


def test_step_prompt_forbids_both_role_ref_and_inline():
    with pytest.raises(ValueError, match="only one of"):
        StepPrompt(role_ref="a", role_inline="b", task="t", constraints=[])


def test_hook_spec_parses_dict_form():
    spec = HookSpec(name="json_schema", config={"strip_fences": True})
    assert spec.name == "json_schema"
    assert spec.config["strip_fences"] is True


def test_agent_step_v2_with_prompt_block():
    step = AgentStep(
        id="analyze",
        name="Analyze",
        role="reasoning",
        prompt=StepPrompt(role_ref="architect", task="t", constraints=["no prose"]),
        inputs=["seed.files"],
        outputs=["entities"],
        output_schema={"type": "object", "required": ["entities"]},
    )
    assert step.prompt is not None
    assert step.output_schema["type"] == "object"


def test_agent_step_v1_still_works_with_system_prompt():
    step = AgentStep(
        id="analyze",
        name="Analyze",
        role="reasoning",
        system_prompt="You are X. Do Y.",
        inputs=["seed.files"],
        outputs=["entities"],
    )
    assert step.system_prompt == "You are X. Do Y."
    assert step.prompt is None


def test_agent_step_requires_either_prompt_or_system_prompt():
    with pytest.raises(ValueError, match="prompt or system_prompt"):
        AgentStep(
            id="x", name="x", role="reasoning",
            inputs=[], outputs=["y"],
        )


def test_workflow_definition_v2_fields():
    wf = WorkflowDefinition(
        id="w",
        name="W",
        schema_version=2,
        context={"project": "Enclave"},
        schemas={"ent": {"type": "object"}},
        steps=[AgentStep(
            id="s", name="S", role="coding",
            system_prompt="x",
            outputs=["y"],
        )],
    )
    assert wf.schema_version == 2
    assert wf.context["project"] == "Enclave"
    assert "ent" in wf.schemas


def test_workflow_definition_defaults_to_v1():
    wf = WorkflowDefinition(
        id="w", name="W",
        steps=[AgentStep(id="s", name="S", role="coding", system_prompt="x", outputs=["y"])],
    )
    assert wf.schema_version == 1
```

- [ ] **Step 15.2: Run tests to verify failure**

Run: `pytest tests/unit/test_workflow_models_v2.py -v`
Expected: 7 failures — most fields don't exist yet.

- [ ] **Step 15.3: Modify `api/models/workflow_models.py`**

Replace the contents of `api/models/workflow_models.py` with the following (keeps all v1 fields, adds v2 fields):

```python
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

    # v1 field
    system_prompt: Optional[str] = None
    # v2 field
    prompt: Optional[StepPrompt] = None

    inputs: List[str] = Field(default_factory=list)
    outputs: List[str] = Field(min_length=1)
    output_schema: Optional[Dict[str, Any]] = None
    hooks: StepHooks = Field(default_factory=StepHooks)
    config: StepConfig = Field(default_factory=StepConfig)

    @model_validator(mode="after")
    def _validate_prompt_shape(self):
        if not self.system_prompt and not self.prompt:
            raise ValueError("AgentStep requires `prompt` (v2) or `system_prompt` (v1)")
        if self.system_prompt and self.prompt:
            raise ValueError("AgentStep has both `prompt` and `system_prompt` — use one")
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
        default_factory=lambda: {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    )
    retries: int = 0
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


# ── Workflow Run (unchanged) ───────────────────────────────────────────────


class WorkflowRun(BaseModel):
    run_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    workflow_id: str
    status: str = "pending"
    context: WorkflowContext
    step_results: List[StepResult] = Field(default_factory=list)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
```

- [ ] **Step 15.4: Run tests to verify they pass**

Run: `pytest tests/unit/test_workflow_models_v2.py -v && pytest tests/ -v -k workflow`
Expected: 7 new tests pass; no regressions in existing workflow tests.

- [ ] **Step 15.5: Commit**

```bash
git add api/models/workflow_models.py tests/unit/test_workflow_models_v2.py
git commit -m "feat(workflow): extend models with v2 fields (StepPrompt, HookSpec, schema_version, context, schemas)"
```

---

## Task 16: StepExecutor Integration — Wire Composer, Adapter, Hook Bus

**Files:**
- Modify: `api/services/step_executor.py` (substantial rewrite)

This task rewrites the core execution path. It is deliberately larger.

- [ ] **Step 16.1: Replace `api/services/step_executor.py`**

```python
"""
Step Executor — Runs a single workflow step through the 6-hook lifecycle.

Pipeline:
  resolve inputs → compose prompt → adapt for family → [before_step hooks]
    → [transform_prompt hooks] → model call → [after_step hooks]
    → [validate_output hooks] → on success return; on failure → [on_failure hooks]
"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from ..logging_config import logger
from ..exceptions import GenerationError
from ..models.workflow_models import (
    AgentStep,
    StepResult,
    WorkflowContext,
    WorkflowDefaults,
    WorkflowDefinition,
)
from .hook_bus import HookBus, HookContext, HookResult
from .prompt_composer import PromptComposer, ComposedPrompt
from .model_adapters import resolve_adapter
from .ollama_service import OllamaService


class StepExecutor:
    def __init__(
        self,
        ollama_service: OllamaService,
        composer: PromptComposer,
        hook_bus: HookBus,
    ):
        self.ollama = ollama_service
        self.composer = composer
        self.hook_bus = hook_bus

    def execute(
        self,
        step: AgentStep,
        workflow: WorkflowDefinition,
        context: WorkflowContext,
        resolved_model: str,
        defaults: WorkflowDefaults,
        workflow_run=None,
    ) -> StepResult:
        result = StepResult(step_id=step.id, status="running", started_at=datetime.utcnow())
        result.model_used = resolved_model

        temperature = step.config.temperature or defaults.temperature
        max_tokens = step.config.max_tokens or defaults.max_tokens
        max_retries = step.config.retries if step.config.retries is not None else defaults.retries
        retry_delay = step.config.retry_delay if step.config.retry_delay is not None else defaults.retry_delay

        # --- Compose prompt ---------------------------------------------------
        resolved_inputs = {
            ref: context.resolve_input(ref) for ref in step.inputs
        }
        resolved_inputs = {k: v for k, v in resolved_inputs.items() if v is not None}

        composed = self._compose(step, workflow, resolved_inputs, {
            "temperature": temperature,
            "num_predict": max_tokens,
        })

        # --- Adapt for model family ------------------------------------------
        adapter = resolve_adapter(resolved_model)
        composed, params = adapter.prepare(composed, composed.params)
        composed.params = params

        # --- Retry loop with hook lifecycle ----------------------------------
        last_error: Any = None
        current_model = resolved_model

        for attempt in range(max_retries + 1):
            ctx = HookContext(
                workflow=workflow_run,
                step=step,
                prompt=composed,
                attempt=attempt,
            )

            # before_step
            if self._short_circuit(self.hook_bus.dispatch("before_step", ctx)):
                break

            # transform_prompt
            if self._short_circuit(self.hook_bus.dispatch("transform_prompt", ctx)):
                break

            # model call
            try:
                llm_result = self.ollama.chat(
                    model=current_model,
                    messages=ctx.prompt.as_messages(),
                    temperature=ctx.prompt.params.get("temperature", temperature),
                    max_tokens=ctx.prompt.params.get("num_predict", max_tokens),
                )
                ctx.output = llm_result.get("content", "")
            except Exception as e:
                ctx.output = ""
                ctx.error = e
                last_error = str(e)
                logger.warning(f"Step '{step.id}' attempt {attempt + 1} model call raised: {e}")

            # after_step
            self.hook_bus.dispatch("after_step", ctx)

            # validate_output
            validation_results = self.hook_bus.dispatch("validate_output", ctx)
            validation_failed = any(r.action != "continue" for r in validation_results)

            if not validation_failed and ctx.output:
                # Success — write outputs to workspace
                self._write_outputs(step, ctx, context)
                result.status = "completed"
                result.retries = attempt
                result.token_count = self._token_count(llm_result)
                result.completed_at = datetime.utcnow()
                result.duration_seconds = (
                    result.completed_at - result.started_at
                ).total_seconds()
                return result

            # on_failure
            # Attach the validation failure's feedback as ctx.error
            failure_feedback = next(
                (r.feedback for r in validation_results if r.feedback),
                last_error or "unknown validation failure",
            )
            from api.hooks.builtins.retry_with_feedback import ValidationFailure
            ctx.error = ValidationFailure(feedback=str(failure_feedback))

            failure_results = self.hook_bus.dispatch("on_failure", ctx)
            decision = failure_results[-1].action if failure_results else "fail"

            if decision == "retry" and attempt < max_retries:
                # Apply escalation mutation if present
                last_mutations = failure_results[-1].mutations if failure_results else {}
                escalate_to = last_mutations.get("escalate_to")
                if escalate_to:
                    # Caller (WorkflowEngine) owns model_resolver; we defer by setting role hint
                    context.set_shared(f"_escalated_{step.id}", escalate_to)
                if retry_delay > 0:
                    time.sleep(retry_delay)
                last_error = failure_feedback
                continue
            else:
                last_error = failure_feedback
                break

        # Failure path
        result.status = "failed"
        result.error = str(last_error)
        result.retries = max_retries
        result.completed_at = datetime.utcnow()
        result.duration_seconds = (result.completed_at - result.started_at).total_seconds()
        logger.error(f"Step '{step.id}' failed after {max_retries + 1} attempts: {last_error}")
        return result

    # ── helpers ────────────────────────────────────────────────────────────

    def _compose(
        self,
        step: AgentStep,
        workflow: WorkflowDefinition,
        resolved_inputs: dict,
        default_params: dict,
    ) -> ComposedPrompt:
        workflow_context_str = self._render_context(workflow.context)
        # v2 path
        if step.prompt is not None:
            output_schema = step.output_schema or {}
            return self.composer.compose(
                role_ref=step.prompt.role_ref,
                role_inline=step.prompt.role_inline,
                context=workflow_context_str,
                task=step.prompt.task,
                constraints=step.prompt.constraints,
                output_schema=output_schema,
                resolved_inputs=resolved_inputs,
                params=dict(default_params),
            )
        # v1 path — wrap legacy system_prompt
        return self.composer.compose(
            role_ref=None,
            role_inline=step.system_prompt,
            context=workflow_context_str,
            task="(See role description above.)",
            constraints=[],
            output_schema={"type": "object", "properties": {k: {} for k in step.outputs}},
            resolved_inputs=resolved_inputs,
            params=dict(default_params),
        )

    @staticmethod
    def _render_context(context: dict) -> str:
        if not context:
            return "(no workflow context provided)"
        return "\n".join(f"- {k}: {v}" for k, v in context.items())

    @staticmethod
    def _short_circuit(results: list[HookResult]) -> bool:
        return any(r.action == "fail" for r in results)

    @staticmethod
    def _token_count(llm_result) -> dict:
        prompt_tokens = llm_result.get("prompt_eval_count", 0) if llm_result else 0
        completion_tokens = llm_result.get("eval_count", 0) if llm_result else 0
        return {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        }

    def _write_outputs(self, step: AgentStep, ctx: HookContext, context: WorkflowContext):
        # Prefer parsed (from json_schema hook) over raw text
        parsed = ctx.parsed
        if isinstance(parsed, dict):
            for key in step.outputs:
                if key in parsed:
                    context.set_workspace(step.id, key, parsed[key])
                else:
                    # Key missing from parsed dict — store raw for visibility
                    context.set_workspace(step.id, key, ctx.output)
        elif len(step.outputs) == 1:
            context.set_workspace(step.id, step.outputs[0], ctx.output)
        else:
            for key in step.outputs:
                context.set_workspace(step.id, key, ctx.output)
```

- [ ] **Step 16.2: Run the existing tests to detect regressions**

Run: `pytest tests/ -v --tb=short 2>&1 | head -80`
Expected: Some workflow_engine tests may fail because they construct `StepExecutor` with only `OllamaService`. Those failures are expected and addressed in Task 17.

- [ ] **Step 16.3: Commit (tests will go green after Task 17)**

```bash
git add api/services/step_executor.py
git commit -m "refactor(workflow): rewrite StepExecutor around 6-hook lifecycle"
```

---

## Task 17: WorkflowEngine Integration — Instantiate Hook Bus + Composer

**Files:**
- Modify: `api/services/workflow_engine.py`
- Modify: `tests/` — fix any construction sites

- [ ] **Step 17.1: Locate `StepExecutor` construction site in `workflow_engine.py`**

Run: `grep -n "StepExecutor(" api/services/workflow_engine.py`

Expected lines shown; typically a single call that passes only `OllamaService`.

- [ ] **Step 17.2: Modify `WorkflowEngine.__init__` to build the new dependencies**

Find the `WorkflowEngine.__init__` method and update it. Near the imports of `workflow_engine.py`, add:

```python
from pathlib import Path
from .hook_bus import HookBus
from .prompt_composer import PromptComposer
```

In `__init__`, construct the dependencies:

```python
def __init__(self, ollama_service, model_resolver, workflows_dir="workflows"):
    self.ollama = ollama_service
    self.model_resolver = model_resolver
    self.workflows_dir = Path(workflows_dir)

    # Prompt composer
    project_root = Path(__file__).resolve().parents[2]
    self.composer = PromptComposer(
        roles_dir=project_root / "prompts" / "roles",
        templates_dir=project_root / "prompts" / "templates",
    )

    # Hook bus with built-in defaults + custom auto-discovery
    self.hook_bus = HookBus()
    self._register_default_hooks()
    self.hook_bus.discover_and_register(project_root / "api" / "hooks" / "custom", source="custom")

    # Executor takes the full triple
    self.step_executor = StepExecutor(
        ollama_service=ollama_service,
        composer=self.composer,
        hook_bus=self.hook_bus,
    )
```

Add the helper method:

```python
def _register_default_hooks(self):
    """Register the project-wide default hooks (applied to all workflows)."""
    from api.hooks.builtins.token_budget import TokenBudgetHook
    from api.hooks.builtins.output_logger import OutputLoggerHook
    from api.hooks.builtins.retry_with_feedback import RetryWithFeedbackHook
    from api.hooks.builtins.refusal_detector import RefusalDetectorHook

    self.hook_bus.register(TokenBudgetHook(max_prompt_tokens=3500, reserve_for_output=1024))
    self.hook_bus.register(OutputLoggerHook(include_prompt=False))
    self.hook_bus.register(RetryWithFeedbackHook(max_attempts=2, include_example=True))
    self.hook_bus.register(RefusalDetectorHook(patterns=[], use_family_defaults=True))
    # json_schema is step-scoped (needs step's output_schema), registered per-step in execute()
```

- [ ] **Step 17.3: Register per-step json_schema hook**

Locate the point in `workflow_engine.py` where `step_executor.execute` is called. Before the call, register a step-scoped json_schema hook if the step declares `output_schema`:

```python
# Inside the per-step loop, before step_executor.execute(...)
from api.hooks.builtins.json_schema import JsonSchemaHook

# Clear any previously-registered per-step hook (track in self for cleanup)
if step.output_schema:
    per_step_hook = JsonSchemaHook(schema=step.output_schema, strip_fences=True)
    self.hook_bus.register(per_step_hook, source="builtin")
```

Note on lifecycle: because json_schema is registered per step, in the NEXT iteration it would double-register. Refactor so the engine uses a fresh `HookBus` per step OR clears validate_output hooks between steps. Simplest fix — keep two buses:

Rewrite the per-step loop section to:

```python
for step in workflow.steps:
    # Build a per-step bus view by cloning registrations + adding step-scoped ones
    step_bus = self._build_step_bus(step)
    step_executor = StepExecutor(
        ollama_service=self.ollama,
        composer=self.composer,
        hook_bus=step_bus,
    )
    # ... continue with execute()
```

Add the helper:

```python
def _build_step_bus(self, step) -> HookBus:
    """Return a fresh HookBus with default hooks + step-scoped json_schema."""
    from api.hooks.builtins.token_budget import TokenBudgetHook
    from api.hooks.builtins.output_logger import OutputLoggerHook
    from api.hooks.builtins.retry_with_feedback import RetryWithFeedbackHook
    from api.hooks.builtins.refusal_detector import RefusalDetectorHook
    from api.hooks.builtins.json_schema import JsonSchemaHook

    bus = HookBus()
    bus.register(TokenBudgetHook(max_prompt_tokens=3500, reserve_for_output=1024))
    bus.register(OutputLoggerHook(include_prompt=False))
    bus.register(RetryWithFeedbackHook(max_attempts=2, include_example=True))
    bus.register(RefusalDetectorHook(patterns=[], use_family_defaults=True))
    if step.output_schema:
        bus.register(JsonSchemaHook(schema=step.output_schema, strip_fences=True))
    # Apply explicit per-step YAML hook overrides
    for spec in step.hooks.validate_output:
        bus.register(self._instantiate_hook(spec, "validate_output"))
    for spec in step.hooks.on_failure:
        bus.register(self._instantiate_hook(spec, "on_failure"))
    # ... repeat for other stages as needed
    # Finally, register custom discovered hooks
    project_root = Path(__file__).resolve().parents[2]
    bus.discover_and_register(project_root / "api" / "hooks" / "custom", source="custom")
    return bus

def _instantiate_hook(self, spec, stage):
    """Map a YAML HookSpec into a concrete built-in hook instance."""
    from api.hooks.builtins.json_schema import JsonSchemaHook
    from api.hooks.builtins.refusal_detector import RefusalDetectorHook
    from api.hooks.builtins.retry_with_feedback import RetryWithFeedbackHook
    from api.hooks.builtins.token_budget import TokenBudgetHook
    from api.hooks.builtins.output_logger import OutputLoggerHook
    from api.hooks.builtins.few_shot_injector import FewShotInjectorHook

    factory = {
        "json_schema": JsonSchemaHook,
        "refusal_detector": RefusalDetectorHook,
        "retry_with_feedback": RetryWithFeedbackHook,
        "token_budget": TokenBudgetHook,
        "output_logger": OutputLoggerHook,
        "few_shot_injector": FewShotInjectorHook,
    }.get(spec.name)
    if factory is None:
        raise ValueError(f"Unknown built-in hook: {spec.name}")
    return factory(**spec.config)
```

- [ ] **Step 17.4: Update `step_executor.execute` call site to pass `workflow` and `workflow_run`**

Find the `step_executor.execute(...)` call in `workflow_engine.py` and update it:

```python
result = step_executor.execute(
    step=step,
    workflow=workflow,
    context=run.context,
    resolved_model=resolved_model,
    defaults=workflow.defaults,
    workflow_run=run,
)
```

- [ ] **Step 17.5: Run all tests**

Run: `pytest tests/ -v --tb=short`
Expected: All unit + hook tests pass. Integration tests will be added in Task 22-27.

- [ ] **Step 17.6: Commit**

```bash
git add api/services/workflow_engine.py
git commit -m "feat(workflow): wire HookBus, PromptComposer, and per-step hook registration into WorkflowEngine"
```

---

## Task 18: CLI Upgrade Command (v1 → v2 YAML)

**Files:**
- Modify: `cli/workflow.py` — add `upgrade` subcommand
- Test: `tests/unit/test_cli_upgrade.py`

- [ ] **Step 18.1: Write failing test for upgrade**

`tests/unit/test_cli_upgrade.py`:
```python
import pytest
import yaml
from cli.workflow import upgrade_v1_to_v2


V1_YAML = """
id: demo
name: "Demo"
version: "1.0"
defaults:
  role: coding
steps:
  - id: analyze
    name: "Analyze"
    role: reasoning
    system_prompt: |
      You are a senior data architect.
      Analyze source files and extract entities.
    inputs: [seed.files]
    outputs: [entities, relationships]
"""


def test_upgrade_produces_valid_v2(tmp_path):
    src = tmp_path / "demo.yaml"
    src.write_text(V1_YAML)
    dst = tmp_path / "demo.v2.yaml"
    upgrade_v1_to_v2(src, dst)
    data = yaml.safe_load(dst.read_text())
    assert data["schema_version"] == 2
    step = data["steps"][0]
    assert "prompt" in step
    assert step["prompt"]["role_inline"].startswith("You are a senior data architect")
    assert "entities" in step["prompt"]["task"].lower() or "analyze" in step["prompt"]["task"].lower()
    assert "output_schema" in step
    assert step["output_schema"]["type"] == "object"
    assert "entities" in step["output_schema"]["properties"]
    assert "relationships" in step["output_schema"]["properties"]


def test_upgrade_never_overwrites(tmp_path):
    src = tmp_path / "demo.yaml"
    src.write_text(V1_YAML)
    dst = tmp_path / "demo.v2.yaml"
    dst.write_text("# existing\n")
    with pytest.raises(FileExistsError):
        upgrade_v1_to_v2(src, dst)


def test_upgrade_preserves_config_blocks(tmp_path):
    src = tmp_path / "demo.yaml"
    content = V1_YAML + """
    config:
      temperature: 0.3
"""
    src.write_text(content)
    dst = tmp_path / "demo.v2.yaml"
    upgrade_v1_to_v2(src, dst)
    data = yaml.safe_load(dst.read_text())
    assert data["steps"][0]["config"]["temperature"] == 0.3
```

- [ ] **Step 18.2: Run tests to verify failure**

Run: `pytest tests/unit/test_cli_upgrade.py -v`
Expected: `ImportError: cannot import name 'upgrade_v1_to_v2' from 'cli.workflow'`.

- [ ] **Step 18.3: Add `upgrade_v1_to_v2` function to `cli/workflow.py`**

Append to `cli/workflow.py` (before the `if __name__ == "__main__":` line if present):

```python
def upgrade_v1_to_v2(src_path, dst_path):
    """Upgrade a v1 workflow YAML into v2 schema. Never overwrites.

    Heuristics:
      - `system_prompt` → split: first sentence = role_inline, rest = task
      - `outputs` list → output_schema with string-typed properties
    """
    import re
    from pathlib import Path
    import yaml

    src = Path(src_path)
    dst = Path(dst_path)
    if dst.exists():
        raise FileExistsError(f"refusing to overwrite {dst}")

    data = yaml.safe_load(src.read_text())
    data["schema_version"] = 2

    for step in data.get("steps", []):
        sp = step.pop("system_prompt", None)
        if sp is None:
            continue
        sp = sp.strip()
        # First sentence becomes role; remainder becomes task
        m = re.match(r"([^.\n]+[.\n])(.*)", sp, re.DOTALL)
        if m:
            role_inline = m.group(1).strip()
            task = m.group(2).strip() or "(Perform the role described above.)"
        else:
            role_inline = sp
            task = "(Perform the role described above.)"
        step["prompt"] = {
            "role_inline": role_inline,
            "task": task,
            "constraints": [
                "Return JSON only. No prose, no markdown fences.",
            ],
        }
        outputs = step.get("outputs", [])
        step["output_schema"] = {
            "type": "object",
            "required": list(outputs),
            "properties": {k: {"type": "string"} for k in outputs},
        }

    dst.write_text(yaml.safe_dump(data, sort_keys=False))
    print(f"Upgraded → {dst}")
    print("Review generated output_schema: stubs are all type:string. Tighten as needed.")
```

- [ ] **Step 18.4: Wire subcommand into argparse (if `cli/workflow.py` uses argparse)**

Run: `grep -n "subparsers" cli/workflow.py`

If subparsers exist, add:
```python
p_upgrade = subparsers.add_parser("upgrade", help="Upgrade a v1 workflow YAML to v2")
p_upgrade.add_argument("src")
p_upgrade.add_argument("--out", default=None, help="Destination path (defaults to <src>.v2.yaml)")
```

And in the command dispatcher:
```python
elif args.command == "upgrade":
    from pathlib import Path
    src = Path(args.src)
    dst = Path(args.out) if args.out else src.with_suffix(".v2.yaml")
    upgrade_v1_to_v2(src, dst)
```

- [ ] **Step 18.5: Run tests to verify they pass**

Run: `pytest tests/unit/test_cli_upgrade.py -v`
Expected: 3 passed.

- [ ] **Step 18.6: Commit**

```bash
git add cli/workflow.py tests/unit/test_cli_upgrade.py
git commit -m "feat(workflow): add `workflow upgrade` CLI to convert v1 YAML to v2"
```

---

## Task 19: FakeOllamaClient Integration Fixture

**Files:**
- Create: `tests/integration/conftest.py`

- [ ] **Step 19.1: Create `tests/integration/conftest.py`**

```python
"""Shared fixtures for workflow engine integration tests (no real Ollama)."""

import pytest
from pathlib import Path
from api.services.hook_bus import HookBus
from api.services.prompt_composer import PromptComposer
from api.services.step_executor import StepExecutor


class FakeOllamaClient:
    """Scriptable stand-in for OllamaService.

    Construct with a list of responses; each call to `chat` returns the next.
    Responses may be strings (treated as the `content`) or dicts (passed through).
    """

    def __init__(self, responses=None):
        self._responses = list(responses or [])
        self.calls = []

    def chat(self, model, messages, temperature=None, max_tokens=None):
        self.calls.append({
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        })
        if not self._responses:
            return {"content": "", "prompt_eval_count": 0, "eval_count": 0}
        resp = self._responses.pop(0)
        if isinstance(resp, str):
            return {"content": resp, "prompt_eval_count": 5, "eval_count": 5}
        return resp


@pytest.fixture
def project_root():
    return Path(__file__).resolve().parents[2]


@pytest.fixture
def composer(project_root):
    return PromptComposer(
        roles_dir=project_root / "prompts" / "roles",
        templates_dir=project_root / "prompts" / "templates",
    )


@pytest.fixture
def empty_bus():
    return HookBus()


@pytest.fixture
def make_executor(composer):
    def _make(fake_client, bus):
        return StepExecutor(
            ollama_service=fake_client,
            composer=composer,
            hook_bus=bus,
        )
    return _make
```

- [ ] **Step 19.2: Commit**

```bash
git add tests/integration/conftest.py
git commit -m "test(workflow): add FakeOllamaClient fixture for integration tests"
```

---

## Task 20: Integration Test — Pipeline Happy Path

**Files:**
- Create: `tests/integration/test_pipeline_happy_path.py`

- [ ] **Step 20.1: Write the happy-path integration test**

`tests/integration/test_pipeline_happy_path.py`:
```python
import json
from api.models.workflow_models import (
    AgentStep,
    StepPrompt,
    WorkflowDefinition,
    WorkflowDefaults,
    WorkflowContext,
)
from api.hooks.builtins.json_schema import JsonSchemaHook
from tests.integration.conftest import FakeOllamaClient


def _workflow_with_one_step():
    step = AgentStep(
        id="analyze",
        name="Analyze",
        role="reasoning",
        prompt=StepPrompt(
            role_inline="You are X.",
            task="analyze the inputs",
            constraints=["JSON only"],
        ),
        inputs=["seed.files"],
        outputs=["entities", "count"],
        output_schema={
            "type": "object",
            "required": ["entities", "count"],
            "properties": {
                "entities": {"type": "array"},
                "count": {"type": "integer"},
            },
        },
    )
    wf = WorkflowDefinition(
        id="w", name="W", schema_version=2,
        context={"project": "Enclave"},
        defaults=WorkflowDefaults(),
        steps=[step],
    )
    return wf, step


def test_happy_path_writes_parsed_outputs_to_workspace(make_executor, empty_bus):
    wf, step = _workflow_with_one_step()
    ctx = WorkflowContext(seed={"files": ["a.py"]})

    empty_bus.register(JsonSchemaHook(schema=step.output_schema))

    client = FakeOllamaClient(responses=[
        json.dumps({"entities": [{"name": "User"}], "count": 1}),
    ])
    executor = make_executor(client, empty_bus)
    result = executor.execute(
        step=step,
        workflow=wf,
        context=ctx,
        resolved_model="mistral:latest",
        defaults=wf.defaults,
    )
    assert result.status == "completed"
    assert ctx.get_workspace("analyze", "entities") == [{"name": "User"}]
    assert ctx.get_workspace("analyze", "count") == 1
    assert len(client.calls) == 1
```

- [ ] **Step 20.2: Run test**

Run: `pytest tests/integration/test_pipeline_happy_path.py -v`
Expected: 1 passed.

- [ ] **Step 20.3: Commit**

```bash
git add tests/integration/test_pipeline_happy_path.py
git commit -m "test(workflow): integration happy-path — parsed outputs land in workspace"
```

---

## Task 21: Integration Test — Retry-With-Feedback Recovery

**Files:**
- Create: `tests/integration/test_retry_with_feedback_flow.py`

- [ ] **Step 21.1: Write the test**

`tests/integration/test_retry_with_feedback_flow.py`:
```python
import json
from api.models.workflow_models import (
    AgentStep, StepPrompt, WorkflowDefinition, WorkflowDefaults, WorkflowContext,
)
from api.hooks.builtins.json_schema import JsonSchemaHook
from api.hooks.builtins.retry_with_feedback import RetryWithFeedbackHook
from tests.integration.conftest import FakeOllamaClient


SCHEMA = {
    "type": "object",
    "required": ["answer"],
    "properties": {"answer": {"type": "integer"}},
}


def _step():
    return AgentStep(
        id="solve",
        name="Solve",
        role="reasoning",
        prompt=StepPrompt(role_inline="You are X.", task="solve", constraints=[]),
        inputs=[],
        outputs=["answer"],
        output_schema=SCHEMA,
        config={"retries": 2, "retry_delay": 0},
    )


def _workflow(step):
    return WorkflowDefinition(
        id="w", name="W", schema_version=2,
        defaults=WorkflowDefaults(retries=2, retry_delay=0),
        steps=[step],
    )


def test_malformed_json_then_valid_json_succeeds_on_attempt_two(make_executor, empty_bus):
    step = _step()
    wf = _workflow(step)
    ctx = WorkflowContext()

    empty_bus.register(JsonSchemaHook(schema=SCHEMA))
    empty_bus.register(RetryWithFeedbackHook(max_attempts=2))

    client = FakeOllamaClient(responses=[
        "not valid json at all",
        json.dumps({"answer": 42}),
    ])
    executor = make_executor(client, empty_bus)
    result = executor.execute(
        step=step, workflow=wf, context=ctx,
        resolved_model="mistral:latest", defaults=wf.defaults,
    )
    assert result.status == "completed"
    assert result.retries == 1
    assert ctx.get_workspace("solve", "answer") == 42
    assert len(client.calls) == 2
    # The second call's user message should include feedback from the first failure
    second_user = client.calls[1]["messages"][1]["content"]
    assert "previous" in second_user.lower()
    assert "json" in second_user.lower()


def test_all_attempts_fail_returns_failed_status(make_executor, empty_bus):
    step = _step()
    wf = _workflow(step)
    ctx = WorkflowContext()

    empty_bus.register(JsonSchemaHook(schema=SCHEMA))
    empty_bus.register(RetryWithFeedbackHook(max_attempts=2))

    client = FakeOllamaClient(responses=[
        "not json",
        "still not json",
        "still not json",
    ])
    executor = make_executor(client, empty_bus)
    result = executor.execute(
        step=step, workflow=wf, context=ctx,
        resolved_model="mistral:latest", defaults=wf.defaults,
    )
    assert result.status == "failed"
    assert len(client.calls) == 3  # initial + 2 retries
```

- [ ] **Step 21.2: Run test**

Run: `pytest tests/integration/test_retry_with_feedback_flow.py -v`
Expected: 2 passed.

- [ ] **Step 21.3: Commit**

```bash
git add tests/integration/test_retry_with_feedback_flow.py
git commit -m "test(workflow): integration — retry_with_feedback recovers malformed JSON on attempt 2"
```

---

## Task 22: Integration Test — Token Budget Truncation

**Files:**
- Create: `tests/integration/test_token_budget_truncation.py`

- [ ] **Step 22.1: Write the test**

`tests/integration/test_token_budget_truncation.py`:
```python
import json
from api.models.workflow_models import (
    AgentStep, StepPrompt, WorkflowDefinition, WorkflowDefaults, WorkflowContext,
)
from api.hooks.builtins.json_schema import JsonSchemaHook
from api.hooks.builtins.token_budget import TokenBudgetHook
from tests.integration.conftest import FakeOllamaClient


def test_long_context_gets_truncated_before_model_call(make_executor, empty_bus):
    # Workflow context huge; task + constraints concise
    long_ctx_value = "x " * 5000  # ~10k chars
    step = AgentStep(
        id="s", name="S", role="coding",
        prompt=StepPrompt(
            role_inline="You are X.",
            task="Respond with {\"ok\": true}",
            constraints=["BE BRIEF"],
        ),
        inputs=["seed.big"],
        outputs=["ok"],
        output_schema={"type": "object", "required": ["ok"], "properties": {"ok": {"type": "boolean"}}},
    )
    wf = WorkflowDefinition(
        id="w", name="W", schema_version=2,
        context={"big_thing": long_ctx_value},
        defaults=WorkflowDefaults(retries=0),
        steps=[step],
    )
    ctx = WorkflowContext(seed={"big": long_ctx_value})

    # Tight budget forces truncation
    empty_bus.register(TokenBudgetHook(max_prompt_tokens=500, reserve_for_output=100))
    empty_bus.register(JsonSchemaHook(schema=step.output_schema))

    client = FakeOllamaClient(responses=[json.dumps({"ok": True})])
    executor = make_executor(client, empty_bus)
    result = executor.execute(
        step=step, workflow=wf, context=ctx,
        resolved_model="mistral:latest", defaults=wf.defaults,
    )
    assert result.status == "completed"

    # Assertions about what was actually sent
    sent_system = client.calls[0]["messages"][0]["content"]
    # Task + Constraints are preserved verbatim
    assert "Respond with" in sent_system
    assert "BE BRIEF" in sent_system
    # Context was truncated
    assert "truncated for token budget" in sent_system or len(sent_system) < len(long_ctx_value)
```

- [ ] **Step 22.2: Run test**

Run: `pytest tests/integration/test_token_budget_truncation.py -v`
Expected: 1 passed.

- [ ] **Step 22.3: Commit**

```bash
git add tests/integration/test_token_budget_truncation.py
git commit -m "test(workflow): integration — token_budget truncates context but preserves task/constraints"
```

---

## Task 23: Integration Test — v1 Legacy Regression

**Files:**
- Create: `tests/integration/test_v1_legacy_regression.py`

- [ ] **Step 23.1: Write the test**

`tests/integration/test_v1_legacy_regression.py`:
```python
import json
from api.models.workflow_models import (
    AgentStep, WorkflowDefinition, WorkflowDefaults, WorkflowContext,
)
from tests.integration.conftest import FakeOllamaClient


def test_v1_system_prompt_step_runs_through_new_executor(make_executor, empty_bus):
    # Step uses v1 system_prompt only — no `prompt` block, no output_schema
    step = AgentStep(
        id="legacy",
        name="Legacy",
        role="coding",
        system_prompt="You are a legacy v1 agent. Respond with JSON {\"k\": \"v\"}.",
        inputs=[],
        outputs=["k"],
    )
    wf = WorkflowDefinition(
        id="legacy_wf", name="Legacy",
        # schema_version omitted → defaults to 1
        defaults=WorkflowDefaults(retries=0),
        steps=[step],
    )
    ctx = WorkflowContext()

    client = FakeOllamaClient(responses=[json.dumps({"k": "v"})])
    executor = make_executor(client, empty_bus)
    result = executor.execute(
        step=step, workflow=wf, context=ctx,
        resolved_model="mistral:latest", defaults=wf.defaults,
    )
    assert result.status == "completed"
    # For v1 w/o json_schema hook, output stored as raw text for all output keys
    stored = ctx.get_workspace("legacy", "k")
    assert stored is not None
```

- [ ] **Step 23.2: Run test**

Run: `pytest tests/integration/test_v1_legacy_regression.py -v`
Expected: 1 passed.

- [ ] **Step 23.3: Commit**

```bash
git add tests/integration/test_v1_legacy_regression.py
git commit -m "test(workflow): integration — v1 legacy system_prompt workflows still execute"
```

---

## Task 24: Integration Test — Custom Hook Auto-Discovery

**Files:**
- Create: `tests/integration/test_custom_hook_discovery.py`

- [ ] **Step 24.1: Write the test**

`tests/integration/test_custom_hook_discovery.py`:
```python
import json
import textwrap
from api.services.hook_bus import HookBus
from api.models.workflow_models import (
    AgentStep, StepPrompt, WorkflowDefinition, WorkflowDefaults, WorkflowContext,
)
from api.hooks.builtins.json_schema import JsonSchemaHook
from tests.integration.conftest import FakeOllamaClient


def test_custom_hook_fires_after_step(tmp_path, make_executor):
    # Write a custom after_step hook to a temp dir
    custom_dir = tmp_path / "custom"
    custom_dir.mkdir()
    (custom_dir / "counter_hook.py").write_text(textwrap.dedent("""
        from api.services.hook_bus import HookResult, register_hook

        CALLS = []

        @register_hook(stage="after_step", name="test_counter")
        def count(ctx):
            CALLS.append(ctx.step.id if ctx.step else None)
            return HookResult(action="continue")
    """))

    bus = HookBus()
    bus.register(JsonSchemaHook(schema={
        "type": "object", "required": ["ok"],
        "properties": {"ok": {"type": "boolean"}},
    }))
    registered = bus.discover_and_register(custom_dir, source="custom")
    assert registered == 1

    step = AgentStep(
        id="s", name="S", role="coding",
        prompt=StepPrompt(role_inline="You are X.", task="t", constraints=[]),
        outputs=["ok"],
        output_schema={"type": "object", "required": ["ok"], "properties": {"ok": {"type": "boolean"}}},
    )
    wf = WorkflowDefinition(id="w", name="W", schema_version=2, defaults=WorkflowDefaults(), steps=[step])
    client = FakeOllamaClient(responses=[json.dumps({"ok": True})])
    executor = make_executor(client, bus)
    executor.execute(
        step=step, workflow=wf, context=WorkflowContext(),
        resolved_model="mistral:latest", defaults=wf.defaults,
    )

    # The custom hook's module was loaded under a unique name; find its CALLS list
    import sys
    counter_mod = next(
        (m for name, m in sys.modules.items() if name.startswith("_hooks_auto_counter_hook_")),
        None,
    )
    assert counter_mod is not None
    assert "s" in counter_mod.CALLS
```

- [ ] **Step 24.2: Run test**

Run: `pytest tests/integration/test_custom_hook_discovery.py -v`
Expected: 1 passed.

- [ ] **Step 24.3: Commit**

```bash
git add tests/integration/test_custom_hook_discovery.py
git commit -m "test(workflow): integration — custom hooks auto-discovered from api/hooks/custom/"
```

---

## Task 25: Integration Test — Model Escalation

**Files:**
- Create: `tests/integration/test_model_escalation.py`

- [ ] **Step 25.1: Write the test**

`tests/integration/test_model_escalation.py`:
```python
import json
from api.models.workflow_models import (
    AgentStep, StepPrompt, WorkflowDefinition, WorkflowDefaults, WorkflowContext,
)
from api.hooks.builtins.json_schema import JsonSchemaHook
from api.hooks.builtins.retry_with_feedback import RetryWithFeedbackHook
from tests.integration.conftest import FakeOllamaClient


SCHEMA = {"type": "object", "required": ["k"], "properties": {"k": {"type": "string"}}}


def test_escalate_to_sets_shared_marker(make_executor, empty_bus):
    step = AgentStep(
        id="s", name="S", role="fast",
        prompt=StepPrompt(role_inline="You are X.", task="t", constraints=[]),
        outputs=["k"],
        output_schema=SCHEMA,
        config={"retries": 1, "retry_delay": 0},
    )
    wf = WorkflowDefinition(
        id="w", name="W", schema_version=2,
        defaults=WorkflowDefaults(retries=1, retry_delay=0),
        steps=[step],
    )
    ctx = WorkflowContext()

    empty_bus.register(JsonSchemaHook(schema=SCHEMA))
    empty_bus.register(RetryWithFeedbackHook(max_attempts=1, escalate_to="reasoning"))

    client = FakeOllamaClient(responses=[
        "bad output",
        json.dumps({"k": "v"}),
    ])
    executor = make_executor(client, empty_bus)
    result = executor.execute(
        step=step, workflow=wf, context=ctx,
        resolved_model="mistral:latest", defaults=wf.defaults,
    )
    assert result.status == "completed"
    # Executor surfaces the escalation hint to shared state under a namespaced key
    assert ctx.get_shared("_escalated_s") == "reasoning"
```

- [ ] **Step 25.2: Run test**

Run: `pytest tests/integration/test_model_escalation.py -v`
Expected: 1 passed.

- [ ] **Step 25.3: Commit**

```bash
git add tests/integration/test_model_escalation.py
git commit -m "test(workflow): integration — model escalation surfaces to shared state"
```

---

## Task 26: E2E Smoke Test (Real Ollama, Skipped in CI)

**Files:**
- Create: `tests/e2e/__init__.py`
- Create: `tests/e2e/test_family_adapters_live.py`

- [ ] **Step 26.1: Create `tests/e2e/__init__.py`**

```bash
mkdir -p tests/e2e
touch tests/e2e/__init__.py
```

- [ ] **Step 26.2: Create `tests/e2e/test_family_adapters_live.py`**

```python
"""
E2E smoke tests against a running Ollama. Skipped by default — run locally with
`pytest tests/e2e/ -v -m e2e --run-e2e` (requires Ollama service up and models pulled).
"""

import json
import os
import pytest
import requests

from api.models.workflow_models import (
    AgentStep, StepPrompt, WorkflowDefinition, WorkflowDefaults, WorkflowContext,
)
from api.services.hook_bus import HookBus
from api.services.prompt_composer import PromptComposer
from api.services.step_executor import StepExecutor
from api.services.ollama_service import OllamaService
from api.hooks.builtins.json_schema import JsonSchemaHook
from api.hooks.builtins.retry_with_feedback import RetryWithFeedbackHook


pytestmark = pytest.mark.e2e


def _ollama_up() -> bool:
    try:
        r = requests.get("http://localhost:11434/api/tags", timeout=1)
        return r.status_code == 200
    except Exception:
        return False


@pytest.fixture(autouse=True)
def skip_if_no_ollama():
    if not _ollama_up():
        pytest.skip("Ollama service not reachable at localhost:11434")


@pytest.mark.parametrize("model", [
    os.environ.get("ENCLAVE_E2E_MODEL", "mistral:latest"),
])
def test_end_to_end_simple_step(model, tmp_path):
    from pathlib import Path
    project_root = Path(__file__).resolve().parents[2]
    composer = PromptComposer(
        roles_dir=project_root / "prompts" / "roles",
        templates_dir=project_root / "prompts" / "templates",
    )
    schema = {
        "type": "object",
        "required": ["answer"],
        "properties": {"answer": {"type": "string"}},
    }
    bus = HookBus()
    bus.register(JsonSchemaHook(schema=schema, strip_fences=True))
    bus.register(RetryWithFeedbackHook(max_attempts=2))

    step = AgentStep(
        id="e2e", name="E2E", role="general",
        prompt=StepPrompt(
            role_inline="You answer trivia. Be concise.",
            task="What is the capital of France?",
            constraints=["Respond as JSON: {\"answer\": \"<city>\"}", "Exact city name only."],
        ),
        outputs=["answer"],
        output_schema=schema,
        config={"retries": 2, "retry_delay": 1},
    )
    wf = WorkflowDefinition(
        id="e2e", name="E2E", schema_version=2,
        defaults=WorkflowDefaults(retries=2, retry_delay=1),
        steps=[step],
    )

    executor = StepExecutor(
        ollama_service=OllamaService(base_url="http://localhost:11434"),
        composer=composer,
        hook_bus=bus,
    )
    ctx = WorkflowContext()
    result = executor.execute(
        step=step, workflow=wf, context=ctx,
        resolved_model=model, defaults=wf.defaults,
    )
    assert result.status == "completed", f"failed: {result.error}"
    answer = ctx.get_workspace("e2e", "answer")
    assert answer is not None
    assert "paris" in str(answer).lower()
```

- [ ] **Step 26.3: Add pytest marker config**

Ensure `pytest.ini` at the project root has:
```ini
[pytest]
markers =
    e2e: requires live Ollama service (skipped in CI)
```

Check current content: `grep -n "^markers" pytest.ini`
If the `[pytest]` section exists without a `markers` block, append the marker lines. If the file has no pytest section at all, create it.

- [ ] **Step 26.4: Run E2E (locally, with Ollama up) — optional verification**

Run: `pytest tests/e2e/ -v` (if Ollama is up and `mistral:latest` is pulled)
Expected: 1 passed. Otherwise: 1 skipped with "Ollama service not reachable".

- [ ] **Step 26.5: Commit**

```bash
git add tests/e2e/ pytest.ini
git commit -m "test(workflow): add E2E smoke test (skipped without live Ollama)"
```

---

## Task 27: Full Test Sweep + Coverage Check

- [ ] **Step 27.1: Run full test suite**

Run: `pytest tests/ -v --ignore=tests/e2e`
Expected: all tests pass (unit + hooks + integration). E2E skipped by default.

- [ ] **Step 27.2: Check coverage target (85% on the new module)**

Run: `pytest tests/ --ignore=tests/e2e --cov=api/services/hook_bus --cov=api/services/prompt_composer --cov=api/services/model_adapters --cov=api/hooks/builtins --cov-report=term-missing`
Expected: ≥ 85% line coverage across the listed modules.

- [ ] **Step 27.3: If coverage under 85%, add targeted tests for uncovered lines**

Review the "Missing" output and add unit tests for any uncovered conditional branches. Commit each additional test as its own `test(workflow): cover <case>` commit.

- [ ] **Step 27.4: Tag implementation complete**

```bash
git tag -a workflow-prompt-framework-v1 -m "Part A: workflow prompt framework complete"
```

---

## Self-Review Against Spec

- [x] **A.3 Module Boundaries:** Tasks 1-8 create `hook_bus`, `prompt_composer`, `model_adapters`. Task 3 sets up `api/hooks/builtins` + `api/hooks/custom`. Task 5 creates `prompts/roles` + `prompts/templates`.
- [x] **A.4 Lifecycle Contract:** Task 1 adds protocol; Task 2 adds HookBus with order + short-circuit rules; Task 3 adds auto-discovery.
- [x] **A.5 YAML Schema:** Task 15 extends `workflow_models.py` with `StepPrompt`, `HookSpec`, `schema_version`, `context`, `schemas`, `output_schema`.
- [x] **A.6 Model Adapters:** Tasks 7 + 8 implement base + Default + 6 family adapters with register/resolve.
- [x] **A.7 Built-in Hooks:** Tasks 9-14 implement all six built-ins (json_schema, refusal_detector, token_budget, output_logger, few_shot_injector, retry_with_feedback).
- [x] **A.8 Migration + Compatibility:** Task 15 keeps v1 fields; Task 16 handles v1 in `_compose`; Task 18 adds `upgrade` CLI; Task 23 regression test.
- [x] **A.9 Guardrails Policy:** No content-filter hooks shipped. `refusal_detector` exists only to trigger re-prompts.
- [x] **A.10 Testing Strategy:** Unit (Tasks 1, 4, 6, 7, 8, 15, 18), hook contract (9-14), integration (19-25), E2E (26).

No spec gaps identified.

**Placeholder scan:** No "TBD", "TODO", "fill in later", or bare `Similar to Task N` references.

**Type consistency:** `HookContext`/`HookResult` used consistently across Tasks 1-25. `ComposedPrompt` signature stable from Task 4 through Task 26. `StepPrompt`/`HookSpec` introduced in Task 15 and consumed in Task 16. Adapter `.prepare(prompt, params) → (prompt, params)` contract consistent across Tasks 7, 8, 16.
