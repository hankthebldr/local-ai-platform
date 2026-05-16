# SPDX-FileCopyrightText: ohno llc
# SPDX-License-Identifier: AGPL-3.0-or-later
"""
VALIDATION_RULES — Port of `validationRules` from server/data/rules-engine.ts.

Each rule preserves the original ID, name, severity, category, message,
recommendation, codeSnippet, and appliesTo verbatim. Pattern/antiPattern
regexes are translated from JS to Python; customCheck callables are
re-implemented in Python.

PORT STATUS (2026-05-15):
  - Phase 3a (this file, initial commit): foundation rules covering the
    parser-conformance gate that workflows actually call out to. The
    remaining ~70 rules are tracked in the issue list under
    docs/plans/2026-05-15-gocortex-xql-ide-integration.md.

  - Phase 3b (next): port the remaining ERR / WARN / INFO / SUG rules
    and the per-rule pytest fixtures.

Derived from gocortex-xql-ide/server/data/rules-engine.ts (AGPL-3.0).
"""
from __future__ import annotations

import re
from typing import List

from ._schema import KNOWN_XDM_CATEGORIES, known_xdm_paths, known_xql_functions
from ._types import ValidationRule, Violation


# ── ERR-001 — Missing vendor field ─────────────────────────────────────
_ERR_001 = ValidationRule(
    id="ERR-001",
    name="Missing vendor field",
    severity="error",
    category="Required Fields",
    pattern=re.compile(r"\[INGEST:", re.IGNORECASE),
    antiPattern=re.compile(r"vendor\s*=", re.IGNORECASE),
    message="Parsing rule is missing the required vendor= field",
    recommendation='Add vendor="YOUR_VENDOR" to the INGEST declaration',
    codeSnippet='vendor="VENDOR_NAME"',
    appliesTo="parsing",
)


# ── ERR-002 — Missing product field ────────────────────────────────────
_ERR_002 = ValidationRule(
    id="ERR-002",
    name="Missing product field",
    severity="error",
    category="Required Fields",
    pattern=re.compile(r"\[INGEST:", re.IGNORECASE),
    antiPattern=re.compile(r"product\s*=", re.IGNORECASE),
    message="Parsing rule is missing the required product= field",
    recommendation='Add product="YOUR_PRODUCT" to the INGEST declaration',
    codeSnippet='product="PRODUCT_NAME"',
    appliesTo="parsing",
)


# ── ERR-003 — Missing target dataset ───────────────────────────────────
_ERR_003 = ValidationRule(
    id="ERR-003",
    name="Missing target dataset",
    severity="error",
    category="Required Fields",
    pattern=re.compile(r"\[INGEST:", re.IGNORECASE),
    antiPattern=re.compile(r"target_dataset\s*=", re.IGNORECASE),
    message="Parsing rule is missing the required target_dataset= field",
    recommendation='Add target_dataset="vendor_product_raw" to the INGEST declaration',
    codeSnippet='target_dataset="VENDOR_PRODUCT_raw"',
    appliesTo="parsing",
)


# ── ERR-004 — Missing dataset in model rule ────────────────────────────
_ERR_004 = ValidationRule(
    id="ERR-004",
    name="Missing dataset in model rule",
    severity="error",
    category="Required Fields",
    pattern=re.compile(r"\[MODEL:", re.IGNORECASE),
    antiPattern=re.compile(r"dataset\s*=", re.IGNORECASE),
    message="Data model rule is missing the required dataset= field",
    recommendation="Add dataset=vendor_product_raw to the MODEL declaration",
    codeSnippet="dataset=VENDOR_PRODUCT_raw",
    appliesTo="modeling",
)


# ── ERR-005 — Missing timestamp handling ───────────────────────────────
_ERR_005 = ValidationRule(
    id="ERR-005",
    name="Missing timestamp handling",
    severity="error",
    category="Required Fields",
    pattern=re.compile(r"\[INGEST:", re.IGNORECASE),
    antiPattern=re.compile(r"_time\s*=", re.IGNORECASE),
    message="Parsing rule does not set _time (timestamp). Events without timestamps cannot be properly indexed",
    recommendation="Add _time assignment using to_timestamp() or timestamp_seconds()",
    codeSnippet='_time = to_timestamp(timestamp_str, "%Y-%m-%dT%H:%M:%S")',
    appliesTo="parsing",
)


# ── ERR-006 — Invalid XDM category (customCheck) ───────────────────────
_XDM_CAT_RE = re.compile(r"xdm\.(\w+)\.(\w+)")


def _err_006_check(code: str, lines: List[str]) -> List[Violation]:
    violations: List[Violation] = []
    seen: set[str] = set()
    valid_list = ", ".join(sorted(KNOWN_XDM_CATEGORIES))
    for i, line in enumerate(lines):
        trimmed = line.lstrip()
        if trimmed.startswith("//"):
            continue
        code_part = line.split("//", 1)[0]
        for m in _XDM_CAT_RE.finditer(code_part):
            category = m.group(1)
            if category in KNOWN_XDM_CATEGORIES or category in seen:
                continue
            seen.add(category)
            violations.append(Violation(
                ruleId="ERR-006",
                ruleName="Invalid XDM category",
                severity="error",
                category="XDM Validation",
                message=f'Unknown XDM category "xdm.{category}". Valid categories: {valid_list}',
                recommendation="Check the XDM category spelling and use a valid top-level category",
                line=i + 1,
            ))
    return violations


_ERR_006 = ValidationRule(
    id="ERR-006",
    name="Invalid XDM category",
    severity="error",
    category="XDM Validation",
    pattern=re.compile(r"xdm\.\w+"),
    message="XDM field uses an unknown top-level category",
    recommendation=(
        f"Use one of the {len(KNOWN_XDM_CATEGORIES)} valid XDM categories: "
        f"{', '.join(sorted(KNOWN_XDM_CATEGORIES))}"
    ),
    appliesTo="modeling",
    customCheck=_err_006_check,
)


# ── ERR-007 — Unknown XQL function (customCheck) ───────────────────────
_FUNC_CALL_RE = re.compile(r"(?<![.\w\"'`])([a-z][a-z0-9_]*)\s*\(")
# Locally-defined non-function tokens that should never be flagged.
_FUNC_KEYWORDS = frozenset({
    "filter", "alter", "comp", "fields", "sort", "limit", "join",
    "iterate", "config", "case_sensitive", "true", "false", "null",
    "and", "or", "not", "in", "between", "is", "asc", "desc",
    "by", "as", "if", "then", "else",
})


def _err_007_check(code: str, lines: List[str]) -> List[Violation]:
    violations: List[Violation] = []
    seen: set[str] = set()
    known_funcs = known_xql_functions()
    for i, line in enumerate(lines):
        trimmed = line.lstrip()
        if trimmed.startswith("//") or trimmed.startswith("*") or trimmed.startswith("#"):
            continue
        cleaned = line.split("//", 1)[0]
        # Strip string literals so we don't flag inner function-call-like names
        cleaned = re.sub(r'"[^"]*"', '""', cleaned)
        cleaned = re.sub(r"'[^']*'", "''", cleaned)
        for m in _FUNC_CALL_RE.finditer(cleaned):
            fname = m.group(1)
            if fname in known_funcs or fname in _FUNC_KEYWORDS or fname in seen:
                continue
            seen.add(fname)
            violations.append(Violation(
                ruleId="ERR-007",
                ruleName="Unknown XQL function",
                severity="error",
                category="XQL Validation",
                message=f'Unknown XQL function "{fname}()". Check the XQL function reference',
                recommendation="Check the function name against the XQL function reference, or wrap in a valid XQL function",
                line=i + 1,
            ))
    return violations


_ERR_007 = ValidationRule(
    id="ERR-007",
    name="Unknown XQL function",
    severity="error",
    category="XQL Validation",
    pattern=re.compile(r"\w+\s*\("),
    message="Unknown XQL function call detected",
    recommendation="Check the function name against the XQL function reference",
    appliesTo="both",
    customCheck=_err_007_check,
)


# ── ERR-016 — Invented xdm.event.start_time / xdm.event.end_time path ─
# These two paths famously don't exist in XDM. Cortex sets _time
# automatically; folding start/end into xdm.event.duration via subtract()
# is the canonical pattern.
_START_END_RE = re.compile(r"xdm\.event\.(start_time|end_time)\s*=")


def _err_016_check(code: str, lines: List[str]) -> List[Violation]:
    violations: List[Violation] = []
    for i, line in enumerate(lines):
        trimmed = line.lstrip()
        if trimmed.startswith("//"):
            continue
        code_part = line.split("//", 1)[0]
        m = _START_END_RE.search(code_part)
        if not m:
            continue
        violations.append(Violation(
            ruleId="ERR-016",
            ruleName="Invented xdm.event.start_time / xdm.event.end_time path",
            severity="error",
            category="Cortex Parser Conformance",
            message=(
                f"xdm.event.{m.group(1)} does not exist in the XDM schema. "
                "Cortex rejects this with 'unknown field'"
            ),
            recommendation=(
                "Fold start/end millisecond pairs into xdm.event.duration via "
                "subtract(): xdm.event.duration = to_integer(subtract(_end_ms, _start_ms)). "
                "Cortex sets _time automatically -- there is no separate XDM start/end pair"
            ),
            codeSnippet=(
                "xdm.event.duration = to_integer(subtract(to_number(_end_ms), to_number(_start_ms)))"
            ),
            line=i + 1,
        ))
    return violations


_ERR_016 = ValidationRule(
    id="ERR-016",
    name="Invented xdm.event.start_time / xdm.event.end_time path",
    severity="error",
    category="Cortex Parser Conformance",
    pattern=_START_END_RE,
    message="xdm.event.start_time and xdm.event.end_time do NOT exist in the XDM schema",
    recommendation=(
        "Fold start/end millisecond pairs into xdm.event.duration via subtract(). "
        "Cortex sets _time automatically -- there is no separate XDM start/end pair"
    ),
    codeSnippet=(
        "xdm.event.duration = to_integer(subtract(to_number(_end_ms), to_number(_start_ms)))"
    ),
    appliesTo="modeling",
    customCheck=_err_016_check,
)


# ── ERR-020 — Invented xdm.* assignment target ─────────────────────────
# Strict exact-leaf match against KNOWN_XDM_PATHS. We deliberately do NOT
# use is_valid_xdm_path() here because the schema includes broad parent
# placeholders (e.g. xdm.event, xdm.source) that would let invented
# descendants pass a prefix check. Mirrors rules-engine.ts ERR-020
# (line 3388).
_LHS_RE = re.compile(r"^\s*(xdm\.[\w.]+)\s*=")


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    v0 = list(range(len(b) + 1))
    v1 = [0] * (len(b) + 1)
    for i, ca in enumerate(a):
        v1[0] = i + 1
        for j, cb in enumerate(b):
            cost = 0 if ca == cb else 1
            v1[j + 1] = min(v1[j] + 1, v0[j + 1] + 1, v0[j] + cost)
        v0[:] = v1[:]
    return v0[len(b)]


def _err_020_check(code: str, lines: List[str]) -> List[Violation]:
    violations: List[Violation] = []
    seen: set[str] = set()
    allow = known_xdm_paths()
    allow_list = list(allow)
    for i, line in enumerate(lines):
        trimmed = line.lstrip()
        if trimmed.startswith("//"):
            continue
        code_part = line.split("//", 1)[0]
        m = _LHS_RE.match(code_part)
        if not m:
            continue
        path = m.group(1)
        if path in seen:
            continue
        seen.add(path)
        if path in allow:  # strict exact-match
            continue
        # Top-3 closest matches by Levenshtein distance.
        scored = sorted(allow_list, key=lambda p: _levenshtein(path, p))[:3]
        hint = f" Closest matches: {', '.join(scored)}" if scored else ""
        violations.append(Violation(
            ruleId="ERR-020",
            ruleName="Invented xdm.* assignment target",
            severity="error",
            category="Cortex Parser Conformance",
            message=(
                f"'{path}' is not a known XDM field. "
                f"Cortex rejects assignments to invented paths.{hint}"
            ),
            recommendation=(
                "Use the XDM schema browser to find the correct field path, "
                "or pick the closest semantic match from the suggestions above"
            ),
            line=i + 1,
        ))
    return violations


_ERR_020 = ValidationRule(
    id="ERR-020",
    name="Invented xdm.* assignment target (not in XDM schema)",
    severity="error",
    category="Cortex Parser Conformance",
    pattern=re.compile(r"^\s*xdm\.[\w.]+\s*=", re.MULTILINE),
    message=(
        "An xdm.* path used as an assignment target does not exist in the XDM schema. "
        "Cortex rejects assignments to invented field paths"
    ),
    recommendation=(
        "Use a real XDM field. Open the XDM schema browser to find the closest "
        "matching field, or pick a different field that captures the same semantic"
    ),
    appliesTo="modeling",
    customCheck=_err_020_check,
)


# ── Registry ───────────────────────────────────────────────────────────
# Order matters for cascade suppression: keep in source-file order.
VALIDATION_RULES: List[ValidationRule] = [
    _ERR_001, _ERR_002, _ERR_003, _ERR_004, _ERR_005,
    _ERR_006, _ERR_007, _ERR_016, _ERR_020,
    # TODO Phase 3b: port remaining ~75 rules from
    # gocortex-xql-ide/server/data/rules-engine.ts:
    #   ERR-008..ERR-015, ERR-017..ERR-019, ERR-021..ERR-026 (15 rules)
    #   WARN-001..WARN-036 (34 rules)
    #   INFO-001..INFO-011 (11 rules; INFO-012 emitted by engine, not registered)
    #   SUG-001..SUG-018  (14 rules)
]
