# SPDX-FileCopyrightText: ohno llc
# SPDX-License-Identifier: AGPL-3.0-or-later
"""
analyse_xql — public tool entry. Runs the full rules-engine port against
an XQL data model or parsing rule and returns the structured analyser
report (rule IDs, line numbers, severities, recommendations, score).

This is the new high-fidelity validator. The legacy `validate_xql` tool
remains as a thin shim that calls this and translates to the older
BLOCKER/WARNING/INFO verdict shape that `xdm-rule-from-log.yaml`
currently consumes.

Tool contract (plugin.yaml `analyse_xql`):
    Input:
      rule: str   — the rule text to validate
      kind: str   — "modeling" (default) or "parsing"
    Output:
      see AnalysisResult.to_dict — `violations`, `suggestions`,
      `score`, `summary`, plus a derived `verdict` field for
      ergonomics.

Derived from gocortex-xql-ide/server/data/rules-engine.ts (AGPL-3.0).
"""
from __future__ import annotations

from typing import Any, Dict

from ._engine import analyse_code


def _verdict(summary: Dict[str, int]) -> str:
    """Derive a one-word verdict matching the legacy validator surface."""
    errors = summary["errors"]
    warnings = summary["warnings"]
    if errors >= 3:
        return "REWRITE-RECOMMENDED"
    if errors > 0:
        return "NEEDS-FIXES"
    if warnings > 0:
        return "NEEDS-FIXES"
    return "READY-TO-DEPLOY"


def execute(rule: str = "", kind: str = "modeling", **_unused) -> Dict[str, Any]:
    """Plugin entrypoint. Returns a JSON-friendly dict."""
    if not isinstance(rule, str) or not rule.strip():
        return {
            "verdict": "REWRITE-RECOMMENDED",
            "violations": [],
            "suggestions": [],
            "score": 0,
            "summary": {"errors": 1, "warnings": 0, "info": 0, "suggestions": 0},
            "error": "empty rule body",
        }
    if kind not in ("parsing", "modeling"):
        kind = "modeling"

    result = analyse_code(rule, rule_type=kind)
    out = result.to_dict()
    out["verdict"] = _verdict(out["summary"])
    return out
