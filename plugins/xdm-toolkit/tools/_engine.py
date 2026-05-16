# SPDX-FileCopyrightText: ohno llc
# SPDX-License-Identifier: AGPL-3.0-or-later
"""
analyseCode — main engine entry that mirrors `server/data/rules-engine.ts`
analyseCode (lines 4266-4475).

Runs the rule list against an XQL rule body, applies the same
post-processing supersession passes (parser cascade, INFO-012 adjacency
hint, ERR-025/INFO-007, WARN-035/WARN-020/WARN-030), and returns an
AnalysisResult with the source repo's scoring formula.

Derived from gocortex-xql-ide/server/data/rules-engine.ts (AGPL-3.0).
"""
from __future__ import annotations

import re
from typing import List

from ._rules import VALIDATION_RULES
from ._types import (
    AnalysisResult,
    AnalysisSummary,
    Severity,
    ValidationRule,
    Violation,
)

_ASSIGN_RE = re.compile(r"^\s*(?:xdm\.[\w.]+|_?[A-Za-z_]\w*)\s*=")


def _build_violation(rule: ValidationRule, lines: List[str], _full_code: str) -> Violation:
    """TS: buildViolation (line 4477). First line matching the top-level pattern wins."""
    line_num: int | None = None
    for i, line in enumerate(lines):
        if rule.pattern.search(line):
            line_num = i + 1
            break
    return Violation(
        ruleId=rule.id,
        ruleName=rule.name,
        severity=rule.severity,
        category=rule.category,
        message=rule.message,
        recommendation=rule.recommendation,
        codeSnippet=rule.codeSnippet,
        line=line_num,
    )


def _find_statement_start(lines: List[str], err_line: int) -> int:
    """TS: findStatementStart (line 4324). Walk back to nearest `<lhs> =` line."""
    for li in range(err_line - 1, -1, -1):
        raw = lines[li] if li < len(lines) else ""
        stripped = raw.split("//")[0]
        if _ASSIGN_RE.search(stripped):
            return li + 1
    return err_line


# Cascade-prone parser-conformance rules that contribute to INFO-012 adjacency.
_CASCADE_RULE_IDS = frozenset({"ERR-012", "ERR-013", "ERR-014", "ERR-017", "ERR-018"})


def _apply_cascade_suppression(violations: List[Violation], lines: List[str]) -> None:
    """TS lines 4312-4361: group parser-conformance errors by statement, keep earliest."""
    conformance = sorted(
        (v for v in violations
         if v.category == "Cortex Parser Conformance"
         and v.severity == "error"
         and v.line is not None),
        key=lambda v: v.line,  # type: ignore[arg-type]
    )
    if len(conformance) < 2:
        return

    stmt_groups: dict[int, list[Violation]] = {}
    for v in conformance:
        stmt = _find_statement_start(lines, v.line)  # type: ignore[arg-type]
        stmt_groups.setdefault(stmt, []).append(v)

    suppressed: set[int] = set()
    for group in stmt_groups.values():
        if len(group) < 2:
            continue
        root, *downstream = group
        for d in downstream:
            suppressed.add(id(d))
        if "(parser cascade" not in root.message:
            plural = "" if len(downstream) == 1 else "s"
            root.message = (
                f"{root.message} (parser cascade: {len(downstream)} downstream "
                f"error{plural} on the same statement suppressed -- fix this first)"
            )
    if suppressed:
        violations[:] = [v for v in violations if id(v) not in suppressed]


def _emit_info012_adjacency_hint(violations: List[Violation], code: str, rule_type: str) -> None:
    """TS lines 4363-4416: emit INFO-012 when 2+ cascade-prone errors fall on adjacent lines."""
    if rule_type != "modeling" or not re.search(r"\[MODEL:", code):
        return
    err_lines = sorted(
        v.line for v in violations
        if v.ruleId in _CASCADE_RULE_IDS
        and v.severity == "error"
        and v.line is not None
    )
    if not err_lines:
        return

    best_run: list[int] = []
    cur_run: list[int] = []
    for ln in err_lines:
        if not cur_run or ln - cur_run[-1] <= 1:
            cur_run.append(ln)
        else:
            if len(cur_run) > len(best_run):
                best_run = cur_run
            cur_run = [ln]
    if len(cur_run) > len(best_run):
        best_run = cur_run

    if len(best_run) >= 2:
        violations.append(Violation(
            ruleId="INFO-012",
            ruleName="Cascade root-cause hint",
            severity="info",
            category="Cortex Parser Conformance",
            message=(
                f"{len(best_run)} parser-conformance errors fall on adjacent lines "
                f"({best_run[0]}-{best_run[-1]}). Fix line {best_run[0]} first -- "
                f"subsequent cascade errors usually clear once the root cause is resolved"
            ),
            recommendation=(
                "Walk back from the earliest reported error to the preceding alter "
                "assignment. Check for: (a) infix arithmetic, (b) JSON-string column "
                "without '-> []' cast, (c) bare \"@element\" passthrough, "
                "(d) bareword true/false equality on string column. Fix the first "
                "defect, then re-validate"
            ),
            line=best_run[0],
        ))


_NAME_RE = re.compile(r"'([_A-Za-z]\w*)'")


def _apply_warn035_supersession(violations: List[Violation]) -> None:
    """TS lines 4424-4442: WARN-035 supersedes WARN-020/030 on the same line."""
    warn035_lines = {v.line for v in violations if v.ruleId == "WARN-035" and v.line is not None}
    if not warn035_lines:
        return
    violations[:] = [
        v for v in violations
        if not (v.ruleId in {"WARN-020", "WARN-030"} and v.line in warn035_lines)
    ]


def _apply_err025_supersession(violations: List[Violation]) -> None:
    """TS lines 4444-4458: ERR-025 supersedes INFO-007 for the same temp name on the same line."""
    err025_keys = set()
    for v in violations:
        if v.ruleId != "ERR-025":
            continue
        m = _NAME_RE.search(v.message)
        if m:
            err025_keys.add(f"{m.group(1)}@{v.line}")
    if not err025_keys:
        return
    keep: list[Violation] = []
    for v in violations:
        if v.ruleId == "INFO-007":
            m = _NAME_RE.search(v.message)
            if m and f"{m.group(1)}@{v.line}" in err025_keys:
                continue
        keep.append(v)
    violations[:] = keep


def _score(errors: int, warnings: int, info: int, suggestions: int) -> int:
    """TS lines 4465-4467: 100 - (20*err + 10*warn + 3*info + 1*sug), floor 0."""
    return max(0, 100 - (20 * errors + 10 * warnings + 3 * info + 1 * suggestions))


def analyse_code(code: str, rule_type: str = "modeling") -> AnalysisResult:
    """Main engine entry. Mirrors `analyseCode` from rules-engine.ts.

    Args:
        code: full text of the rule (typically a [MODEL: ...] or [INGEST: ...] block).
        rule_type: "modeling" or "parsing". Rules with appliesTo="both" run regardless.
    """
    if rule_type not in ("parsing", "modeling"):
        raise ValueError(f"rule_type must be 'parsing' or 'modeling', got {rule_type!r}")

    violations: List[Violation] = []
    suggestions: List[Violation] = []
    lines = code.split("\n")

    for rule in VALIDATION_RULES:
        if rule.appliesTo != "both" and rule.appliesTo != rule_type:
            continue

        if rule.customCheck is not None:
            for v in rule.customCheck(code, lines):
                (suggestions if v.severity == "suggestion" else violations).append(v)
            continue

        if not rule.pattern.search(code):
            continue
        if rule.antiPattern is not None and rule.antiPattern.search(code):
            continue

        v = _build_violation(rule, lines, code)
        (suggestions if rule.severity == "suggestion" else violations).append(v)

    # Post-processing supersessions
    _apply_cascade_suppression(violations, lines)
    _emit_info012_adjacency_hint(violations, code, rule_type)
    _apply_warn035_supersession(violations)
    _apply_err025_supersession(violations)

    errors = sum(1 for v in violations if v.severity == "error")
    warnings = sum(1 for v in violations if v.severity == "warning")
    info = sum(1 for v in violations if v.severity == "info")
    sug_count = len(suggestions)

    return AnalysisResult(
        violations=violations,
        suggestions=suggestions,
        score=_score(errors, warnings, info, sug_count),
        summary=AnalysisSummary(
            errors=errors, warnings=warnings, info=info, suggestions=sug_count,
        ),
    )
