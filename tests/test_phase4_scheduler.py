"""Phase 4 — DAG scheduling facade.

Covers:
  1. Scheduler.ready_steps() — depends_on resolution
  2. Scheduler.schedule() — arch delegation
  3. Scheduler.validate_feasibility() — per-step feasibility checks
  4. Scheduler.preview() — full DAG walk producing tick-by-tick schedule
  5. AgentStep.est_size_gb — schema acceptance + round-trip
  6. Integration: workflow engine raises on infeasible workflows
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from api.exceptions import WorkflowValidationError
from api.models.workflow_models import (
    AgentStep,
    StepPrompt,
    WorkflowDefaults,
    WorkflowDefinition,
)
from api.services.scheduler import FeasibilityIssue, Scheduler, SchedulePreview


# ── Test helpers ─────────────────────────────────────────────────────────


def _step(step_id, depends_on=None, est_size_gb=None, model="m"):
    return AgentStep(
        id=step_id,
        name=step_id,
        model=model,
        prompt=StepPrompt(role_inline="r", task="t"),
        outputs=["out"],
        depends_on=depends_on or [],
        est_size_gb=est_size_gb,
    )


def _defn(steps):
    return WorkflowDefinition(
        id="w",
        name="w",
        steps=steps,
        defaults=WorkflowDefaults(),
    )


class _MockArch:
    """Minimal arch mock — schedule_ready picks head, feasible budgets."""

    def __init__(self, total_memory_gb=48.0, budget_gb=40.0):
        self.name = SimpleNamespace(value="mock_arch")
        self.total_memory_gb = total_memory_gb
        self._budget = budget_gb

    def schedule_ready(self, ready):
        if not ready:
            return []
        decisions = [SimpleNamespace(step_id=ready[0].id, placement=0, deferred=False)]
        for rest in ready[1:]:
            decisions.append(
                SimpleNamespace(
                    step_id=rest.id,
                    placement=None,
                    deferred=True,
                    defer_reason="sequential mock",
                )
            )
        return decisions

    def feasible(self, island):
        if not island:
            return SimpleNamespace(fits=True, reason=None)
        largest = max((s.est_size_gb or 0) for s in island)
        fits = largest <= self._budget
        return SimpleNamespace(
            fits=fits,
            reason=None if fits else f"{largest} GB exceeds {self._budget} GB budget",
        )


# ── ready_steps ──────────────────────────────────────────────────────────


def test_ready_steps_no_deps_all_ready_initially():
    s = Scheduler(arch=_MockArch())
    steps = [_step("a"), _step("b"), _step("c")]
    ready = s.ready_steps(steps, completed_step_ids=set())
    assert [r.id for r in ready] == ["a", "b", "c"]


def test_ready_steps_with_deps_blocks_until_satisfied():
    s = Scheduler(arch=_MockArch())
    steps = [_step("a"), _step("b", depends_on=["a"]), _step("c", depends_on=["b"])]
    assert [r.id for r in s.ready_steps(steps, set())] == ["a"]
    assert [r.id for r in s.ready_steps(steps, {"a"})] == ["b"]
    assert [r.id for r in s.ready_steps(steps, {"a", "b"})] == ["c"]
    assert s.ready_steps(steps, {"a", "b", "c"}) == []


def test_ready_steps_diamond_dag():
    """a → {b, c} → d — b and c are ready together after a, then d after both."""
    s = Scheduler(arch=_MockArch())
    steps = [
        _step("a"),
        _step("b", depends_on=["a"]),
        _step("c", depends_on=["a"]),
        _step("d", depends_on=["b", "c"]),
    ]
    assert {r.id for r in s.ready_steps(steps, {"a"})} == {"b", "c"}
    assert {r.id for r in s.ready_steps(steps, {"a", "b"})} == {"c"}
    assert {r.id for r in s.ready_steps(steps, {"a", "b", "c"})} == {"d"}


# ── schedule (arch delegation) ───────────────────────────────────────────


def test_schedule_delegates_to_arch():
    arch = _MockArch()
    s = Scheduler(arch=arch)
    decisions = s.schedule([_step("a"), _step("b")])
    assert len(decisions) == 2
    assert decisions[0].deferred is False
    assert decisions[1].deferred is True


def test_schedule_falls_back_to_unknown_arch_when_no_detection():
    """Detection failure (singleton unset) falls through to
    UnknownArchitecture so the engine still gets a usable schedule
    (head dispatched, rest deferred) rather than [] — which the engine
    would treat as a deadlock and fail the run."""
    s = Scheduler(arch=None)
    decisions = s.schedule([_step("a"), _step("b")])
    assert len(decisions) == 2
    # Head is not deferred; the rest are.
    assert not getattr(decisions[0], "deferred", False)
    assert getattr(decisions[1], "deferred", False) is True


# ── validate_feasibility ─────────────────────────────────────────────────


def test_validate_feasibility_no_op_when_no_est_size():
    """Pre-Phase-4 workflows (no est_size_gb) pass through cleanly."""
    s = Scheduler(arch=_MockArch())
    issues = s.validate_feasibility(_defn([_step("a"), _step("b")]))
    assert issues == []


def test_validate_feasibility_flags_oversize_steps():
    s = Scheduler(arch=_MockArch(total_memory_gb=48.0, budget_gb=40.0))
    defn = _defn(
        [
            _step("small", est_size_gb=4.5),  # 7B Q4 — fits
            _step("medium", est_size_gb=20.0),  # 32B Q4 — fits
            _step("huge", est_size_gb=80.0),  # doesn't fit
        ]
    )
    issues = s.validate_feasibility(defn)
    assert len(issues) == 1
    assert issues[0].step_id == "huge"
    assert issues[0].est_size_gb == 80.0


def test_validate_feasibility_skips_steps_without_size():
    """Mixed workflow: some steps have est_size_gb, others don't.
    Only the sized ones are checked; unsized ones are silently skipped."""
    s = Scheduler(arch=_MockArch(budget_gb=40.0))
    defn = _defn(
        [
            _step("sized", est_size_gb=80.0),  # would fail
            _step("unsized", est_size_gb=None),  # skipped
        ]
    )
    issues = s.validate_feasibility(defn)
    assert len(issues) == 1
    assert issues[0].step_id == "sized"


# ── preview (full DAG walk) ──────────────────────────────────────────────


def test_preview_sequential_workflow():
    s = Scheduler(arch=_MockArch())
    defn = _defn([_step("a"), _step("b", depends_on=["a"])])
    preview = s.preview(defn)
    assert preview.arch_name == "mock_arch"
    assert len(preview.ticks) == 2
    assert preview.ticks[0]["ready_step_ids"] == ["a"]
    assert preview.ticks[1]["ready_step_ids"] == ["b"]
    assert preview.feasibility_issues == []


def test_preview_diamond_dag_groups_ready_steps():
    """In the diamond DAG, b and c are ready together after a — the
    preview should surface them in a single tick (the arch decides
    whether they actually run in parallel)."""
    s = Scheduler(arch=_MockArch())
    defn = _defn(
        [
            _step("a"),
            _step("b", depends_on=["a"]),
            _step("c", depends_on=["a"]),
            _step("d", depends_on=["b", "c"]),
        ]
    )
    preview = s.preview(defn)
    # Tick 1: a alone
    assert preview.ticks[0]["ready_step_ids"] == ["a"]
    # Tick 2: b and c both ready (mock arch picks b, defers c)
    assert set(preview.ticks[1]["ready_step_ids"]) == {"b", "c"}
    # Tick 3: c (no longer deferred by completion of tick 2's b) then... etc.
    # The exact tick count depends on arch deferral semantics — what matters
    # is the preview eventually completes all steps without deadlocking.
    last_tick = preview.ticks[-1]
    assert "d" in last_tick["ready_step_ids"]


def test_preview_falls_back_to_unknown_arch():
    """When detection failed, Scheduler() falls through to
    UnknownArchitecture — the preview produces real ticks with the
    head-dispatched/rest-deferred shape, not a deadlock."""
    s = Scheduler(arch=None)
    defn = _defn([_step("a"), _step("b", depends_on=["a"])])
    preview = s.preview(defn)
    assert preview.arch_name == "unknown"
    # Two sequential ticks: a then b.
    assert len(preview.ticks) == 2
    assert preview.ticks[0]["ready_step_ids"] == ["a"]
    assert preview.ticks[1]["ready_step_ids"] == ["b"]
    assert preview.notes == []


# ── Schema ───────────────────────────────────────────────────────────────


def test_agent_step_accepts_est_size_gb():
    s = AgentStep(
        id="s1",
        name="s",
        prompt=StepPrompt(role_inline="r", task="t"),
        outputs=["out"],
        est_size_gb=20.0,
    )
    assert s.est_size_gb == 20.0
    assert s.model_dump()["est_size_gb"] == 20.0


def test_agent_step_default_est_size_gb_is_none():
    """Pre-Phase-4 YAMLs without the field deserialise to None."""
    s = AgentStep(
        id="s1",
        name="s",
        prompt=StepPrompt(role_inline="r", task="t"),
        outputs=["out"],
    )
    assert s.est_size_gb is None


# ── Phase 4.4 — starvation handling ──────────────────────────────────────


class _DeferAllArch:
    """Arch that defers every step it sees — simulates an over-pressured GPU
    or an impossibly-large model. Used to trigger starvation."""

    def __init__(self):
        self.name = SimpleNamespace(value="defer_all")
        self.total_memory_gb = 8.0

    def schedule_ready(self, ready):
        return [
            SimpleNamespace(
                step_id=s.id,
                placement=None,
                deferred=True,
                defer_reason="forced defer",
            )
            for s in ready
        ]

    def feasible(self, island):
        return SimpleNamespace(fits=True, reason=None)


def test_scheduler_starvation_emits_capacity_starvation_after_max_defers():
    """A step deferred more than max_defer_ticks gets annotated with
    error_code='capacity_starvation' so the engine can promote it to a
    real failure rather than spin forever."""
    s = Scheduler(arch=_DeferAllArch(), max_defer_ticks=3)
    step = _step("oversize")

    # First 2 ticks: still deferred, no error annotation
    for _ in range(2):
        decisions = s.schedule([step])
        assert getattr(decisions[0], "error_code", None) is None

    # Third tick: defer count hits 3 (== max), starvation annotation appears
    decisions = s.schedule([step])
    assert getattr(decisions[0], "error_code", None) == "capacity_starvation"
    assert "deferred 3 times" in getattr(decisions[0], "error_message", "")


def test_scheduler_starvation_count_resets_on_dispatch():
    """If the arch finally dispatches a step (not deferred), the counter
    resets so a later defer doesn't carry stale weight."""
    arch = _DeferAllArch()
    s = Scheduler(arch=arch, max_defer_ticks=5)
    step = _step("temp")

    # Defer twice
    for _ in range(2):
        s.schedule([step])
    assert s.defer_counts.get("temp") == 2

    # Swap to a non-deferring arch — first call dispatches, counter clears
    s.arch = _MockArch()
    s.schedule([step])
    assert s.defer_counts.get("temp") is None


def test_scheduler_clear_defer_manual_reset():
    """clear_defer() resets a single step's counter without touching others."""
    s = Scheduler(arch=_DeferAllArch(), max_defer_ticks=10)
    s.schedule([_step("a"), _step("b")])
    assert s.defer_counts.get("a") == 1
    assert s.defer_counts.get("b") == 1

    s.clear_defer("a")
    assert s.defer_counts.get("a") is None
    assert s.defer_counts.get("b") == 1  # unchanged


def test_scheduler_defer_counts_property_is_readonly_view():
    """defer_counts returns a copy — mutating it doesn't affect scheduler state."""
    s = Scheduler(arch=_DeferAllArch())
    s.schedule([_step("x")])
    view = s.defer_counts
    view["x"] = 999
    # Internal counter untouched
    assert s.defer_counts["x"] == 1


# ── Integration: validation rejects infeasible workflows ─────────────────


def test_engine_validate_rejects_oversize_when_arch_set(monkeypatch):
    """When a step's est_size_gb exceeds the arch budget, engine.validate()
    raises WorkflowValidationError with a useful message."""
    from api.services import architecture as arch_mod
    from api.services.workflow_engine import WorkflowEngine

    arch_mod._set_current(_MockArch(total_memory_gb=48.0, budget_gb=40.0))
    try:
        defn = _defn([_step("oversize", est_size_gb=80.0)])
        engine = WorkflowEngine.__new__(WorkflowEngine)  # skip __init__
        with pytest.raises(WorkflowValidationError) as exc:
            engine.validate(defn)
        assert "oversize" in str(exc.value)
        assert "80" in str(exc.value)
    finally:
        arch_mod._current_architecture = None


def test_engine_validate_passes_when_no_est_size_set():
    """Workflows without est_size_gb on any step validate cleanly —
    preserves pre-Phase-4 acceptance surface."""
    from api.services import architecture as arch_mod
    from api.services.workflow_engine import WorkflowEngine

    arch_mod._set_current(_MockArch())
    try:
        defn = _defn([_step("a"), _step("b", depends_on=["a"])])
        engine = WorkflowEngine.__new__(WorkflowEngine)
        engine.validate(defn)  # should not raise
    finally:
        arch_mod._current_architecture = None
