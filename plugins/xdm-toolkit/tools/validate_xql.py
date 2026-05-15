"""
validate_xql — static-validate an XQL data model rule.

Catches the most common parser-conformance + structural failures without
running the rule against a live Cortex tenant:

  - missing MODEL/INGEST header
  - missing MAPPED-header comment block
  - unbalanced parens / brackets / braces
  - duplicate assignments to the same xdm.* path
  - companion-pair violations from knowledge §9.2
  - MITRE arraymap double-wrapping
  - bare-scalar array assignments (missing arraycreate())
  - obviously-unknown XDM namespaces

Heuristic, not a real parser — false negatives are possible. Intended as
the fast pre-flight check before the operator pastes into a tenant.

Returns a dict shaped:

    {
      "verdict": "READY-TO-DEPLOY" | "NEEDS-FIXES" | "REWRITE-RECOMMENDED",
      "phases": {
        "structural": {"pass": bool, "issues": [...]},
        "schema":     {"pass": bool, "issues": [...]},
        "transform":  {"pass": bool, "issues": [...]},
      },
      "issues":  [{"line": int, "severity": "BLOCKER|WARNING|INFO", "msg": str}, ...],
      "summary": "n blockers, m warnings, k info"
    }
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

# Known XDM top-level namespaces. Anything outside these is almost
# certainly hallucinated. Sourced from knowledge §2 outline.
XDM_NAMESPACES = {
    "xdm.event",
    "xdm.source",
    "xdm.target",
    "xdm.observer",
    "xdm.network",
    "xdm.auth",
    "xdm.alert",
    "xdm.intermediate",
    "xdm.session",
    "xdm.email",
    "xdm.cloud",
    "xdm.threat",
}

# Companion pairs from §9.2 — if you map one side, you must map the other.
# This is a minimal seed; full set lives in the knowledge file.
COMPANION_PAIRS = [
    ("xdm.source.ipv4", "xdm.source.host.ipv4_addresses"),
    ("xdm.target.ipv4", "xdm.target.host.ipv4_addresses"),
    ("xdm.source.port", "xdm.target.port"),  # weak pair — usually both
    ("xdm.network.application_protocol", "xdm.network.application_protocol_category"),
    ("xdm.auth.outcome", "xdm.auth.outcome_reason"),
]


def _balanced(text: str, opener: str, closer: str) -> int:
    """Return depth at end of text. 0 = balanced. Non-zero = unbalanced."""
    depth = 0
    for ch in text:
        if ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth < 0:
                return depth
    return depth


def _scan_xdm_paths(rule: str) -> List[str]:
    """Extract every xdm.<...> token referenced as an assignment target."""
    return [m.group(1) for m in re.finditer(r"\b(xdm\.[A-Za-z0-9_.]+)\s*=", rule)]


def _scan_all_xdm_paths(rule: str) -> List[str]:
    return [m.group(1) for m in re.finditer(r"\b(xdm\.[A-Za-z0-9_.]+)", rule)]


def execute(rule: str = "", **_unused) -> Dict[str, Any]:
    """Plugin tool entrypoint — kwargs match the manifest's `parameters:` block.

    The plugin runtime spreads the params dict as kwargs via `func(**params)`,
    so each declared parameter must appear here as a typed positional or
    keyword arg. Extras (like a sandbox injection) are accepted via **_unused.
    """
    rule = (rule or "").strip()
    if not rule:
        return {
            "verdict": "REWRITE-RECOMMENDED",
            "phases": {},
            "issues": [{"line": 0, "severity": "BLOCKER", "msg": "no rule text provided"}],
            "summary": "1 blockers, 0 warnings, 0 info",
        }

    lines = rule.splitlines()
    issues: List[Dict[str, Any]] = []

    def add(line: int, severity: str, msg: str) -> None:
        issues.append({"line": line, "severity": severity, "msg": msg})

    # ── Phase 1: Structural ──────────────────────────────────────────
    structural_issues_before = len(issues)
    header_re = re.compile(r"\[\s*(MODEL|INGEST)\s*:\s*dataset\s*=", re.IGNORECASE)
    if not any(header_re.search(ln) for ln in lines):
        add(0, "BLOCKER", "missing [MODEL: dataset=...] or [INGEST: dataset=...] header")

    # MAPPED-header comment — flexible: any leading comment block that
    # mentions 'vendor' or 'pattern' counts.
    leading_comment = []
    for ln in lines:
        s = ln.strip()
        if s.startswith("//") or s.startswith("#") or s.startswith("/*") or s.startswith("*"):
            leading_comment.append(s)
        elif s == "":
            continue
        else:
            break
    leading_text = " ".join(leading_comment).lower()
    if not leading_comment:
        add(0, "WARNING", "no MAPPED-header comment block at top of rule")
    elif not any(k in leading_text for k in ("vendor", "pattern", "mapped")):
        add(0, "INFO", "leading comment doesn't look like a MAPPED-header (no vendor/pattern keys)")

    for opener, closer, name in [
        ("(", ")", "parens"),
        ("[", "]", "brackets"),
        ("{", "}", "braces"),
    ]:
        bal = _balanced(rule, opener, closer)
        if bal != 0:
            add(
                0,
                "BLOCKER",
                f"unbalanced {name}: depth {bal:+d} at end of rule",
            )

    structural_pass = len(issues) == structural_issues_before

    # ── Phase 2: Schema discipline ───────────────────────────────────
    schema_issues_before = len(issues)
    assignments = _scan_xdm_paths(rule)
    seen: Dict[str, int] = {}
    for idx, ln in enumerate(lines, start=1):
        for m in re.finditer(r"\b(xdm\.[A-Za-z0-9_.]+)\s*=", ln):
            path = m.group(1)
            if path in seen:
                add(
                    idx,
                    "BLOCKER",
                    f"duplicate assignment to '{path}' (first seen line {seen[path]})",
                )
            else:
                seen[path] = idx

    # Unknown namespace check.
    for idx, ln in enumerate(lines, start=1):
        for m in re.finditer(r"\b(xdm\.[A-Za-z0-9_.]+)", ln):
            path = m.group(1)
            ns_head = ".".join(path.split(".")[:2])  # 'xdm.X'
            if ns_head not in XDM_NAMESPACES:
                add(
                    idx,
                    "WARNING",
                    f"unknown XDM namespace '{ns_head}' in path '{path}' — verify against §2",
                )
                break  # one warning per line

    schema_pass = len(issues) == schema_issues_before

    # ── Phase 3: Transformation discipline ───────────────────────────
    transform_issues_before = len(issues)

    # Companion pairs: if one side is mapped and the other isn't.
    mapped_set = set(assignments)
    for a, b in COMPANION_PAIRS:
        if a in mapped_set and b not in mapped_set:
            add(
                0,
                "WARNING",
                f"companion pair: mapped '{a}' but missing '{b}' (§9.2)",
            )
        elif b in mapped_set and a not in mapped_set:
            add(
                0,
                "WARNING",
                f"companion pair: mapped '{b}' but missing '{a}' (§9.2)",
            )

    # MITRE arraymap double-wrap detection.
    if re.search(r"arraycreate\s*\(\s*arraymap\b", rule):
        add(
            0,
            "BLOCKER",
            "MITRE mapping double-wrapped: arraycreate(arraymap(...)) — use arraymap directly (§9.8)",
        )

    # ipv4_addresses / mac_addresses bare-scalar detection.
    for idx, ln in enumerate(lines, start=1):
        m = re.search(
            r"(xdm\.[A-Za-z0-9_.]+\.(?:ipv4_addresses|mac_addresses))\s*=\s*([^,;]+)",
            ln,
        )
        if m and "arraycreate" not in m.group(2):
            add(
                idx,
                "WARNING",
                f"array field '{m.group(1)}' assigned a bare scalar — wrap with arraycreate() (§9.3)",
            )

    transform_pass = len(issues) == transform_issues_before

    # ── Verdict ──────────────────────────────────────────────────────
    blockers = sum(1 for i in issues if i["severity"] == "BLOCKER")
    warnings = sum(1 for i in issues if i["severity"] == "WARNING")
    info = sum(1 for i in issues if i["severity"] == "INFO")

    if blockers > 0:
        verdict = "REWRITE-RECOMMENDED" if blockers >= 3 else "NEEDS-FIXES"
    elif warnings > 0:
        verdict = "NEEDS-FIXES"
    else:
        verdict = "READY-TO-DEPLOY"

    return {
        "verdict": verdict,
        "phases": {
            "structural": {"pass": structural_pass, "issues": []},
            "schema": {"pass": schema_pass, "issues": []},
            "transform": {"pass": transform_pass, "issues": []},
        },
        "issues": issues,
        "summary": f"{blockers} blockers, {warnings} warnings, {info} info",
    }
