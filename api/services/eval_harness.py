"""Agent / workflow evaluation + regression harness.

The point of this module is *behavioral stability*: a reproducible way to
assert that an agent or workflow still behaves the way you expect after a
prompt edit, a model swap, or an engine change — the gap our review of Nerve /
smolagents / OpenShell identified (see
docs/plans/2026-06-07-openshell-agent-runtime-decision.md, follow-up #2).

It is deliberately thin and reuses what the engine already has:

  - Cases run through the real ``WorkflowEngine.run`` (or any injected runner),
    so an eval exercises the exact production path.
  - Assertions reuse the engine's safe ``evaluate_gate`` grammar — boolean
    expressions over the final workspace (``compose_brief.brief != ''``,
    ``'Action Items' in compose_brief.brief``, ``extract.confidence >= 0.8``).
    No function calls, no attribute access — just the same whitelisted AST the
    loop/ralph gates use. A ``matches`` assertion adds regex over a resolved
    ref (the one thing the gate grammar can't express).

Property-based by design: LLM output is non-deterministic, so we assert
*structural properties* (non-empty, contains, threshold, pattern) rather than
exact strings — the same philosophy Nerve's eval mode uses.

Suite shape (YAML):

    suite: meeting-summary-regression
    workflow: meeting-summary          # workflow id (looked up in workflows/) or a .yaml path
    cases:
      - name: happy-path
        seed:
          transcript: "..."
        expect_status: completed       # default
        assert:
          - gate: "extract_signals.action_items != []"
            why: "must surface at least one action item"
          - matches: { ref: "compose_brief.brief", pattern: "(?i)action items" }
            why: "brief must carry an Action Items section"

Run programmatically via ``run_suite_file(path)`` or from the CLI
(``cli/eval.py``). ``SuiteResult.ok`` is the CI signal.
"""

from __future__ import annotations

import re
from pathlib import Path
from time import monotonic
from typing import Any, Callable, Dict, List, Optional

import yaml
from pydantic import BaseModel, Field, model_validator

from ..models.workflow_models import WorkflowDefinition, WorkflowRun
from .engine_executors.loop import evaluate_gate

# A runner takes a case's seed and returns the completed WorkflowRun.
RunFn = Callable[["EvalCase"], WorkflowRun]


# ── Suite schema ────────────────────────────────────────────────────────────


class MatchSpec(BaseModel):
    ref: str  # dotted workspace ref, e.g. "compose_brief.brief"
    pattern: str  # Python regex
    negate: bool = False  # assert the pattern does NOT match


class Assertion(BaseModel):
    """Exactly one of ``gate`` or ``matches``."""

    gate: Optional[str] = None
    matches: Optional[MatchSpec] = None
    why: str = ""

    @model_validator(mode="after")
    def _exactly_one(self) -> "Assertion":
        if bool(self.gate) == bool(self.matches):
            raise ValueError("each assertion needs exactly one of: gate, matches")
        return self


class EvalCase(BaseModel):
    name: str
    seed: Dict[str, Any] = Field(default_factory=dict)
    expect_status: str = "completed"
    # `assert` is a Python keyword — accept it as an alias, store as `assertions`.
    assertions: List[Assertion] = Field(default_factory=list, alias="assert")

    model_config = {"populate_by_name": True}


class EvalSuite(BaseModel):
    suite: str
    workflow: str  # workflow id (resolved under workflows/) or a .yaml path
    cases: List[EvalCase] = Field(default_factory=list)


# ── Result schema ───────────────────────────────────────────────────────────


class AssertionResult(BaseModel):
    kind: str  # "status" | "gate" | "matches"
    expr: str  # human-readable form
    passed: bool
    why: str = ""
    error: Optional[str] = None


class CaseResult(BaseModel):
    name: str
    passed: bool
    status: str = ""
    expected_status: str = ""
    run_id: Optional[str] = None
    duration_ms: float = 0.0
    assertions: List[AssertionResult] = Field(default_factory=list)
    error: Optional[str] = None  # execution-level failure (engine threw)


class SuiteResult(BaseModel):
    suite: str
    total: int
    passed: int
    failed: int
    cases: List[CaseResult] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.failed == 0


# ── Assertion evaluation (pure — no engine needed) ──────────────────────────


def _eval_assertion(a: Assertion, run: WorkflowRun) -> AssertionResult:
    ctx = run.context
    if a.gate is not None:
        try:
            ok = evaluate_gate(a.gate, ctx)
            return AssertionResult(kind="gate", expr=a.gate, passed=bool(ok), why=a.why)
        except Exception as e:  # noqa: BLE001  (ValueError from gate eval, etc.)
            return AssertionResult(
                kind="gate", expr=a.gate, passed=False, why=a.why, error=str(e)
            )

    m = a.matches  # validated: present when gate is None
    expr = f"{m.ref} {'!~' if m.negate else '=~'} /{m.pattern}/"
    try:
        value = ctx.resolve_input(m.ref)
        found = re.search(m.pattern, "" if value is None else str(value)) is not None
        passed = (not found) if m.negate else found
        return AssertionResult(kind="matches", expr=expr, passed=passed, why=a.why)
    except Exception as e:  # noqa: BLE001
        return AssertionResult(
            kind="matches", expr=expr, passed=False, why=a.why, error=str(e)
        )


def evaluate_run(run: WorkflowRun, case: EvalCase) -> CaseResult:
    """Score a completed run against a case's expectations. Pure: given a
    WorkflowRun + a case it does no I/O, so it unit-tests with a synthetic run."""
    status_ok = (run.status or "") == case.expect_status
    asserts: List[AssertionResult] = [
        AssertionResult(
            kind="status",
            expr=f"status == {case.expect_status}",
            passed=status_ok,
            why="run must reach the expected terminal status",
        )
    ]
    for a in case.assertions:
        asserts.append(_eval_assertion(a, run))

    return CaseResult(
        name=case.name,
        passed=all(r.passed for r in asserts),
        status=run.status or "",
        expected_status=case.expect_status,
        run_id=run.run_id,
        assertions=asserts,
    )


# ── Suite execution (engine injected) ───────────────────────────────────────


def run_suite(suite: EvalSuite, run_fn: RunFn) -> SuiteResult:
    """Run every case through ``run_fn`` and score it. ``run_fn`` is injected so
    tests can pass a fake; production wires the real engine via
    ``engine_run_fn`` / ``run_suite_file``."""
    cases: List[CaseResult] = []
    for case in suite.cases:
        t0 = monotonic()
        try:
            run = run_fn(case)
        except Exception as e:  # noqa: BLE001  — one bad case shouldn't abort the suite
            cases.append(
                CaseResult(
                    name=case.name,
                    passed=False,
                    expected_status=case.expect_status,
                    error=f"execution failed: {e}",
                    duration_ms=(monotonic() - t0) * 1000,
                )
            )
            continue
        result = evaluate_run(run, case)
        result.duration_ms = (monotonic() - t0) * 1000
        cases.append(result)

    failed = sum(1 for c in cases if not c.passed)
    return SuiteResult(
        suite=suite.suite,
        total=len(cases),
        passed=len(cases) - failed,
        failed=failed,
        cases=cases,
    )


# ── Loading + engine wiring ─────────────────────────────────────────────────


def load_suite(path: str | Path) -> EvalSuite:
    raw = yaml.safe_load(Path(path).read_text())
    return EvalSuite.model_validate(raw)


def _resolve_workflow(ref: str, *, project_root: Path) -> Path:
    """A suite's ``workflow`` is either a path to a .yaml or a bare workflow id
    resolved under ``workflows/``."""
    p = Path(ref)
    if p.suffix in (".yaml", ".yml") and p.exists():
        return p
    candidate = project_root / "workflows" / f"{ref}.yaml"
    if candidate.exists():
        return candidate
    if p.exists():
        return p
    raise FileNotFoundError(
        f"workflow '{ref}' not found (looked for {candidate} and {p})"
    )


def engine_run_fn(engine: Any, definition: WorkflowDefinition) -> RunFn:
    """Build a RunFn that executes the given definition on the real engine."""

    def _run(case: EvalCase) -> WorkflowRun:
        return engine.run(definition, dict(case.seed))

    return _run


def run_suite_file(
    path: str | Path,
    *,
    engine: Any = None,
    project_root: Optional[Path] = None,
) -> SuiteResult:
    """Load + run a suite file against the real WorkflowEngine. Constructs a
    default engine from the Ollama service if one isn't injected."""
    project_root = project_root or Path(__file__).resolve().parents[2]
    suite = load_suite(path)

    if engine is None:
        from .workflow_engine import WorkflowEngine
        from ..main import (
            get_ollama_service,
        )  # lazy: avoids import cycle at module load

        engine = WorkflowEngine(get_ollama_service())

    wf_path = _resolve_workflow(suite.workflow, project_root=project_root)
    definition = engine.load(str(wf_path))
    return run_suite(suite, engine_run_fn(engine, definition))


# ── Reporting ───────────────────────────────────────────────────────────────


def format_report(result: SuiteResult) -> str:
    """Human-readable suite report for the CLI."""
    lines = [
        f"suite: {result.suite}",
        f"  {result.passed}/{result.total} cases passed"
        + (f" · {result.failed} FAILED" if result.failed else ""),
        "",
    ]
    for c in result.cases:
        mark = "PASS" if c.passed else "FAIL"
        head = f"  [{mark}] {c.name}  ({c.status or '—'}, {c.duration_ms:.0f}ms)"
        lines.append(head)
        if c.error:
            lines.append(f"        ! {c.error}")
        for a in c.assertions:
            if a.passed and result.ok:
                continue  # keep green suites terse; only surface detail when something failed
            amark = "ok" if a.passed else "XX"
            lines.append(
                f"        {amark} {a.expr}" + (f"  — {a.why}" if a.why else "")
            )
            if a.error:
                lines.append(f"           error: {a.error}")
    return "\n".join(lines)
