#!/usr/bin/env python3
"""Tests for the agent/workflow eval-regression harness.

The assertion engine (evaluate_run) is pure — it scores a synthetic
WorkflowRun, so no engine/LLM is needed here. run_suite is exercised with an
injected fake runner. The shipped sample suite is parsed to guard its schema.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from api.models.workflow_models import WorkflowContext, WorkflowRun
from api.services.eval_harness import (
    Assertion,
    EvalCase,
    EvalSuite,
    evaluate_run,
    load_suite,
    run_suite,
)


def _run(status="completed", **workspace) -> WorkflowRun:
    """Build a synthetic completed run with the given workspace values.
    Keys are "step__key" → workspace[step][key] (double underscore splits)."""
    ctx = WorkflowContext(seed={})
    for compound, value in workspace.items():
        step, key = compound.split("__", 1)
        ctx.set_workspace(step, key, value)
    return WorkflowRun(workflow_id="wf", context=ctx, status=status)


# ── Assertion schema ────────────────────────────────────────────────────────


def test_assertion_requires_exactly_one():
    Assertion(gate="a.b != []")  # ok
    Assertion(matches={"ref": "a.b", "pattern": "x"})  # ok
    with pytest.raises(ValueError):
        Assertion()  # neither
    with pytest.raises(ValueError):
        Assertion(gate="x", matches={"ref": "a.b", "pattern": "x"})  # both


def test_case_accepts_assert_alias():
    case = EvalCase.model_validate({"name": "c", "assert": [{"gate": "a.b != []"}]})
    assert len(case.assertions) == 1
    assert case.assertions[0].gate == "a.b != []"


# ── Gate assertions ─────────────────────────────────────────────────────────


def test_gate_pass():
    run = _run(extract__action_items=["do x"])
    case = EvalCase(name="c", assertions=[Assertion(gate="extract.action_items != []")])
    res = evaluate_run(run, case)
    assert res.passed
    # status assertion is always prepended.
    assert res.assertions[0].kind == "status"
    assert all(a.passed for a in res.assertions)


def test_gate_fail():
    run = _run(extract__action_items=[])
    case = EvalCase(name="c", assertions=[Assertion(gate="extract.action_items != []")])
    res = evaluate_run(run, case)
    assert not res.passed
    gate_res = [a for a in res.assertions if a.kind == "gate"][0]
    assert gate_res.passed is False


def test_gate_invalid_expr_is_error_not_crash():
    run = _run(extract__x=1)
    case = EvalCase(name="c", assertions=[Assertion(gate="extract.x +++ bad")])
    res = evaluate_run(run, case)
    assert not res.passed
    gate_res = [a for a in res.assertions if a.kind == "gate"][0]
    assert gate_res.error is not None


def test_gate_membership_on_string():
    run = _run(compose__brief="## Action Items\n- do x")
    case = EvalCase(
        name="c", assertions=[Assertion(gate="'Action Items' in compose.brief")]
    )
    assert evaluate_run(run, case).passed


# ── Regex (matches) assertions ──────────────────────────────────────────────


def test_matches_pass():
    run = _run(compose__brief="## Action Items\n- ship it")
    case = EvalCase(
        name="c",
        assertions=[Assertion(matches={"ref": "compose.brief", "pattern": r"(?i)action"})],
    )
    assert evaluate_run(run, case).passed


def test_matches_negate():
    run = _run(compose__brief="clean summary")
    case = EvalCase(
        name="c",
        assertions=[
            Assertion(
                matches={"ref": "compose.brief", "pattern": "ERROR", "negate": True}
            )
        ],
    )
    assert evaluate_run(run, case).passed  # ERROR absent → negate passes


def test_matches_missing_ref_resolves_none():
    run = _run(compose__brief="x")
    case = EvalCase(
        name="c",
        assertions=[Assertion(matches={"ref": "nope.gone", "pattern": "x"})],
    )
    # None → "" → no match → assertion fails (but no crash).
    res = evaluate_run(run, case)
    assert not res.passed


# ── Status check ────────────────────────────────────────────────────────────


def test_status_mismatch_fails_case():
    run = _run(status="failed", extract__action_items=["x"])
    case = EvalCase(
        name="c",
        expect_status="completed",
        assertions=[Assertion(gate="extract.action_items != []")],
    )
    res = evaluate_run(run, case)
    assert not res.passed  # gate passes but status assertion fails
    status_res = [a for a in res.assertions if a.kind == "status"][0]
    assert status_res.passed is False


# ── Suite orchestration ─────────────────────────────────────────────────────


def test_run_suite_all_pass():
    suite = EvalSuite(
        suite="s",
        workflow="wf",
        cases=[
            EvalCase(name="a", assertions=[Assertion(gate="x.k == 1")]),
            EvalCase(name="b", assertions=[Assertion(gate="x.k != 2")]),
        ],
    )
    result = run_suite(suite, lambda case: _run(x__k=1))
    assert result.ok
    assert result.passed == 2 and result.failed == 0


def test_run_suite_isolates_execution_failure():
    def run_fn(case):
        if case.name == "boom":
            raise RuntimeError("engine exploded")
        return _run(x__k=1)

    suite = EvalSuite(
        suite="s",
        workflow="wf",
        cases=[
            EvalCase(name="ok", assertions=[Assertion(gate="x.k == 1")]),
            EvalCase(name="boom", assertions=[Assertion(gate="x.k == 1")]),
        ],
    )
    result = run_suite(suite, run_fn)
    assert result.failed == 1 and result.passed == 1
    boom = [c for c in result.cases if c.name == "boom"][0]
    assert boom.error and "engine exploded" in boom.error


# ── Shipped sample parses ───────────────────────────────────────────────────


def test_sample_suite_parses():
    root = Path(__file__).resolve().parents[1]
    suite = load_suite(root / "evals" / "meeting-summary.eval.yaml")
    assert suite.workflow == "meeting-summary"
    assert len(suite.cases) >= 1
    # every assertion is well-formed (exactly-one validator ran).
    assert all(c.assertions for c in suite.cases)
