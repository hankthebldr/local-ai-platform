"""
validate_xql — Legacy-shape shim over analyse_xql.

The original heuristic validator (Phase 0) returned a verdict shape
consumed by `workflows/xdm-rule-from-log.yaml`'s `validate_and_revise`
step. Phase 3 replaces the heuristic with the full 84-rule port behind
`analyse_xql`; this file translates the new structured output back to
the legacy {verdict, phases, issues, summary} shape so existing
workflows do not break.

For new code, prefer the `analyse_xql` tool directly — it carries the
rule IDs and recommendations the operator actually needs.

Derived from gocortex-xql-ide/server/data/rules-engine.ts (AGPL-3.0).
"""
from __future__ import annotations

from typing import Any, Dict, List

from .analyse_xql import execute as analyse_execute

# Severity translation: new (rules-engine) -> legacy (validate_xql).
_SEV_MAP = {
    "error": "BLOCKER",
    "warning": "WARNING",
    "info": "INFO",
    "suggestion": "INFO",
}


def _to_legacy_issue(v: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "line": v.get("line") or 0,
        "severity": _SEV_MAP.get(v.get("severity", "info"), "INFO"),
        "msg": f'[{v.get("ruleId", "???")}] {v.get("message", "")}',
        "rule_id": v.get("ruleId"),
        "recommendation": v.get("recommendation"),
    }


def execute(rule: str = "", **_unused) -> Dict[str, Any]:
    """Legacy entrypoint. Same signature, same return shape as Phase 0."""
    new = analyse_execute(rule=rule, kind=_unused.get("kind", "modeling"))

    issues: List[Dict[str, Any]] = []
    for v in new.get("violations", []):
        issues.append(_to_legacy_issue(v))
    for v in new.get("suggestions", []):
        legacy = _to_legacy_issue(v)
        legacy["severity"] = "INFO"
        issues.append(legacy)

    summary = new.get("summary", {})
    blockers = summary.get("errors", 0)
    warnings = summary.get("warnings", 0)
    info_count = summary.get("info", 0) + summary.get("suggestions", 0)

    verdict = new.get("verdict", "READY-TO-DEPLOY")

    # The legacy phases dict was informational only. Mark all three based on
    # absence of issues in their severity band so existing UI rendering keeps
    # working.
    return {
        "verdict": verdict,
        "phases": {
            "structural": {"pass": blockers == 0, "issues": []},
            "schema":     {"pass": blockers == 0, "issues": []},
            "transform":  {"pass": warnings == 0 and blockers == 0, "issues": []},
        },
        "issues": issues,
        "summary": f"{blockers} blockers, {warnings} warnings, {info_count} info",
        # Bonus: surface the analyser's score for callers that want it.
        "score": new.get("score", 0),
    }
