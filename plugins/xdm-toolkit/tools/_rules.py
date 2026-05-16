# SPDX-FileCopyrightText: ohno llc
# SPDX-License-Identifier: AGPL-3.0-or-later
"""
VALIDATION_RULES — Port of `validationRules` from server/data/rules-engine.ts.

Each rule preserves the original ID, name, severity, category, message,
recommendation, codeSnippet, and appliesTo verbatim. Pattern/antiPattern
regexes are translated from JS to Python; customCheck callables are
re-implemented in Python.

PORT STATUS (2026-05-16):
  - Phase 3a (initial): foundation rules covering parser-conformance gate.
  - Phase 3b (this commit): remaining ~75 rules + scaffold engine.

Derived from gocortex-xql-ide/server/data/rules-engine.ts (AGPL-3.0).
"""
from __future__ import annotations

import re
from typing import List

from ._dataflow import (
    ARRAY_PRODUCING_FNS,
    StageStatement,
    analyse_dataflow,
    as_string_literal,
    collect_stage_statements,
    infer_scalar_base,
    line_at,
    rhs_is_array_typed,
    scalar_bases_compatible,
    split_assignment,
    split_top_level_args,
)
from ._schema import (
    KNOWN_XDM_CATEGORIES,
    array_xdm_paths,
    get_xdm_field_enum,
    get_xdm_field_type,
    is_valid_xdm_path,
    known_xdm_paths,
    known_xql_functions,
    known_xql_stages,
    xdm_const_paths,
)
from ._types import ValidationRule, Violation


# ─────────────────────────────────────────────────────────────────────
# ERR-001..ERR-005 — required fields (parsing/modeling)
# ─────────────────────────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────────────────────────
# ERR-006 — invalid XDM category
# ─────────────────────────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────────────────────────
# ERR-007 — unknown XQL function
# ─────────────────────────────────────────────────────────────────────

_FUNC_CALL_RE = re.compile(r"(?<![.\w\"'`])([a-z][a-z0-9_]*)\s*\(")
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


# ─────────────────────────────────────────────────────────────────────
# WARN-001..WARN-010 (with custom WARN-010)
# ─────────────────────────────────────────────────────────────────────

_WARN_001 = ValidationRule(
    id="WARN-001",
    name="Overly broad regex pattern",
    severity="warning",
    category="Performance",
    pattern=re.compile(r'regextract\([^)]*"\.\*"'),
    message="Using .* in regextract can be inefficient and may match unintended content",
    recommendation="Use a more specific regex pattern to improve performance and accuracy",
    appliesTo="both",
)

_WARN_002 = ValidationRule(
    id="WARN-002",
    name="Possible missing null check",
    severity="warning",
    category="Data Quality",
    pattern=re.compile(r"xdm\.\w+[\w.]*\s*=\s*(?!coalesce|if\()\w+(?!\s*!=\s*null)"),
    antiPattern=re.compile(r"coalesce|!= null"),
    message="XDM field assignment without null check. If the source field is null, the XDM field will also be null",
    recommendation="Consider wrapping in coalesce() or adding a null check with if()",
    codeSnippet='xdm.field = coalesce(raw_field, "default_value")',
    appliesTo="modeling",
)

_WARN_003 = ValidationRule(
    id="WARN-003",
    name="Parsing rule used for field mapping",
    severity="warning",
    category="Best Practices",
    pattern=re.compile(r"\[INGEST:[\s\S]*xdm\."),
    message="Parsing rules should not map to XDM fields. XDM mapping belongs in data model rules",
    recommendation="Move XDM field assignments to a separate [MODEL:] data model rule",
    appliesTo="parsing",
)

_WARN_004 = ValidationRule(
    id="WARN-004",
    name="Hardcoded IP address",
    severity="warning",
    category="Best Practices",
    pattern=re.compile(r'(?:filter|alter).*"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}"'),
    message="Hardcoded IP address detected. This reduces rule portability",
    recommendation="Consider using incidr() for IP range checks or variables for specific IPs",
    appliesTo="both",
)

_WARN_005 = ValidationRule(
    id="WARN-005",
    name="Using json_extract for scalar values",
    severity="warning",
    category="Performance",
    pattern=re.compile(r"json_extract\s*\("),
    antiPattern=re.compile(r"json_extract_scalar|json_extract_array"),
    message="json_extract returns an object. For single values, use json_extract_scalar instead",
    recommendation="Replace json_extract() with json_extract_scalar() when extracting single values",
    codeSnippet='json_extract_scalar(field, "$.path")',
    appliesTo="both",
)

# WARN-006 uses variable-width lookbehind, which Python re cannot do. Use simpler
# pattern with manual prefix-check via the standard alternation; lookbehind in
# original is (?<![a-zA-Z0-9_]) — fixed-width 1, so this works in re.
_WARN_006 = ValidationRule(
    id="WARN-006",
    name="XQL schema fields in data model rules should be mapped to XDM",
    severity="warning",
    category="Best Practices",
    pattern=re.compile(
        r"\[MODEL:[\s\S]*(?<![a-zA-Z0-9_])"
        r"(?:action_local_ip|action_remote_ip|actor_process_image_name|"
        r"actor_primary_username|action_file_path|action_protocol|"
        r"agent_hostname|event_timestamp|action_total_upload|"
        r"action_total_download)\b"
    ),
    antiPattern=re.compile(
        r"xdm\.\w+[\w.]*\s*=\s*"
        r"(?:action_local_ip|action_remote_ip|actor_process_image_name|"
        r"actor_primary_username|action_file_path|action_protocol|"
        r"agent_hostname|event_timestamp)"
    ),
    message="XQL schema fields found in data model rule but not mapped to XDM. Raw xdr_data fields should be assigned to their corresponding xdm.* paths",
    recommendation="Map XQL schema fields to XDM equivalents (e.g. action_local_ip -> xdm.source.ipv4, actor_process_image_name -> xdm.source.process.name)",
    codeSnippet='xdm.source.ipv4 = action_local_ip,\nxdm.source.process.name = actor_process_image_name',
    appliesTo="modeling",
)

_WARN_007 = ValidationRule(
    id="WARN-007",
    name="Missing xdm.observer.product mapping",
    severity="warning",
    category="Data Quality",
    pattern=re.compile(r"\[MODEL:"),
    antiPattern=re.compile(r"xdm\.observer\.product\s*="),
    message="Data model rule does not set xdm.observer.product. This field is required for proper SIEM normalisation and correlation",
    recommendation="Add xdm.observer.product = product (or a literal string) to identify the source product",
    codeSnippet='xdm.observer.product = product',
    appliesTo="modeling",
)

_WARN_008 = ValidationRule(
    id="WARN-008",
    name="Missing fields cleanup for tmp_ variables",
    severity="warning",
    category="Best Practices",
    pattern=re.compile(r"\btmp_\w+"),
    antiPattern=re.compile(r"fields\s+-\s*tmp"),
    message="Temporary variables (tmp_*) are used but not cleaned up with a fields - tmp* statement",
    recommendation="Add | fields -tmp* at the end of your rule to remove temporary variables from the output",
    codeSnippet="| fields -tmp*",
    appliesTo="both",
)

_WARN_009 = ValidationRule(
    id="WARN-009",
    name="Missing no_hit directive",
    severity="warning",
    category="Best Practices",
    pattern=re.compile(r"\[INGEST:"),
    antiPattern=re.compile(r"no_hit\s*=\s*(?:drop|keep)", re.IGNORECASE),
    message="Parsing rule does not specify a no_hit directive. Events that do not match any filter will pass through unprocessed",
    recommendation="Add no_hit=drop (to discard unmatched events) or no_hit=keep (to pass them through) to the INGEST declaration",
    codeSnippet='[INGEST:vendor="V", product="P", target_dataset="ds", no_hit=drop]',
    appliesTo="parsing",
)


# WARN-010 — Unresolved XDM field path (customCheck)
_WARN_010_FIELD_RE = re.compile(r"\b(xdm\.[\w.]+)")


def _warn_010_check(code: str, lines: List[str]) -> List[Violation]:
    violations: List[Violation] = []
    seen: set[str] = set()
    for i, line in enumerate(lines):
        trimmed = line.lstrip()
        if trimmed.startswith("//"):
            continue
        target = line
        if '"' in line:
            target = re.sub(r'"[^"]*"', '""', line)
        for m in _WARN_010_FIELD_RE.finditer(target):
            field_path = m.group(1).rstrip(".")
            if field_path.count(".") < 2:
                continue
            if field_path in seen:
                continue
            if is_valid_xdm_path(field_path):
                continue
            seen.add(field_path)
            violations.append(Violation(
                ruleId="WARN-010",
                ruleName="Unresolved XDM field path",
                severity="warning",
                category="XDM Validation",
                message=f'XDM field path "{field_path}" does not match any known field in the schema (645 fields)',
                recommendation="Check the field path spelling against the XDM schema browser or add the field to the schema if it is a newly documented field",
                line=i + 1,
            ))
    return violations


_WARN_010 = ValidationRule(
    id="WARN-010",
    name="Unresolved XDM field path",
    severity="warning",
    category="XDM Validation",
    pattern=re.compile(r"xdm\.\w+\.\w+"),
    message="XDM field path does not match any known field in the XDM schema",
    recommendation="Check the field path spelling against the XDM schema browser",
    appliesTo="modeling",
    customCheck=_warn_010_check,
)


_WARN_011 = ValidationRule(
    id="WARN-011",
    name="Missing xdm.observer.vendor mapping",
    severity="warning",
    category="Data Quality",
    pattern=re.compile(r"\[MODEL:"),
    antiPattern=re.compile(r"xdm\.observer\.vendor\s*="),
    message="Data model rule does not set xdm.observer.vendor. This field identifies the vendor of the observing product",
    recommendation='Add xdm.observer.vendor = "VENDOR_NAME" to the data model rule',
    codeSnippet='xdm.observer.vendor = "Palo Alto Networks"',
    appliesTo="modeling",
)


# ─────────────────────────────────────────────────────────────────────
# INFO-001..INFO-006
# ─────────────────────────────────────────────────────────────────────

_INFO_001 = ValidationRule(
    id="INFO-001",
    name="Consider coalesce for fallback values",
    severity="info",
    category="Best Practices",
    pattern=re.compile(r"if\s*\(\s*\w+\s*!=\s*null\s*,\s*\w+\s*,"),
    message="Pattern matches a common null-check that could be simplified with coalesce()",
    recommendation="Use coalesce(field, fallback) instead of if(field != null, field, fallback)",
    codeSnippet="coalesce(field, fallback_value)",
    appliesTo="both",
)

_INFO_002 = ValidationRule(
    id="INFO-002",
    name="Event type not set",
    severity="info",
    category="Data Quality",
    pattern=re.compile(r"\[MODEL:"),
    antiPattern=re.compile(r"xdm\.event\.type\s*="),
    message="Data model rule does not set xdm.event.type. Setting event type improves analytics and correlation",
    recommendation='Add xdm.event.type = "NETWORK" (or AUTH, FILE, PROCESS, etc.)',
    codeSnippet='xdm.event.type = "NETWORK"',
    appliesTo="modeling",
)

_INFO_003 = ValidationRule(
    id="INFO-003",
    name="Event outcome not set",
    severity="info",
    category="Data Quality",
    pattern=re.compile(r"\[MODEL:"),
    antiPattern=re.compile(r"xdm\.event\.outcome\s*="),
    message="Data model rule does not set xdm.event.outcome. This field is important for success/failure analysis",
    recommendation='Add xdm.event.outcome using if() to map vendor action to SUCCESS/FAILURE',
    codeSnippet='xdm.event.outcome = if(action = "allow", "SUCCESS", "FAILURE")',
    appliesTo="modeling",
)

_INFO_004 = ValidationRule(
    id="INFO-004",
    name="Missing event description",
    severity="info",
    category="Data Quality",
    pattern=re.compile(r"\[MODEL:"),
    antiPattern=re.compile(r"xdm\.event\.description\s*="),
    message="Data model rule does not set xdm.event.description. Adding a description improves log readability in XSIAM",
    recommendation="Add xdm.event.description using concat() or format_string() to build a human-readable summary",
    codeSnippet='xdm.event.description = concat("User ", username, " performed ", action)',
    appliesTo="modeling",
)

_INFO_005 = ValidationRule(
    id="INFO-005",
    name="Consider format_timestamp for year in RFC 3164",
    severity="info",
    category="Best Practices",
    pattern=re.compile(
        r"(?:%b\s+%d\s+%H:%M:%S|%h\s+%d\s+%H:%M:%S|syslog_header)",
        re.IGNORECASE,
    ),
    antiPattern=re.compile(r"format_timestamp|%Y"),
    message="RFC 3164 (syslog) timestamps do not include the year. Events may be assigned to the wrong year at year boundaries",
    recommendation="Use format_timestamp() to prepend the current year, or parse with %E*S if the source includes epoch precision",
    codeSnippet='timestamp_str = concat(format_timestamp("%Y ", current_time()), raw_timestamp)',
    appliesTo="parsing",
)

_INFO_006 = ValidationRule(
    id="INFO-006",
    name="Missing fields cleanup",
    severity="info",
    category="Best Practices",
    pattern=re.compile(r"\|\s*alter\b[\s\S]*\w+\s*=\s*"),
    antiPattern=re.compile(r"\|\s*fields\s+-"),
    message="Rule uses alter to create intermediary fields but does not include a fields - statement to clean up unused variables",
    recommendation="Add | fields - <intermediary_fields> at the end to remove fields that are not needed in the final output",
    codeSnippet="| fields -tmp_field1, tmp_field2",
    appliesTo="both",
)


# ─────────────────────────────────────────────────────────────────────
# SUG-001..SUG-010
# ─────────────────────────────────────────────────────────────────────

_SUG_001 = ValidationRule(
    id="SUG-001",
    name="Use incidr() for IP range checks",
    severity="suggestion",
    category="Best Practices",
    pattern=re.compile(r'~=\s*"[\d\\.\*]+"'),
    message="Regex-based IP matching detected. incidr() is more efficient and accurate for IP range checks",
    recommendation='Replace regex IP matching with incidr(ip_field, "cidr_range")',
    codeSnippet='incidr(src_ip, "10.0.0.0/8")',
    appliesTo="both",
)

_SUG_002 = ValidationRule(
    id="SUG-002",
    name="Field naming convention",
    severity="suggestion",
    category="Best Practices",
    pattern=re.compile(r"alter\s+\w*[A-Z]\w*\s*="),
    message="Field names should use snake_case (lowercase with underscores) for consistency",
    recommendation="Rename fields to use snake_case: myField becomes my_field",
    appliesTo="both",
)

_SUG_003 = ValidationRule(
    id="SUG-003",
    name="Consider lowercase() for case-insensitive matching",
    severity="suggestion",
    category="Best Practices",
    pattern=re.compile(r'filter\s+\w+\s*(?:=|contains)\s*"[^"]*[A-Z][^"]*"'),
    message="String comparison with mixed-case value. Consider normalising with lowercase() for case-insensitive matching",
    recommendation='Use lowercase(field) = "value" for case-insensitive comparisons',
    codeSnippet='filter lowercase(action) = "allow"',
    appliesTo="both",
)

_SUG_004 = ValidationRule(
    id="SUG-004",
    name="Use XDM_CONST for standardised values",
    severity="suggestion",
    category="Best Practices",
    pattern=re.compile(
        r'xdm\.event\.(?:type|outcome)\s*=\s*"(?:NETWORK|AUTH|FILE|PROCESS|SUCCESS|FAILURE)"'
    ),
    message="Consider using XDM_CONST enums instead of string literals for standardised XDM values. This ensures forward compatibility",
    recommendation="Replace string literals with XDM_CONST values (e.g. XDM_CONST.EVENT_TYPE_NETWORK, XDM_CONST.OUTCOME_SUCCESS)",
    codeSnippet='xdm.event.type = XDM_CONST.EVENT_TYPE_NETWORK,\nxdm.event.outcome = XDM_CONST.OUTCOME_SUCCESS',
    appliesTo="modeling",
)

_SUG_005 = ValidationRule(
    id="SUG-005",
    name="Consider incidr6() alongside incidr() for dual-stack",
    severity="suggestion",
    category="Best Practices",
    pattern=re.compile(r"incidr\s*\("),
    antiPattern=re.compile(r"incidr6\s*\("),
    message="Rule uses incidr() for IPv4 range checks but does not include incidr6() for IPv6. In dual-stack environments, IPv6 addresses may be missed",
    recommendation="Add incidr6() checks alongside incidr() to cover IPv6 addresses",
    codeSnippet='if(is_ipv4(ip), incidr(ip, "10.0.0.0/8"), incidr6(ip, "fd00::/8"))',
    appliesTo="both",
)

_SUG_006 = ValidationRule(
    id="SUG-006",
    name="Consider arraydistinct after arrayconcat",
    severity="suggestion",
    category="Best Practices",
    pattern=re.compile(r"arrayconcat\s*\("),
    antiPattern=re.compile(r"arraydistinct\s*\("),
    message="arrayconcat() merges arrays but may produce duplicates. Consider wrapping with arraydistinct() for unique values",
    recommendation="Wrap arrayconcat() in arraydistinct() to remove duplicate entries",
    codeSnippet="arraydistinct(arrayconcat(array1, array2))",
    appliesTo="both",
)

_SUG_007 = ValidationRule(
    id="SUG-007",
    name="Consider arraystring for array-to-string conversion",
    severity="suggestion",
    category="Best Practices",
    pattern=re.compile(r"concat\s*\([^)]*regextract"),
    message="Using concat() on regextract results may not handle arrays cleanly. Consider arraystring() for joining array elements",
    recommendation='Use arraystring(regextract(...), ", ") to cleanly join extracted array values into a string',
    codeSnippet='arraystring(regextract(field, "pattern"), ", ")',
    appliesTo="both",
)

_SUG_008 = ValidationRule(
    id="SUG-008",
    name="Use XDM_CONST for outcome values",
    severity="suggestion",
    category="Best Practices",
    pattern=re.compile(r'xdm\.event\.outcome\s*=\s*"(?:SUCCESS|FAILURE)"', re.IGNORECASE),
    message='String literal "SUCCESS" or "FAILURE" used for xdm.event.outcome. Consider using XDM_CONST for standardised values',
    recommendation="Replace with XDM_CONST.OUTCOME_SUCCESS or XDM_CONST.OUTCOME_FAILURE",
    codeSnippet='xdm.event.outcome = XDM_CONST.OUTCOME_SUCCESS',
    appliesTo="modeling",
)

_SUG_009 = ValidationRule(
    id="SUG-009",
    name="Consider %E*S for variable timestamp precision",
    severity="suggestion",
    category="Best Practices",
    pattern=re.compile(r"%E[0-9]S"),
    antiPattern=re.compile(r"%E\*S"),
    message="Fixed-precision timestamp format (e.g. %E3S, %E6S) used. If the source sends variable precision, %E*S handles any sub-second length",
    recommendation="Replace %E3S or %E6S with %E*S to handle variable sub-second precision automatically",
    codeSnippet='to_timestamp(ts, "%Y-%m-%dT%H:%M:%E*S")',
    appliesTo="parsing",
)

_SUG_010 = ValidationRule(
    id="SUG-010",
    name="Consecutive alter stages could be combined",
    severity="suggestion",
    category="Performance",
    pattern=re.compile(r"\|\s*alter\b[^\n]*\n\s*\|\s*alter\b"),
    message="Multiple consecutive | alter stages detected. These can often be combined into a single alter stage for better readability",
    recommendation="Combine consecutive alter stages into one using comma-separated assignments",
    codeSnippet="| alter\n    field1 = value1,\n    field2 = value2",
    appliesTo="both",
)


# ─────────────────────────────────────────────────────────────────────
# WARN-012..WARN-015 — mode/syntax
# ─────────────────────────────────────────────────────────────────────

_WARN_012 = ValidationRule(
    id="WARN-012",
    name="MODEL block in parsing mode",
    severity="warning",
    category="Mode Mismatch",
    pattern=re.compile(r"\[MODEL:", re.IGNORECASE),
    message="A [MODEL:] block was found but the current mode is Parsing Rule. Data model rules use [MODEL:] blocks; parsing rules use [INGEST:] blocks",
    recommendation="Switch to Data Model Rule mode using the footer toggle, or replace [MODEL:] with [INGEST:] if you intended to write a parsing rule",
    appliesTo="parsing",
)

_WARN_013 = ValidationRule(
    id="WARN-013",
    name="INGEST block in data model mode",
    severity="warning",
    category="Mode Mismatch",
    pattern=re.compile(r"\[INGEST:", re.IGNORECASE),
    message="An [INGEST:] block was found but the current mode is Data Model Rule. Parsing rules use [INGEST:] blocks; data model rules use [MODEL:] blocks",
    recommendation="Switch to Parsing Rule mode using the footer toggle, or replace [INGEST:] with [MODEL:] if you intended to write a data model rule",
    appliesTo="modeling",
)

_WARN_014 = ValidationRule(
    id="WARN-014",
    name="Quoted XDM_CONST value",
    severity="warning",
    category="Syntax",
    pattern=re.compile(r'"XDM_CONST\.'),
    message="XDM_CONST values must not be enclosed in quotes. They are enum constants, not string literals",
    recommendation='Remove the surrounding quotes (e.g. XDM_CONST.OUTCOME_SUCCESS not "XDM_CONST.OUTCOME_SUCCESS")',
    codeSnippet='xdm.event.outcome = XDM_CONST.OUTCOME_SUCCESS',
    appliesTo="modeling",
)

_WARN_015 = ValidationRule(
    id="WARN-015",
    name="Quoted dataset name in MODEL block declaration",
    severity="warning",
    category="Syntax",
    pattern=re.compile(r'\[MODEL:[^\]]*dataset\s*=\s*"[^"]*"', re.IGNORECASE),
    message="Dataset names should not be enclosed in quotes in MODEL block declarations. Note: INGEST rules correctly use quoted values",
    recommendation='Use [MODEL: dataset=name_raw] instead of [MODEL: dataset="name_raw"]. This does not apply to INGEST rules where quoting is correct',
    codeSnippet="[MODEL: dataset=vendor_product_raw]",
    appliesTo="modeling",
)


# ─────────────────────────────────────────────────────────────────────
# INFO-007 — unused temporary field
# ─────────────────────────────────────────────────────────────────────

def _info_007_check(code: str, lines: List[str]) -> List[Violation]:
    violations: List[Violation] = []
    flow = analyse_dataflow(code, lines)

    # Detect parser (INGEST) rule context with comment stripping.
    code_for_opener = ""
    for raw in lines:
        trimmed = raw.lstrip()
        if trimmed.startswith("//"):
            continue
        code_for_opener += raw.split("//", 1)[0] + "\n"
    is_parser = bool(re.search(r"^\s*\[INGEST:", code_for_opener, re.IGNORECASE | re.MULTILINE))

    # Pre-compute per-line code parts + def-range map only in parser mode.
    code_parts: List[str] = []
    def_ranges: dict[int, tuple[int, int]] = {}
    if is_parser:
        code_parts = [
            "" if raw.lstrip().startswith("//") else raw.split("//", 1)[0]
            for raw in lines
        ]
        def_line_set = {d.line - 1 for d in flow.defs}

        def is_stage_start(cp: str) -> bool:
            return bool(re.match(r"^\s*\|\s*\w+", cp))

        for d in flow.defs:
            start = d.line - 1
            end = len(code_parts) - 1
            for j in range(start + 1, len(code_parts)):
                cp = code_parts[j]
                if is_stage_start(cp) or j in def_line_set or re.search(r"xdm\.[\w.]+\s*=", cp):
                    end = j - 1
                    break
            def_ranges[d.line] = (start, end)

    def is_anchor_column(name: str) -> bool:
        if not is_parser:
            return False
        own_ranges = []
        for d in flow.defs:
            if d.name != name:
                continue
            r = def_ranges.get(d.line)
            if r:
                own_ranges.append(r)
        if not own_ranges:
            return False

        def is_own_line(idx: int) -> bool:
            return any(s <= idx <= e for s, e in own_ranges)

        escaped = re.escape(name)
        regex = re.compile(r"\b" + escaped + r"\b")
        for i, cp in enumerate(code_parts):
            if is_own_line(i):
                continue
            if regex.search(cp):
                return False
        return True

    seen: set[str] = set()
    for d in flow.defs:
        if not d.isUnderscore:
            continue
        if d.name in seen:
            continue
        seen.add(d.name)
        if d.name in flow.reachable:
            continue
        if is_anchor_column(d.name):
            continue
        violations.append(Violation(
            ruleId="INFO-007",
            ruleName="Unused temporary field",
            severity="info",
            category="Data Quality",
            message=f"Temporary field '{d.name}' is extracted but never assigned to an XDM field. Remove it or map it to an appropriate XDM field",
            recommendation=f"Add an XDM field assignment such as xdm.<category>.<field> = {d.name}, or remove the extraction if the field is not needed",
            line=d.line,
        ))
    return violations


_INFO_007 = ValidationRule(
    id="INFO-007",
    name="Unused temporary field",
    severity="info",
    category="Data Quality",
    pattern=re.compile(r"\b_\w+\s*="),
    message="Temporary field is extracted but never assigned to an XDM field",
    recommendation="Remove the unused temporary field or map it to an appropriate XDM field. Anchor columns stamped at ingest by an [INGEST: ...] parser rule are exempt -- see PRIVATE_DOCS/anchor_field_design.md",
    appliesTo="both",
    customCheck=_info_007_check,
)


# ─────────────────────────────────────────────────────────────────────
# ERR-008 — Invalid JSON path with @ prefix
# ─────────────────────────────────────────────────────────────────────

_ERR_008 = ValidationRule(
    id="ERR-008",
    name="Invalid JSON path with @ prefix in json_extract_scalar",
    severity="error",
    category="Syntax",
    pattern=re.compile(r'json_extract_scalar\s*\([^)]*"\$\.@'),
    antiPattern=re.compile(r"json_extract_scalar\s*\([^)]*\"\$\['"),
    message='JSON path using $.@ notation will fail at runtime. Keys containing special characters like @ must use bracket notation',
    recommendation='Use bracket notation for special-character keys: json_extract_scalar(_raw_log, "$[\'@timestamp\']") instead of json_extract_scalar(_raw_log, "$.@timestamp")',
    codeSnippet='_timestamp = json_extract_scalar(_raw_log, "$[\'@timestamp\']")',
    appliesTo="both",
)


# ─────────────────────────────────────────────────────────────────────
# WARN-016..WARN-018 — robustness / mode mismatches
# ─────────────────────────────────────────────────────────────────────

_WARN_016 = ValidationRule(
    id="WARN-016",
    name="Unguarded parse_epoch or parse_timestamp",
    severity="warning",
    category="Robustness",
    pattern=re.compile(r"(?:_time|_timestamp)\s*=\s*parse_(?:epoch|timestamp)\s*\("),
    antiPattern=re.compile(r"(?:_time|_timestamp)\s*=\s*if\s*\("),
    message="parse_epoch/parse_timestamp will throw a runtime error if the input field is null or empty. Wrap in an if() guard",
    recommendation='Use _time = if(field != null and field != "", parse_epoch(field, "MILLIS"), null) to handle missing timestamps gracefully',
    codeSnippet='_time = if(_timestamp_ms != null and _timestamp_ms != "", parse_epoch(_timestamp_ms, "MILLIS"), null)',
    appliesTo="both",
)

_WARN_017 = ValidationRule(
    id="WARN-017",
    name="Leading pipe before first stage in MODEL rule",
    severity="warning",
    category="Syntax",
    pattern=re.compile(r"\[MODEL:[^\]]*\]\s*\n\s*\|"),
    message="The first stage after a MODEL block header should not have a leading pipe character. Use 'alter' or 'filter' directly, not '| alter' or '| filter'",
    recommendation="Remove the leading | from the first stage. Write [MODEL: dataset=name_raw]\\nalter instead of [MODEL: dataset=name_raw]\\n| alter",
    codeSnippet="[MODEL: dataset=vendor_product_raw]\nalter\n    xdm.event.id = event_id;",
    appliesTo="modeling",
)

_WARN_018 = ValidationRule(
    id="WARN-018",
    name="_time assignment in data model rule",
    severity="warning",
    category="Required Fields",
    pattern=re.compile(r"(?:^|[\n,])\s*_time\s*="),
    message="_time must only be set during INGEST (parsing) rules, not in MODEL rules. The parser is responsible for setting the event timestamp",
    recommendation="Remove the _time assignment from this MODEL rule. If _time is not being set correctly, fix it in the upstream INGEST rule instead",
    codeSnippet="// Do not assign _time in MODEL rules -- it is set by the parser at INGEST time",
    appliesTo="modeling",
)


# ─────────────────────────────────────────────────────────────────────
# INFO-008, INFO-009 — empty editor (boilerplate available)
# ─────────────────────────────────────────────────────────────────────

_INFO_008 = ValidationRule(
    id="INFO-008",
    name="Empty editor -- parsing boilerplate available",
    severity="info",
    category="Getting Started",
    pattern=re.compile(r"^\s*$"),
    message='Editor is empty. Search for "Parsing Rule Boilerplate" in the Snippets panel to get started',
    recommendation='Open the Snippets panel and search for "Parsing Rule Boilerplate" to insert a ready-made INGEST rule template',
    codeSnippet='[INGEST:vendor="VENDOR", product="PRODUCT", target_dataset="vendor_product_raw", no_hit=drop]',
    appliesTo="parsing",
)

_INFO_009 = ValidationRule(
    id="INFO-009",
    name="Empty editor -- data model boilerplate available",
    severity="info",
    category="Getting Started",
    pattern=re.compile(r"^\s*$"),
    message='Editor is empty. Search for "Data Model Rule Boilerplate" in the Snippets panel to get started',
    recommendation='Open the Snippets panel and search for "Data Model Rule Boilerplate" to insert a ready-made MODEL rule template',
    codeSnippet='[MODEL: dataset=vendor_product_raw]\nalter\n    xdm.event.id = event_id;',
    appliesTo="modeling",
)


# ─────────────────────────────────────────────────────────────────────
# ERR-009 — missing terminal semicolon
# ─────────────────────────────────────────────────────────────────────

def _strip_line_comment(line: str) -> str:
    """Quote-aware // stripper."""
    in_str = False
    i = 0
    while i < len(line) - 1:
        if in_str and line[i] == "\\":
            i += 2
            continue
        if line[i] == '"':
            in_str = not in_str
            i += 1
            continue
        if not in_str and line[i] == "/" and line[i + 1] == "/":
            return line[:i]
        i += 1
    return line


def _err_009_check(code: str, lines: List[str]) -> List[Violation]:
    violations: List[Violation] = []
    headers: list[dict] = []
    for i, line in enumerate(lines):
        trimmed = line.lstrip()
        if trimmed.startswith("//"):
            continue
        kind = None
        if re.match(r"^\[MODEL:", trimmed, re.IGNORECASE):
            kind = "MODEL"
        elif re.match(r"^\[INGEST:", trimmed, re.IGNORECASE):
            kind = "INGEST"
        elif re.match(r"^\[RULE:", trimmed, re.IGNORECASE):
            kind = "RULE"
        if kind:
            headers.append({"kind": kind, "line": i + 1})

    for hi, h in enumerate(headers):
        if h["kind"] == "RULE":
            continue
        body_start = h["line"]
        body_end = len(lines)
        for nj in range(hi + 1, len(headers)):
            body_end = headers[nj]["line"] - 1
            break
        body_lines = lines[body_start:body_end]
        last_code = ""
        last_rel = -1
        for bi in range(len(body_lines) - 1, -1, -1):
            code_only = _strip_line_comment(body_lines[bi]).rstrip()
            if not code_only.strip():
                continue
            last_code = code_only
            last_rel = bi
            break
        if last_rel == -1:
            violations.append(Violation(
                ruleId="ERR-009",
                ruleName="Missing terminal semicolon",
                severity="error",
                category="Syntax",
                message=f"Rule block starting at line {h['line']} does not end with a terminal semicolon (;). The Cortex IDE will reject this rule",
                recommendation="Add a semicolon (;) at the very end of the rule block, after the last field assignment",
                codeSnippet="    xdm.event.id = event_id;",
                line=h["line"],
            ))
            continue
        if not last_code.endswith(";"):
            violations.append(Violation(
                ruleId="ERR-009",
                ruleName="Missing terminal semicolon",
                severity="error",
                category="Syntax",
                message=f"Rule block starting at line {h['line']} does not end with a terminal semicolon (;). The Cortex IDE will reject this rule",
                recommendation="Add a semicolon (;) at the very end of the rule block, after the last field assignment",
                codeSnippet="    xdm.event.id = event_id;",
                line=body_start + last_rel + 1,
            ))
    return violations


_ERR_009 = ValidationRule(
    id="ERR-009",
    name="Missing terminal semicolon",
    severity="error",
    category="Syntax",
    pattern=re.compile(r"\[(MODEL|INGEST):"),
    message="Rule block does not end with a terminal semicolon. The Cortex IDE rejects rules without a semicolon at the end",
    recommendation="Add a semicolon (;) at the very end of the rule block, after the last field assignment",
    codeSnippet="    xdm.event.id = event_id;",
    appliesTo="both",
    customCheck=_err_009_check,
)


# ─────────────────────────────────────────────────────────────────────
# ERR-010 — trailing comma on final assignment
# ─────────────────────────────────────────────────────────────────────

def _err_010_check(code: str, lines: List[str]) -> List[Violation]:
    violations: List[Violation] = []
    for m in re.finditer(r",\s*;", code):
        before = code[:m.start()]
        line_num = before.count("\n") + 1
        violations.append(Violation(
            ruleId="ERR-010",
            ruleName="Trailing comma on final assignment",
            severity="error",
            category="Syntax",
            message="Trailing comma detected before the terminal semicolon. This causes a parse error in the Cortex IDE",
            recommendation="Remove the trailing comma before the semicolon on the final assignment line",
            codeSnippet="    xdm.event.id = event_id;  // no comma before semicolon",
            line=line_num,
        ))
    return violations


_ERR_010 = ValidationRule(
    id="ERR-010",
    name="Trailing comma on final assignment",
    severity="error",
    category="Syntax",
    pattern=re.compile(r",\s*;"),
    message="Trailing comma before the terminal semicolon. The last field assignment must not have a trailing comma",
    recommendation="Remove the trailing comma before the semicolon on the final assignment line",
    codeSnippet="    xdm.event.id = event_id;  // no comma before semicolon",
    appliesTo="both",
    customCheck=_err_010_check,
)


# ─────────────────────────────────────────────────────────────────────
# WARN-019 — unused intermediary fields in data model rules
# ─────────────────────────────────────────────────────────────────────

def _warn_019_check(code: str, lines: List[str]) -> List[Violation]:
    violations: List[Violation] = []
    if not re.search(r"\[MODEL:", code):
        return violations

    field_defs: list[dict] = []
    field_def_re = re.compile(r"(?:^|,)\s*([a-zA-Z][a-zA-Z0-9_]*)\s*=", re.MULTILINE)
    keyword_blocklist = re.compile(
        r"^(alter|filter|fields|dataset|vendor|product|target_dataset|no_hit|"
        r"call|comp|sort|limit|dedup|bin|timeframe|preset|reverse|view|union|"
        r"join|namedpipe|config|stage|stage_in|arrayexpand|datamodel|and|xor)$"
    )

    all_code_parts: List[str] = []
    for line in lines:
        trimmed = line.lstrip()
        if trimmed.startswith("//"):
            all_code_parts.append("")
            continue
        all_code_parts.append(line.split("//", 1)[0])

    for i, cp in enumerate(all_code_parts):
        if not cp.strip():
            continue
        for m in field_def_re.finditer(cp):
            field_name = m.group(1)
            if field_name.startswith("xdm"):
                continue
            if field_name.startswith("tmp_"):
                continue
            if field_name.startswith("_"):
                continue
            if keyword_blocklist.match(field_name):
                continue
            field_defs.append({"name": field_name, "line": i + 1})

    if not field_defs:
        return violations

    xdm_lines: list[str] = []
    in_xdm = False
    for cp in all_code_parts:
        if re.search(r"xdm\.[\w.]+\s*=", cp):
            in_xdm = True
        elif re.match(r"^\s*\|\s*(alter|filter|fields|comp|bin|sort|dedup|limit)\b", cp) or \
                re.match(r"^\s*\[(MODEL|INGEST):", cp):
            in_xdm = False
        if in_xdm:
            xdm_lines.append(cp)
    xdm_block = "\n".join(xdm_lines)

    seen: set[str] = set()
    for d in field_defs:
        if d["name"] in seen:
            continue
        seen.add(d["name"])
        escaped = re.escape(d["name"])
        # Python doesn't support variable-width lookbehind robustly. The TS
        # version uses (?<!=\s*)\b<name>\b — to avoid match of LHS itself.
        # We do this manually: skip the def line, search xdm_block only.
        usage_re = re.compile(r"\b" + escaped + r"\b")
        if usage_re.search(xdm_block):
            continue

        # Transitive reach via other field defs' RHS.
        is_transitively_used = False
        checked: set[str] = set()
        to_check: list[str] = [d["name"]]
        while to_check:
            current = to_check.pop()
            if current in checked:
                continue
            checked.add(current)
            current_re = re.compile(r"\b" + re.escape(current) + r"\b")
            if current_re.search(xdm_block):
                is_transitively_used = True
                break
            for other in field_defs:
                if other["name"] in checked:
                    continue
                other_line = all_code_parts[other["line"] - 1] if other["line"] - 1 < len(all_code_parts) else ""
                rhs_split = re.split(r"\b\w+\s*=", other_line)
                rhs = "".join(rhs_split[1:]) if len(rhs_split) > 1 else ""
                if current_re.search(rhs):
                    to_check.append(other["name"])
        if is_transitively_used:
            continue

        violations.append(Violation(
            ruleId="WARN-019",
            ruleName="Unused intermediary fields in data model rules",
            severity="warning",
            category="Data Quality",
            message=f"Intermediary field '{d['name']}' is extracted but never referenced in any XDM field assignment. The Cortex IDE flags this as \"Data Model Rules contains unused fields\"",
            recommendation=f"Map '{d['name']}' to an appropriate XDM field (e.g. xdm.<category>.<field> = {d['name']}) or remove it if not needed",
            line=d["line"],
        ))
    return violations


_WARN_019 = ValidationRule(
    id="WARN-019",
    name="Unused intermediary fields in data model rules",
    severity="warning",
    category="Data Quality",
    pattern=re.compile(r"\[MODEL:"),
    message="Data Model Rules contains unused fields. Non-underscore intermediary fields created in alter blocks are not referenced in any XDM assignment",
    recommendation="Either map unused intermediary fields to XDM fields or remove them. The Cortex IDE flags these as 'Data Model validation error - Data Model Rules contains unused fields'",
    appliesTo="modeling",
    customCheck=_warn_019_check,
)


# ─────────────────────────────────────────────────────────────────────
# WARN-020 — string assigned to array-type XDM field
# ─────────────────────────────────────────────────────────────────────

_ARRAY_FNS_PAT = re.compile(
    r"\b(arraycreate|arrayconcat|arraydistinct|arraymap|arrayfilter|arraypop|"
    r"arrayrange|arrayresize|split|regextract|json_extract_array)\b"
)
_ARRAY_SUFFIX_PAT = re.compile(r"\[\s*\]")


def _warn_020_check(code: str, lines: List[str]) -> List[Violation]:
    violations: List[Violation] = []
    if not re.search(r"\[MODEL:", code):
        return violations
    flow = analyse_dataflow(code, lines)
    known_array_vars = flow.arrayTyped
    arr_paths = array_xdm_paths()
    for i, line in enumerate(lines):
        trimmed = line.lstrip()
        if trimmed.startswith("//"):
            continue
        code_part = trimmed.split("//", 1)[0]
        m = re.match(r"^(xdm\.[\w.]+)\s*=\s*(.+)", code_part)
        if not m:
            continue
        field_path = m.group(1)
        rhs = m.group(2)
        if field_path not in arr_paths:
            continue
        if _ARRAY_FNS_PAT.search(rhs):
            continue
        if _ARRAY_SUFFIX_PAT.search(rhs):
            continue
        if rhs_is_array_typed(rhs, known_array_vars):
            continue
        violations.append(Violation(
            ruleId="WARN-020",
            ruleName="String assigned to array-type XDM field",
            severity="warning",
            category="Data Quality",
            message=f"'{field_path}' expects an array but is being assigned a scalar value. The Cortex IDE will reject this with \"Expected array but received string\"",
            recommendation=f"Wrap the value in arraycreate() -- e.g. {field_path} = if(value != null, arraycreate(value))",
            line=i + 1,
        ))
    return violations


_WARN_020 = ValidationRule(
    id="WARN-020",
    name="String assigned to array-type XDM field",
    severity="warning",
    category="Data Quality",
    pattern=re.compile(r"xdm\.\S+\s*="),
    message="An XDM field that expects an array is being assigned a scalar value",
    recommendation="Wrap the value in arraycreate() to produce a single-element array, or use an array-producing function such as arraycreate(), arrayconcat(), split(), or regextract()",
    codeSnippet="xdm.source.user.roles = if(role != null, arraycreate(role)),",
    appliesTo="modeling",
    customCheck=_warn_020_check,
)


# ─────────────────────────────────────────────────────────────────────
# WARN-021 — XDM_CONST field assigned raw string
# ─────────────────────────────────────────────────────────────────────

def _warn_021_check(code: str, lines: List[str]) -> List[Violation]:
    violations: List[Violation] = []
    if not re.search(r"\[MODEL:", code):
        return violations
    const_paths = xdm_const_paths()
    for i, line in enumerate(lines):
        trimmed = line.lstrip()
        if trimmed.startswith("//"):
            continue
        code_part = trimmed.split("//", 1)[0]
        m = re.match(r"^(xdm\.[\w.]+)\s*=\s*(.+)", code_part)
        if not m:
            continue
        field_path = m.group(1)
        rhs = m.group(2).strip()
        const_type = const_paths.get(field_path)
        if not const_type:
            continue
        if re.search(r"\bXDM_CONST\.", rhs):
            continue
        if re.search(r"\bif\s*\(", rhs):
            continue
        if re.search(r"\bcoalesce\s*\(", rhs):
            continue
        is_quoted = bool(re.match(r'^"[^"]*"', rhs)) or bool(re.match(r"^'[^']*'", rhs))
        if is_quoted:
            violations.append(Violation(
                ruleId="WARN-021",
                ruleName="XDM_CONST field assigned raw string",
                severity="warning",
                category="Data Quality",
                message=f"'{field_path}' expects a {const_type} enumeration but is assigned a raw string literal. Use XDM_CONST.* constants instead",
                recommendation=f"Replace the string with the appropriate {const_type}_* constant (e.g. {const_type}_SUCCESS) or use an if() chain mapping raw values to XDM_CONST enums",
                codeSnippet=f"{field_path} = {const_type}_SUCCESS,",
                line=i + 1,
            ))
    return violations


_WARN_021 = ValidationRule(
    id="WARN-021",
    name="XDM_CONST field assigned raw string",
    severity="warning",
    category="Data Quality",
    pattern=re.compile(r"xdm\.\S+\s*="),
    message="An XDM field that expects an XDM_CONST enumeration is being assigned a raw string literal",
    recommendation="Use the appropriate XDM_CONST.* constant or an if() chain that maps values to XDM_CONST.* enums",
    codeSnippet='xdm.event.outcome = XDM_CONST.OUTCOME_SUCCESS,  // not "SUCCESS"',
    appliesTo="modeling",
    customCheck=_warn_021_check,
)


# ─────────────────────────────────────────────────────────────────────
# INFO-010 — arrow notation without defensive coalesce
# ─────────────────────────────────────────────────────────────────────

def _info_010_check(code: str, lines: List[str]) -> List[Violation]:
    violations: List[Violation] = []
    if not re.search(r"\[MODEL:", code):
        return violations
    arrow_re = re.compile(r"(\w+)\s*->\s*([\w.]+)")
    reported_lines: set[int] = set()
    paren_balance = 0
    inside_coalesce = False
    for i, line in enumerate(lines):
        trimmed = line.lstrip()
        if trimmed.startswith("//"):
            continue
        code_part = trimmed.split("//", 1)[0]
        if not inside_coalesce and re.search(r"\bcoalesce\s*\(", code_part):
            inside_coalesce = True
            paren_balance = 0
        if inside_coalesce:
            for ch in code_part:
                if ch == "(":
                    paren_balance += 1
                if ch == ")":
                    paren_balance -= 1
            if paren_balance <= 0:
                inside_coalesce = False
                paren_balance = 0
            continue
        if re.search(r"\bcoalesce\s*\(", code_part):
            continue
        for m in arrow_re.finditer(code_part):
            lhs = m.group(1)
            prop = m.group(2)
            lhs_first = lhs[0] if lhs else ""
            if lhs_first and lhs_first == lhs_first.upper() and lhs_first != lhs_first.lower():
                continue
            first_char = prop[0] if prop else ""
            if first_char and first_char == first_char.upper() and first_char != first_char.lower():
                if i not in reported_lines:
                    reported_lines.add(i)
                    lc_first = prop[0].lower() + prop[1:] if len(prop) > 1 else prop.lower()
                    violations.append(Violation(
                        ruleId="INFO-010",
                        ruleName="Arrow notation without defensive coalesce",
                        severity="info",
                        category="Defensive Coding",
                        message=f"Arrow notation '{m.group(0)}' accesses a PascalCase property without a coalesce() fallback for camelCase. XSIAM parsers may output either casing convention",
                        recommendation=f"Consider wrapping in coalesce({lhs} -> {prop}, {lhs} -> {lc_first}) for defensive extraction",
                        line=i + 1,
                    ))
    return violations


_INFO_010 = ValidationRule(
    id="INFO-010",
    name="Arrow notation without defensive coalesce",
    severity="info",
    category="Defensive Coding",
    pattern=re.compile(r"->"),
    message="Arrow notation field access without a coalesce() for alternative casing",
    recommendation="Use coalesce(field -> PascalCase, field -> camelCase) for defensive extraction when the XSIAM parser may output either casing convention",
    codeSnippet="coalesce(finding_resource -> AccessKeyDetails.UserName, finding_resource -> accessKeyDetails.userName)",
    appliesTo="modeling",
    customCheck=_info_010_check,
)


# ─────────────────────────────────────────────────────────────────────
# WARN-022 — Missing null guard on arraycreate()
# ─────────────────────────────────────────────────────────────────────

def _warn_022_check(code: str, lines: List[str]) -> List[Violation]:
    violations: List[Violation] = []
    arr_re = re.compile(r"\barraycreate\s*\(\s*(\w+)\s*\)")
    for i, line in enumerate(lines):
        trimmed = line.lstrip()
        if trimmed.startswith("//"):
            continue
        code_part = trimmed.split("//", 1)[0]
        if re.search(r"\bif\s*\(", code_part):
            continue
        for m in arr_re.finditer(code_part):
            arg = m.group(1)
            if re.match(r'^".*"$', arg) or re.match(r"^'.*'$", arg) or \
                    re.match(r"^\d+$", arg) or arg in ("null", "true", "false"):
                continue
            violations.append(Violation(
                ruleId="WARN-022",
                ruleName="Missing null guard on arraycreate()",
                severity="warning",
                category="Data Quality",
                message=f"arraycreate({arg}) will produce [null] if '{arg}' is null, rather than returning null. This can cause unexpected behaviour in XSIAM",
                recommendation=f"Add a null guard: if({arg} != null, arraycreate({arg}))",
                line=i + 1,
            ))
    return violations


_WARN_022 = ValidationRule(
    id="WARN-022",
    name="Missing null guard on arraycreate()",
    severity="warning",
    category="Data Quality",
    pattern=re.compile(r"arraycreate\s*\("),
    message="arraycreate() called without a null guard",
    recommendation="Wrap in an if() guard: if(field != null, arraycreate(field)) -- arraycreate(null) produces [null] rather than null",
    codeSnippet="xdm.source.host.ipv4_addresses = if(ip_addr != null, arraycreate(ip_addr)),",
    appliesTo="both",
    customCheck=_warn_022_check,
)


# ─────────────────────────────────────────────────────────────────────
# WARN-023..WARN-028 — data model compatibility / data quality
# ─────────────────────────────────────────────────────────────────────

_WARN_023 = ValidationRule(
    id="WARN-023",
    name="xdm.alert.mitre_techniques may not be in the selected data model",
    severity="warning",
    category="Data Model Compatibility",
    pattern=re.compile(r"xdm\.alert\.mitre_techniques\s*="),
    message="xdm.alert.mitre_techniques is known to cause Cortex IDE internal validation errors on certain datasets",
    recommendation="This XDM field is not part of the selected data model on some datasets (e.g. _gc_raw datasets). The Cortex IDE will return 'There was an internal error while trying to validate mapping' rather than a clean field error. Verify the field is available on your target dataset before using it. xdm.alert.mitre_tactics is generally available and unaffected",
    codeSnippet="// xdm.alert.mitre_tactics works -- use this for MITRE mapping\n// xdm.alert.mitre_techniques may NOT be available on all data models",
    appliesTo="modeling",
)

_WARN_024 = ValidationRule(
    id="WARN-024",
    name="xdm.target.process.integrity_level may crash Cortex IDE validator",
    severity="warning",
    category="Data Model Compatibility",
    pattern=re.compile(r"xdm\.target\.process\.integrity_level\s*="),
    message="xdm.target.process.integrity_level with XDM_CONST.INTEGRITY_LEVEL_* if() chains causes Cortex IDE internal validation errors on _gc_raw datasets",
    recommendation="This field triggers the same 'internal error' as xdm.alert.mitre_techniques when used with XDM_CONST enum mapping chains on _gc_raw datasets. Remove this field or test it individually on your target dataset before including it in a full rule. The raw integer value can be stored in a string field as a workaround",
    codeSnippet="// INCOMPATIBLE on _gc_raw:\n// xdm.target.process.integrity_level = if(\n//     integrity = 0, XDM_CONST.INTEGRITY_LEVEL_UNTRUSTED, ...)\n// Workaround: store raw value in a string field if needed",
    appliesTo="modeling",
)

_WARN_025 = ValidationRule(
    id="WARN-025",
    name="xdm.session_context_id may not be in the selected data model",
    severity="warning",
    category="Data Model Compatibility",
    pattern=re.compile(r"xdm\.session_context_id\s*="),
    message="xdm.session_context_id is known to cause Cortex IDE internal validation errors on _gc_raw datasets",
    recommendation="This field exists in the XDM schema but is not part of the selected data model on some datasets (e.g. trend_micro_vision_one_gc_raw). Remove it or verify availability on your target dataset",
    appliesTo="modeling",
)

_WARN_026 = ValidationRule(
    id="WARN-026",
    name="xdm.network.direction may not be in the selected data model",
    severity="warning",
    category="Data Model Compatibility",
    pattern=re.compile(r"xdm\.network\.direction\s*="),
    message="xdm.network.direction is not part of the selected data model on some datasets",
    recommendation="This field is confirmed as unavailable on _gc_raw datasets. The Cortex IDE returns 'not part of the selected data model'. Remove this field or verify availability on your target dataset",
    appliesTo="modeling",
)

_WARN_027 = ValidationRule(
    id="WARN-027",
    name="xdm.source.process.parent_process.* does not exist in XDM schema",
    severity="warning",
    category="Data Model Compatibility",
    pattern=re.compile(r"xdm\.source\.process\.parent_process\.\S+\s*="),
    message="xdm.source.process.parent_process.* fields do not exist in the XDM schema and will cause Cortex IDE internal errors on ALL datasets",
    recommendation="The XDM schema has no parent_process child object under source.process. These paths look plausible but are invalid. There is no XDM field for grandparent process data. Remove these assignments entirely",
    codeSnippet="// INVALID -- these fields do NOT exist in the XDM schema:\n// xdm.source.process.parent_process.name\n// xdm.source.process.parent_process.pid\n// xdm.source.process.parent_process.command_line",
    appliesTo="modeling",
)

_WARN_028 = ValidationRule(
    id="WARN-028",
    name="Missing xdm.event.original_event_type mapping for source filter",
    severity="warning",
    category="Data Quality",
    pattern=re.compile(r'filter\s[\s\S]*?\bsource\s*=\s*"'),
    antiPattern=re.compile(r"xdm\.event\.original_event_type\s*="),
    message="Rule filters on source but does not map xdm.event.original_event_type to preserve the source value",
    recommendation="Add xdm.event.original_event_type = source to preserve the original log subtype (e.g. 'endpointActivityData', 'detections') in the data model. This is distinct from xdm.event.type which should hold a normalised category",
    codeSnippet='xdm.event.type = "ENDPOINT_ACTIVITY",\nxdm.event.original_event_type = source,',
    appliesTo="modeling",
)


# ─────────────────────────────────────────────────────────────────────
# ERR-011 — self-referencing XDM field in assignment
# ─────────────────────────────────────────────────────────────────────

def _err_011_check(code: str, lines: List[str]) -> List[Violation]:
    violations: List[Violation] = []
    if not re.search(r"\[MODEL:", code):
        return violations
    assign_re = re.compile(r"^\s*(xdm\.\S+)\s*=\s*.*\b(xdm\.\S+)")
    for i, line in enumerate(lines):
        trimmed = line.lstrip()
        if trimmed.startswith("//"):
            continue
        code_part = trimmed.split("//", 1)[0]
        m = assign_re.match(code_part)
        if m:
            lhs = re.sub(r"[,;]\s*$", "", m.group(1))
            rhs = re.sub(r"[,;)\s]+$", "", m.group(2))
            if lhs == rhs:
                violations.append(Violation(
                    ruleId="ERR-011",
                    ruleName="Self-referencing XDM field in assignment",
                    severity="error",
                    category="XDM Assignment",
                    message=f"'{lhs}' references itself on the right-hand side of its own assignment. In MODEL rules, XDM fields cannot be read during assignment",
                    recommendation="Use an intermediary _temp variable or assign the fallback value directly instead of wrapping in coalesce() with the same XDM field",
                    line=i + 1,
                ))
    return violations


_ERR_011 = ValidationRule(
    id="ERR-011",
    name="Self-referencing XDM field in assignment",
    severity="error",
    category="XDM Assignment",
    pattern=re.compile(r"xdm\.\S+\s*=\s*coalesce\s*\("),
    message="XDM field references itself on the right-hand side of its own assignment",
    recommendation="In MODEL rules, you cannot read an XDM field you are assigning. Use an intermediary _temp variable or assign the fallback value directly",
    codeSnippet="// WRONG: xdm.target.ipv4 = coalesce(xdm.target.ipv4, _client_ip)\n// RIGHT: xdm.target.ipv4 = _client_ip",
    appliesTo="modeling",
    customCheck=_err_011_check,
)


# ─────────────────────────────────────────────────────────────────────
# INFO-011 — one-sided source/target field mapping
# ─────────────────────────────────────────────────────────────────────

def _info_011_check(code: str, lines: List[str]) -> List[Violation]:
    violations: List[Violation] = []
    if not re.search(r"\[MODEL:", code):
        return violations
    stripped = "\n".join(
        "" if l.lstrip().startswith("//") else l.lstrip().split("//", 1)[0]
        for l in lines
    )
    pairs = [
        {"field": "ipv4", "source": r"xdm\.source\.ipv4\s*=", "target": r"xdm\.target\.ipv4\s*="},
        {"field": "user.username", "source": r"xdm\.source\.user\.username\s*=", "target": r"xdm\.target\.user\.username\s*="},
    ]
    for p in pairs:
        has_source = bool(re.search(p["source"], stripped))
        has_target = bool(re.search(p["target"], stripped))
        what = "IP address" if p["field"] == "ipv4" else "user"
        if has_source and not has_target:
            violations.append(Violation(
                ruleId="INFO-011",
                ruleName="One-sided source/target field mapping",
                severity="suggestion",
                category="Field Coverage",
                message=f"xdm.source.{p['field']} is mapped but xdm.target.{p['field']} is not. If the payload has only one {what}, consider mirroring to both sides for correlation coverage",
                recommendation=f"Add xdm.target.{p['field']} = <same_value> to ensure XSIAM correlation queries match regardless of which side is searched",
            ))
        elif not has_source and has_target:
            violations.append(Violation(
                ruleId="INFO-011",
                ruleName="One-sided source/target field mapping",
                severity="suggestion",
                category="Field Coverage",
                message=f"xdm.target.{p['field']} is mapped but xdm.source.{p['field']} is not. If the payload has only one {what}, consider mirroring to both sides for correlation coverage",
                recommendation=f"Add xdm.source.{p['field']} = <same_value> to ensure XSIAM correlation queries match regardless of which side is searched",
            ))
    return violations


_INFO_011 = ValidationRule(
    id="INFO-011",
    name="One-sided source/target field mapping",
    severity="suggestion",
    category="Field Coverage",
    pattern=re.compile(r"xdm\.(source|target)\.(ipv4|user\.username)\s*="),
    message="Only one side (source or target) has this field mapped",
    recommendation="If the payload has only one entity (one IP, one username), consider mirroring it to both xdm.source.* and xdm.target.* to maximise correlation coverage in XSIAM",
    appliesTo="modeling",
    customCheck=_info_011_check,
)


# ─────────────────────────────────────────────────────────────────────
# SUG-013 — consider xdm.source.user.identity_type mapping
# ─────────────────────────────────────────────────────────────────────

_SUG_013 = ValidationRule(
    id="SUG-013",
    name="Consider xdm.source.user.identity_type mapping",
    severity="suggestion",
    category="XDM Enrichment",
    pattern=re.compile(r"xdm\.source\.user\.user_type\s*="),
    antiPattern=re.compile(r"xdm\.source\.user\.identity_type\s*="),
    message="Rule maps xdm.source.user.user_type but does not map xdm.source.user.identity_type",
    recommendation="Consider mapping xdm.source.user.identity_type using an if() chain to normalise vendor-specific user types to XDM_CONST.IDENTITY_TYPE_* enums (MACHINE, USER, BUILTIN, VIRTUAL, UNKNOWN). This improves cross-vendor correlation in XSIAM",
    codeSnippet='xdm.source.user.identity_type = if(\n    user_type = "Root", XDM_CONST.IDENTITY_TYPE_BUILTIN,\n    user_type = "IAMUser", XDM_CONST.IDENTITY_TYPE_USER,\n    XDM_CONST.IDENTITY_TYPE_UNKNOWN),',
    appliesTo="modeling",
)


# ─────────────────────────────────────────────────────────────────────
# WARN-029 — XDM_CONST if-chain default branch uses raw variable
# ─────────────────────────────────────────────────────────────────────

def _warn_029_check(code: str, lines: List[str]) -> List[Violation]:
    violations: List[Violation] = []
    if not re.search(r"\[MODEL:", code):
        return violations
    full_text = "\n".join(
        "" if l.lstrip().startswith("//") else l.lstrip().split("//", 1)[0]
        for l in lines
    )
    const_paths = xdm_const_paths()
    assign_re = re.compile(r"(xdm\.[\w.]+)\s*=\s*if\s*\(")
    for m in assign_re.finditer(full_text):
        field_path = m.group(1)
        const_type = const_paths.get(field_path)
        if not const_type:
            continue
        if_start = m.end()
        depth = 1
        pos = if_start
        while pos < len(full_text) and depth > 0:
            if full_text[pos] == "(":
                depth += 1
            elif full_text[pos] == ")":
                depth -= 1
            if depth > 0:
                pos += 1
        if depth != 0:
            continue
        if_args = full_text[if_start:pos]
        if not re.search(r"\bXDM_CONST\.", if_args):
            continue
        last_comma = -1
        paren_depth = 0
        for i, ch in enumerate(if_args):
            if ch == "(":
                paren_depth += 1
            elif ch == ")":
                paren_depth -= 1
            elif ch == "," and paren_depth == 0:
                last_comma = i
        if last_comma == -1:
            continue
        last_arg = if_args[last_comma + 1:].strip()
        if re.match(r"^XDM_CONST\.", last_arg):
            continue
        if re.match(r"^null$", last_arg, re.IGNORECASE):
            continue
        if re.match(r'^"[^"]*"$', last_arg) or re.match(r"^'[^']*'$", last_arg):
            continue
        if re.match(r"^[_a-zA-Z]\w*$", last_arg) or re.match(r"^\w+\s*!=\s*null", last_arg):
            line_num = None
            search = field_path + " = if("
            idx = full_text.find(search)
            if idx == -1:
                search = field_path + "= if("
                idx = full_text.find(search)
            if idx >= 0:
                line_num = full_text[:idx].count("\n") + 1
            violations.append(Violation(
                ruleId="WARN-029",
                ruleName="XDM_CONST if-chain default branch uses raw variable",
                severity="warning",
                category="Data Quality",
                message=f"'{field_path}' requires {const_type} enum values but the if-chain's default branch falls through to a raw variable '{last_arg}'. Non-enum values are silently dropped by Cortex",
                recommendation=f"Map every expected value to a {const_type}_* constant, or omit the default branch so unmatched values produce null (safe). Use a String-type companion field (e.g. xdm.alert.subcategory) for the raw vendor text",
                line=line_num,
            ))
    return violations


_WARN_029 = ValidationRule(
    id="WARN-029",
    name="XDM_CONST if-chain default branch uses raw variable",
    severity="warning",
    category="Data Quality",
    pattern=re.compile(r"\bif\s*\("),
    message="An XDM_CONST field's if-chain has a default branch that falls through to a raw variable instead of an XDM_CONST value or null",
    recommendation="The final (default) branch of an if-chain for an XDM_CONST-required field must be another XDM_CONST constant, null, or omitted entirely. A raw variable default causes silent data loss in Cortex because non-enum values are dropped",
    codeSnippet="// WRONG: xdm.alert.category = if(_cat = \"sql_injection\", XDM_CONST.THREAT_CATEGORY_SQL_INJECTION, _cat != null, _cat)",
    appliesTo="modeling",
    customCheck=_warn_029_check,
)


# ─────────────────────────────────────────────────────────────────────
# WARN-030 — array XDM field assigned without arraycreate()
# ─────────────────────────────────────────────────────────────────────

def _warn_030_check(code: str, lines: List[str]) -> List[Violation]:
    violations: List[Violation] = []
    if not re.search(r"\[MODEL:", code):
        return violations
    flow = analyse_dataflow(code, lines)
    known_array_vars = flow.arrayTyped
    arr_paths = array_xdm_paths()
    skip_patterns = [
        r"\barraycreate\s*\(", r"\barrayconcat\s*\(", r"\barraymerge\s*\(",
        r"\barraydistinct\s*\(", r"\barrayfilter\s*\(", r"\barraymap\s*\(",
        r"\bjson_extract_array\s*\(", r"\bsplit\s*\(",
    ]
    for i, line in enumerate(lines):
        trimmed = line.lstrip()
        if trimmed.startswith("//"):
            continue
        code_part = trimmed.split("//", 1)[0]
        m = re.match(r"^(xdm\.[\w.]+)\s*=\s*(.+)", code_part)
        if not m:
            continue
        field_path = m.group(1)
        rhs = m.group(2).strip()
        if field_path not in arr_paths:
            continue
        if any(re.search(p, rhs) for p in skip_patterns):
            continue
        if re.match(r"^null\s*[,)]?", rhs):
            continue
        lookahead = code_part + " " + " ".join(lines[i + 1:i + 8])
        if re.search(r"\bif\s*\(", rhs) and re.search(r"\barraycreate\s*\(", lookahead):
            continue
        if re.search(r"\bcoalesce\s*\(", rhs) and re.search(r"\barraycreate\s*\(", lookahead):
            continue
        if rhs_is_array_typed(rhs, known_array_vars):
            continue
        violations.append(Violation(
            ruleId="WARN-030",
            ruleName="Array XDM field assigned without arraycreate()",
            severity="warning",
            category="Data Quality",
            message=f"'{field_path}' is an Array-type field but is assigned a scalar value without arraycreate(). Cortex expects an array value for this field",
            recommendation=f"Wrap the value in arraycreate(): {field_path} = if(value != null, arraycreate(value), null)",
            codeSnippet=f"{field_path} = if(_value != null, arraycreate(_value), null)",
            line=i + 1,
        ))
    return violations


_WARN_030 = ValidationRule(
    id="WARN-030",
    name="Array XDM field assigned without arraycreate()",
    severity="warning",
    category="Data Quality",
    pattern=re.compile(r"xdm\.\S+\s*="),
    message="An Array-type XDM field is assigned a scalar value without wrapping it in arraycreate()",
    recommendation="Array XDM fields (e.g. xdm.source.host.ipv4_addresses) must receive an array value. Wrap scalar values in arraycreate() and guard with a null check",
    codeSnippet="xdm.source.host.ipv4_addresses = if(_src_ip != null, arraycreate(_src_ip), null)",
    appliesTo="modeling",
    customCheck=_warn_030_check,
)


# ─────────────────────────────────────────────────────────────────────
# WARN-035 — XDM field type mismatch (broad)
# ─────────────────────────────────────────────────────────────────────

_IPV4_RE_W35 = re.compile(
    r"^(?:25[0-5]|2[0-4]\d|[01]?\d?\d)(?:\.(?:25[0-5]|2[0-4]\d|[01]?\d?\d)){3}$"
)
_IPV6_LOOSE_RE = re.compile(r"^[0-9a-fA-F:.]+$")


def _warn_035_check(code: str, lines: List[str]) -> List[Violation]:
    violations: List[Violation] = []
    if not re.search(r"\[MODEL:", code):
        return violations
    flow = analyse_dataflow(code, lines)
    known_array_vars = flow.arrayTyped
    assign_re = re.compile(r"^(xdm\.[\w.]+)\s*=\s*(.+?)\s*$")
    for i, line in enumerate(lines):
        trimmed = line.lstrip()
        if trimmed.startswith("//"):
            continue
        code_part = trimmed.split("//", 1)[0]
        m = assign_re.match(code_part)
        if not m:
            continue
        field_path = m.group(1)
        rhs_raw = m.group(2).strip()
        rhs = re.sub(r"[,;]\s*$", "", rhs_raw).strip()
        if not rhs:
            continue
        if re.search(r"\bXDM_CONST\.", rhs):
            continue
        if rhs == "null":
            continue
        meta = get_xdm_field_type(field_path)
        if not meta:
            continue

        if meta["kind"] == "array":
            is_arr = rhs_is_array_typed(rhs, known_array_vars)
            if not is_arr:
                lookahead = " ".join(lines[i:i + 8])
                if re.search(r"\barraycreate\s*\(|\barrayconcat\s*\(|\barraymerge\s*\(", lookahead) and \
                        re.search(r"\bif\s*\(|\bcoalesce\s*\(", rhs):
                    continue
                violations.append(Violation(
                    ruleId="WARN-035",
                    ruleName="XDM field type mismatch",
                    severity="warning",
                    category="Data Quality",
                    message=f"'{field_path}' is an Array-type XDM field but is being assigned a scalar value. Wrap with arraycreate() or use an array-producing function so the assignment matches the field's declared shape",
                    recommendation=f"Wrap the value: {field_path} = if(_value != null, arraycreate(_value), null)",
                    line=i + 1,
                ))
                continue
        else:
            bare_ident = re.match(r"^([a-zA-Z_]\w*)$", rhs)
            if bare_ident and bare_ident.group(1) in known_array_vars:
                violations.append(Violation(
                    ruleId="WARN-035",
                    ruleName="XDM field type mismatch",
                    severity="warning",
                    category="Data Quality",
                    message=f"'{field_path}' is a scalar XDM field but is being assigned the array temp '{bare_ident.group(1)}'. Use arrayindex({bare_ident.group(1)}, 0) or arraystring({bare_ident.group(1)}, \",\") to convert to a scalar first",
                    recommendation=f"Convert the array to a scalar before assigning: {field_path} = arrayindex({bare_ident.group(1)}, 0)",
                    line=i + 1,
                ))
                continue
            fn_match = re.match(r"^([a-zA-Z_]\w*)\s*\(", rhs)
            if fn_match:
                fn = fn_match.group(1).lower()
                if fn in ARRAY_PRODUCING_FNS:
                    violations.append(Violation(
                        ruleId="WARN-035",
                        ruleName="XDM field type mismatch",
                        severity="warning",
                        category="Data Quality",
                        message=f"'{field_path}' is a scalar XDM field but is being assigned the result of array-producing function '{fn}()'. Wrap with arrayindex() or arraystring() to extract a scalar",
                        recommendation=f"Convert to a scalar: {field_path} = arrayindex({fn}(...), 0) or arraystring({fn}(...), \",\")",
                        line=i + 1,
                    ))
                    continue

        # Enum vocabulary
        enum_values = get_xdm_field_enum(field_path)
        if enum_values:
            lit = as_string_literal(rhs)
            if lit is not None and lit not in enum_values:
                violations.append(Violation(
                    ruleId="WARN-035",
                    ruleName="XDM field type mismatch",
                    severity="warning",
                    category="Data Quality",
                    message=f"'{field_path}' expects a value from a closed XDM_CONST vocabulary; \"{lit}\" is not in that vocabulary",
                    recommendation="Use the appropriate XDM_CONST.* token for this field, or one of the documented raw values from the field's enum vocabulary",
                    line=i + 1,
                ))
                continue

        # Scalar literal type vs declared base
        if meta["kind"] == "scalar":
            base = meta["base"]
            lit = as_string_literal(rhs)
            if lit is not None:
                if base == "ipv4" and not _IPV4_RE_W35.match(lit):
                    violations.append(Violation(
                        ruleId="WARN-035",
                        ruleName="XDM field type mismatch",
                        severity="warning",
                        category="Data Quality",
                        message=f"'{field_path}' expects an IPv4 address but is assigned the string literal \"{lit}\", which is not a valid IPv4 address",
                        recommendation="Assign a value that resolves to an IPv4 address (typically a parsed source field) or remove the assignment",
                        line=i + 1,
                    ))
                    continue
                if base == "ipv6" and (":" not in lit or not _IPV6_LOOSE_RE.match(lit)):
                    violations.append(Violation(
                        ruleId="WARN-035",
                        ruleName="XDM field type mismatch",
                        severity="warning",
                        category="Data Quality",
                        message=f"'{field_path}' expects an IPv6 address but is assigned the string literal \"{lit}\", which is not a valid IPv6 address",
                        recommendation="Assign a value that resolves to an IPv6 address or remove the assignment",
                        line=i + 1,
                    ))
                    continue
                if base in ("int", "float") and not re.match(r"^-?\d+(?:\.\d+)?$", lit):
                    cast = "to_integer" if base == "int" else "to_float"
                    violations.append(Violation(
                        ruleId="WARN-035",
                        ruleName="XDM field type mismatch",
                        severity="warning",
                        category="Data Quality",
                        message=f"'{field_path}' expects a {base} but is assigned the string literal \"{lit}\". Use {cast}() to convert, or assign a numeric expression",
                        recommendation=f"Convert: {field_path} = {cast}({rhs})",
                        line=i + 1,
                    ))
                    continue
                if base == "bool" and lit not in ("true", "false"):
                    violations.append(Violation(
                        ruleId="WARN-035",
                        ruleName="XDM field type mismatch",
                        severity="warning",
                        category="Data Quality",
                        message=f"'{field_path}' expects a boolean but is assigned the string literal \"{lit}\". Use to_boolean() or assign true / false directly",
                        recommendation=f"Convert: {field_path} = to_boolean({rhs})",
                        line=i + 1,
                    ))
                    continue
            else:
                if re.match(r"^-?\d+$", rhs):
                    if base == "string":
                        violations.append(Violation(
                            ruleId="WARN-035",
                            ruleName="XDM field type mismatch",
                            severity="warning",
                            category="Data Quality",
                            message=f"'{field_path}' expects a string but is assigned the integer literal '{rhs}'. Wrap with to_string() to convert",
                            recommendation=f"{field_path} = to_string({rhs})",
                            line=i + 1,
                        ))
                        continue
                elif re.match(r"^-?\d+\.\d+$", rhs):
                    if base in ("string", "int"):
                        violations.append(Violation(
                            ruleId="WARN-035",
                            ruleName="XDM field type mismatch",
                            severity="warning",
                            category="Data Quality",
                            message=f"'{field_path}' expects a {base} but is assigned the float literal '{rhs}'",
                            recommendation=f"Convert with to_{'string' if base == 'string' else 'integer'}() or assign a value that matches the declared base",
                            line=i + 1,
                        ))
                        continue
                elif rhs in ("true", "false"):
                    if base != "bool":
                        violations.append(Violation(
                            ruleId="WARN-035",
                            ruleName="XDM field type mismatch",
                            severity="warning",
                            category="Data Quality",
                            message=f"'{field_path}' expects {base} but is assigned the boolean literal '{rhs}'",
                            recommendation=f"Use to_string({rhs}) or assign a value of type {base}",
                            line=i + 1,
                        ))
                        continue
            if base != "string" and as_string_literal(rhs) is None and \
                    not re.match(r"^-?\d+(?:\.\d+)?$", rhs) and rhs not in ("true", "false"):
                inferred = infer_scalar_base(rhs, flow.defs)
                if inferred is not None and not scalar_bases_compatible(inferred, base):
                    cast_fn = {"int": "to_integer", "float": "to_float", "bool": "to_boolean"}.get(base)
                    if cast_fn:
                        recommendation = f"Convert the value: {field_path} = {cast_fn}({rhs}) (or define the source temp as {base})"
                    else:
                        recommendation = f"Assign a value of type {base} (the source temp resolves to {inferred})"
                    violations.append(Violation(
                        ruleId="WARN-035",
                        ruleName="XDM field type mismatch",
                        severity="warning",
                        category="Data Quality",
                        message=f"'{field_path}' expects {base} but the assigned expression resolves to {inferred}",
                        recommendation=recommendation,
                        line=i + 1,
                    ))
                    continue
    return violations


_WARN_035 = ValidationRule(
    id="WARN-035",
    name="XDM field type mismatch",
    severity="warning",
    category="Data Quality",
    pattern=re.compile(r"xdm\.[\w.]+\s*="),
    message="RHS value type does not match the declared XDM field type",
    recommendation="Adjust the value to match the declared XDM type: wrap with arraycreate() / arrayindex() to bridge array vs scalar shapes, use an XDM_CONST.* token (or a value from the documented vocabulary) for enum fields, and use a literal that matches the scalar base (int / float / bool / ipv4 / ipv6) instead of an arbitrary quoted string",
    appliesTo="modeling",
    customCheck=_warn_035_check,
)


# ─────────────────────────────────────────────────────────────────────
# WARN-036 — arraycreate() with potentially-null element
# ─────────────────────────────────────────────────────────────────────

def _warn_036_check(code: str, lines: List[str]) -> List[Violation]:
    violations: List[Violation] = []
    if not re.search(r"\[MODEL:", code):
        return violations

    def is_trusted_literal(arg: str) -> bool:
        a = arg.strip()
        if not a:
            return False
        if re.match(r'^"(?:[^"\\]|\\.)*"$', a):
            return True
        if re.match(r"^'(?:[^'\\]|\\.)*'$", a):
            return True
        if re.match(r"^-?\d+(?:\.\d+)?$", a):
            return True
        if a in ("true", "false"):
            return True
        if re.match(r"^XDM_CONST\.\w+$", a):
            return True
        return False

    def is_single_arm_if(arg: str) -> bool:
        t = arg.strip()
        m = re.match(r"^if\s*\(", t, re.IGNORECASE)
        if not m:
            return False
        if not t.endswith(")"):
            return False
        inner = t[len(m.group(0)):len(t) - 1]
        args = split_top_level_args(inner)
        return len(args) >= 2 and len(args) % 2 == 0

    # Build flat string + line map (string-aware, comment-aware).
    flat: list[str] = []
    line_map: list[int] = []
    for li, line in enumerate(lines):
        line_no = li + 1
        in_str = None
        ci = 0
        while ci < len(line):
            ch = line[ci]
            if in_str:
                flat.append(ch)
                line_map.append(line_no)
                if ch == in_str and (ci == 0 or line[ci - 1] != "\\"):
                    in_str = None
                ci += 1
                continue
            if ch == "/" and ci + 1 < len(line) and line[ci + 1] == "/":
                break
            if ch in ('"', "'"):
                in_str = ch
                flat.append(ch)
                line_map.append(line_no)
                ci += 1
                continue
            flat.append(ch)
            line_map.append(line_no)
            ci += 1
        flat.append("\n")
        line_map.append(line_no)
    flat_str = "".join(flat)

    # Split into statements at depth-0 ',' or ';'.
    statements: list[dict] = []
    depth = 0
    stmt_start = 0
    in_str = None
    i = 0
    while i < len(flat_str):
        ch = flat_str[i]
        if in_str:
            if ch == in_str and (i == 0 or flat_str[i - 1] != "\\"):
                in_str = None
            i += 1
            continue
        if ch in ('"', "'"):
            in_str = ch
            i += 1
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif depth == 0 and (ch == "," or ch == ";"):
            statements.append({"text": flat_str[stmt_start:i], "start": stmt_start})
            stmt_start = i + 1
        i += 1
    if stmt_start < len(flat_str):
        statements.append({"text": flat_str[stmt_start:], "start": stmt_start})

    ac_re = re.compile(r"\barraycreate\s*\(")
    for stmt in statements:
        has_null_guard = bool(re.search(r"!=\s*null", stmt["text"]))
        for m in ac_re.finditer(stmt["text"]):
            open_idx = m.end() - 1
            depth_inner = 0
            close_idx = -1
            in_str_inner = None
            j = open_idx
            while j < len(stmt["text"]):
                ch = stmt["text"][j]
                if in_str_inner:
                    if ch == in_str_inner and stmt["text"][j - 1] != "\\":
                        in_str_inner = None
                    j += 1
                    continue
                if ch in ('"', "'"):
                    in_str_inner = ch
                    j += 1
                    continue
                if ch == "(":
                    depth_inner += 1
                elif ch == ")":
                    depth_inner -= 1
                    if depth_inner == 0:
                        close_idx = j
                        break
                j += 1
            if close_idx < 0:
                continue
            inner = stmt["text"][open_idx + 1:close_idx]
            args = split_top_level_args(inner)
            pos_in_flat = stmt["start"] + m.start()
            line_num = line_map[pos_in_flat] if pos_in_flat < len(line_map) else 1
            danger = None
            if not args:
                continue
            if len(args) == 1:
                if is_single_arm_if(args[0]) and not has_null_guard:
                    preview = args[0][:57] + "..." if len(args[0]) > 60 else args[0]
                    danger = f"arraycreate({preview}) wraps a single-arm if() with no else branch. When the condition is false, the if() returns null and Cortex silently discards the entire enclosing alter, including sibling xdm.* assignments"
            else:
                risky = [a for a in args if not is_trusted_literal(a)]
                if not risky:
                    continue
                if has_null_guard:
                    continue
                flat_preview = ", ".join(
                    (a if len(a := re.sub(r"\s+", " ", arg).strip()) <= 30 else a[:27] + "...")
                    for arg in args
                )
                plural = "" if len(risky) == 1 else "s"
                danger = (
                    f"arraycreate({flat_preview}) has {len(risky)} non-literal argument{plural} "
                    f"without a '!= null' guard in the same alter assignment. If any argument resolves "
                    f"to null, Cortex silently discards the entire enclosing alter, including every sibling xdm.* assignment"
                )
            if danger is None:
                continue
            violations.append(Violation(
                ruleId="WARN-036",
                ruleName="arraycreate() with potentially-null element silently drops the alter",
                severity="warning",
                category="Data Quality",
                message=danger,
                recommendation="Wrap the call in an outer 'if(<temp> != null, arraycreate(...), <literal-only fallback>)' on the same RHS. The fallback ensures the alter still runs (and downstream xdm.* assignments still apply) when the inputs are missing",
                line=line_num,
            ))
    return violations


_WARN_036 = ValidationRule(
    id="WARN-036",
    name="arraycreate() with potentially-null element silently drops the alter",
    severity="warning",
    category="Data Quality",
    pattern=re.compile(r"arraycreate\s*\("),
    message="arraycreate() called on a non-literal element without an outer null guard",
    recommendation="Wrap the call in an outer null guard: if(<temp> != null, arraycreate(<temp>, ...), <literal-only fallback>) -- when any element resolves to null, Cortex silently discards the entire enclosing alter, including sibling xdm.* assignments",
    appliesTo="modeling",
    customCheck=_warn_036_check,
)


# ─────────────────────────────────────────────────────────────────────
# WARN-031 — browser detection label
# ─────────────────────────────────────────────────────────────────────

def _warn_031_check(code: str, lines: List[str]) -> List[Violation]:
    violations: List[Violation] = []
    if not re.search(r"\[MODEL:", code):
        return violations
    bot_labels = re.compile(r"\b(bot|crawler|spider|automated|scraper|scanner|unknown_client)\b", re.IGNORECASE)
    for i, line in enumerate(lines):
        trimmed = line.lstrip()
        if trimmed.startswith("//"):
            continue
        code_part = trimmed.split("//", 1)[0]
        m = re.search(r"xdm\.network\.http\.browser\s*=\s*(.+)", code_part)
        if not m:
            continue
        rhs = m.group(1).strip()
        if re.match(r'^"[^"]*"$', rhs) and bot_labels.search(rhs):
            violations.append(Violation(
                ruleId="WARN-031",
                ruleName="xdm.network.http.browser assigned detection label",
                severity="warning",
                category="Data Quality",
                message=f"xdm.network.http.browser is assigned '{rhs.replace(chr(34), '')}' which looks like a detection classification, not a browser name. This field should contain the actual browser name from the User-Agent header (e.g. Chrome, Firefox, Safari)",
                recommendation="Map the browser name to xdm.network.http.browser and place the detection classification in xdm.event.description or a temp variable",
                line=i + 1,
            ))
    return violations


_WARN_031 = ValidationRule(
    id="WARN-031",
    name="xdm.network.http.browser assigned detection label instead of browser name",
    severity="warning",
    category="Data Quality",
    pattern=re.compile(r"xdm\.network\.http\.browser\s*="),
    message="xdm.network.http.browser should contain the browser name (e.g. Chrome, Firefox), not a detection classification label (e.g. Bot, Crawler, Automated)",
    recommendation="Map the declared browser name from the User-Agent header to xdm.network.http.browser. If the log has a classified client type (Bot, Crawler), include it in xdm.event.description instead",
    codeSnippet='// RIGHT: xdm.network.http.browser = _browser_name   (e.g. "Chrome")\n// WRONG: xdm.network.http.browser = _client_type     (e.g. "Bot")',
    appliesTo="modeling",
    customCheck=_warn_031_check,
)


# ─────────────────────────────────────────────────────────────────────
# WARN-032 — Missing companion pair for xdm.alert.severity
# ─────────────────────────────────────────────────────────────────────

def _warn_032_check(code: str, lines: List[str]) -> List[Violation]:
    violations: List[Violation] = []
    if not re.search(r"\[MODEL:", code):
        return violations
    stripped = "\n".join(
        "" if l.lstrip().startswith("//") else l.lstrip().split("//", 1)[0]
        for l in lines
    )
    has_severity = bool(re.search(r"xdm\.alert\.severity\s*=", stripped))
    has_orig = bool(re.search(r"xdm\.alert\.original_alert_id\s*=", stripped))
    has_event_id = bool(re.search(r"xdm\.event\.id\s*=", stripped))
    if has_severity and not has_orig:
        violations.append(Violation(
            ruleId="WARN-032",
            ruleName="Missing xdm.alert.original_alert_id companion",
            severity="warning",
            category="Field Coverage",
            message="xdm.alert.severity is mapped but xdm.alert.original_alert_id is not. These are companion fields -- severity without an alert ID limits correlation",
            recommendation="Add xdm.alert.original_alert_id = <vendor_alert_id> to link severity to a specific alert instance",
        ))
    if (not has_severity) and has_event_id and (not has_orig) and re.search(r"xdm\.alert\.", stripped):
        violations.append(Violation(
            ruleId="WARN-032",
            ruleName="Missing xdm.alert.original_alert_id with xdm.event.id",
            severity="warning",
            category="Field Coverage",
            message="xdm.event.id is mapped alongside alert fields but xdm.alert.original_alert_id is not. When alert fields are present, map original_alert_id so both event and alert correlation paths are covered",
            recommendation="Add xdm.alert.original_alert_id = <vendor_alert_id_or_event_id> to complete the alert companion pair",
        ))
    return violations


_WARN_032 = ValidationRule(
    id="WARN-032",
    name="Missing companion pair for xdm.alert.severity",
    severity="warning",
    category="Field Coverage",
    pattern=re.compile(r"xdm\.event\.outcome\s*="),
    message="Rule maps alert/event fields but is missing companion pairs",
    recommendation="When mapping alert fields, ensure companion pairs are complete: xdm.alert.severity with xdm.alert.original_alert_id, and xdm.event.id with xdm.alert.original_alert_id",
    appliesTo="modeling",
    customCheck=_warn_032_check,
)


# ─────────────────────────────────────────────────────────────────────
# ERR-012 — infix arithmetic in alter
# ─────────────────────────────────────────────────────────────────────

def _err_012_check(code: str, lines: List[str]) -> List[Violation]:
    violations: List[Violation] = []
    reported: set[int] = set()
    for stmt in collect_stage_statements(lines):
        if stmt.stage != "alter":
            continue
        split = split_assignment(stmt)
        if not split:
            continue
        rhs_start = split["rhsStart"]
        rhs_raw = stmt.text[rhs_start:]
        # Mask string literals by replacing with same-length spaces, then '->' too.

        def _mask(m):
            return m.group(0)[0] + " " * max(0, len(m.group(0)) - 2) + m.group(0)[-1]

        cleaned = re.sub(r'"(?:[^"\\]|\\.)*"', _mask, rhs_raw)
        cleaned = re.sub(r"'(?:[^'\\]|\\.)*'", _mask, cleaned)
        cleaned = cleaned.replace("->", "@@")
        infix = re.compile(r"(?:[\w)])\s*([-+*/])\s*(?:[\w(])")
        for m in infix.finditer(cleaned):
            op_pos = rhs_start + m.start() + m.group(0).index(m.group(1))
            op_line = line_at(stmt, op_pos)
            key = stmt.startLine * 100000 + op_line
            if key in reported:
                continue
            reported.add(key)
            violations.append(Violation(
                ruleId="ERR-012",
                ruleName="Infix arithmetic operator in alter",
                severity="error",
                category="Cortex Parser Conformance",
                message="Infix arithmetic ('+' '-' '*' '/') in an alter assignment is rejected by the Cortex parser. Use the function form (add/subtract/multiply/divide)",
                recommendation="Replace 'a - b' with 'subtract(a, b)', 'a + b' with 'add(a, b)', 'a * b' with 'multiply(a, b)', and 'a / b' with 'divide(a, b)'. The Cortex parser produces a cascade of unrelated-looking errors when infix arithmetic is used",
                codeSnippet="_duration_ms = subtract(_end_ms, _start_ms)",
                line=op_line,
            ))
    return violations


_ERR_012 = ValidationRule(
    id="ERR-012",
    name="Infix arithmetic operator in alter (use add/subtract/multiply/divide)",
    severity="error",
    category="Cortex Parser Conformance",
    pattern=re.compile(r"\|\s*alter\b", re.IGNORECASE),
    message="Infix arithmetic operators (+ - * /) are rejected by the Cortex parser inside alter assignments",
    recommendation="Replace infix arithmetic with the function form: add(a,b), subtract(a,b), multiply(a,b), divide(a,b). Cortex emits a cascade of generic parse errors when infix arithmetic is used inside alter, so the root cause is often hidden several lines away from the reported location",
    codeSnippet="// WRONG: _duration_ms = _end_ms - _start_ms\n// RIGHT: _duration_ms = subtract(_end_ms, _start_ms)",
    appliesTo="modeling",
    customCheck=_err_012_check,
)


# ─────────────────────────────────────────────────────────────────────
# ERR-013 — compound null guard inside if()
# ─────────────────────────────────────────────────────────────────────

def _err_013_check(code: str, lines: List[str]) -> List[Violation]:
    violations: List[Violation] = []
    pattern = re.compile(
        r"\bif\s*\(\s*[^,)]*?(?:!=|=)\s*null\s+(?:and|or)\s+[^,)]*?(?:!=|=)\s*null\s*,",
        re.IGNORECASE,
    )
    reported: set[str] = set()
    for stmt in collect_stage_statements(lines):
        for m in pattern.finditer(stmt.text):
            if_line = line_at(stmt, m.start())
            key = f"{if_line}:{m.start()}"
            if key in reported:
                continue
            reported.add(key)
            violations.append(Violation(
                ruleId="ERR-013",
                ruleName="Compound null guard inside if() predicate",
                severity="error",
                category="Cortex Parser Conformance",
                message="Compound null guards ('X != null and/or Y != null', or '= null' variants) as an if() predicate are rejected by the Cortex parser",
                recommendation="Remove the guard (Cortex propagates null through arithmetic and most functions), or use coalesce() / nested if() / individual guards instead",
                codeSnippet="// Drop the guard -- subtract(a, b) returns null if either operand is null",
                line=if_line,
            ))
    return violations


_ERR_013 = ValidationRule(
    id="ERR-013",
    name="Multi-arm '!= null and ... != null' inside if() guard",
    severity="error",
    category="Cortex Parser Conformance",
    pattern=re.compile(r"\bif\s*\("),
    message="The Cortex parser rejects compound 'X != null and Y != null' predicates as the first arm of an if() guard",
    recommendation="Cortex propagates null through arithmetic and most functions, so an explicit null guard is rarely needed. Drop the guard, or split the check into nested if() / coalesce() calls",
    codeSnippet="// WRONG: if(a != null and b != null, subtract(a, b))\n// RIGHT: subtract(a, b)   // null propagates automatically",
    appliesTo="modeling",
    customCheck=_err_013_check,
)


# ─────────────────────────────────────────────────────────────────────
# ERR-014 — bareword true/false equality (string column)
# ─────────────────────────────────────────────────────────────────────

def _err_014_check(code: str, lines: List[str]) -> List[Violation]:
    violations: List[Violation] = []
    cur_stage = ""
    eq_re = re.compile(
        r"([A-Za-z_][\w\.]*\s*\([^()]*(?:\([^()]*\)[^()]*)*\)(?:\s*->\s*\w+)?|"
        r"[\w\.\@\"\']+)\s*=\s*(true|false)\b"
    )
    for i, raw in enumerate(lines):
        trimmed = raw.lstrip()
        if trimmed.startswith("//"):
            continue
        code_part = raw.split("//", 1)[0]
        sm = re.match(r"^\s*\|\s*(\w+)\b", code_part)
        if sm:
            cur_stage = sm.group(1).lower()
        if cur_stage and cur_stage not in ("alter", "filter"):
            continue
        for m in eq_re.finditer(code_part):
            lhs = m.group(1)
            if re.search(r"to_boolean\s*\(", lhs, re.IGNORECASE):
                continue
            if re.match(r"^xdm\.", lhs):
                continue
            if re.match(r"^[a-zA-Z_]\w*$", lhs.strip()):
                line_trim = code_part.lstrip()
                if line_trim.startswith(lhs.strip()) or re.search(r",\s*$", code_part[:m.start()]):
                    continue
            lhs_is_string = (
                re.search(r"\bjson_extract_scalar\s*\(", lhs) or
                re.search(r"\bto_string\s*\(", lhs) or
                re.search(r"->\s*\w+\s*$", lhs)
            )
            if not lhs_is_string:
                continue
            violations.append(Violation(
                ruleId="ERR-014",
                ruleName="Bareword true/false equality without to_boolean cast",
                severity="error",
                category="Cortex Parser Conformance",
                message=f"'{lhs} = {m.group(2)}' compares against a bareword boolean. The Cortex parser rejects this when the column is string-typed",
                recommendation=f"Quote the literal ('{lhs} = \"{m.group(2)}\"') if the column is a string, or wrap the column: 'to_boolean({lhs}) = {m.group(2)}'",
                line=i + 1,
            ))
        # Reverse direction
        rev_fwd = re.compile(r'\bto_boolean\s*\([^)]*\)\s*=\s*"(true|false)"')
        rev_bwd = re.compile(r'"(true|false)"\s*=\s*to_boolean\s*\([^)]*\)')
        for rm in rev_fwd.finditer(code_part):
            violations.append(Violation(
                ruleId="ERR-014",
                ruleName="Boolean-typed expression compared to quoted string",
                severity="error",
                category="Cortex Parser Conformance",
                message=f'to_boolean(...) = "{rm.group(1)}" compares a Boolean expression against a quoted string. The Cortex parser rejects this type mismatch',
                recommendation=f"Drop the quotes and use the bareword: to_boolean(...) = {rm.group(1)}",
                line=i + 1,
            ))
        for rm in rev_bwd.finditer(code_part):
            violations.append(Violation(
                ruleId="ERR-014",
                ruleName="Boolean-typed expression compared to quoted string",
                severity="error",
                category="Cortex Parser Conformance",
                message=f'"{rm.group(1)}" = to_boolean(...) compares a quoted string against a Boolean expression. The Cortex parser rejects this type mismatch',
                recommendation=f"Drop the quotes and use the bareword: {rm.group(1)} = to_boolean(...)",
                line=i + 1,
            ))
    return violations


_ERR_014 = ValidationRule(
    id="ERR-014",
    name="Bareword true/false equality without to_boolean cast",
    severity="error",
    category="Cortex Parser Conformance",
    pattern=re.compile(r"=\s*(true|false)\b"),
    message="Equality comparison against bareword true/false fails when the column is string-typed",
    recommendation="Either quote the literal ('= \"true\"' / '= \"false\"') if the column is a string, or wrap the column with to_boolean() and compare against bareword true/false",
    codeSnippet='// String column:   if(_external = "true",  ...)\n// Bool column:     if(to_boolean(_external) = true, ...)',
    appliesTo="modeling",
    customCheck=_err_014_check,
)


# ─────────────────────────────────────────────────────────────────────
# ERR-015 — to_number() result assigned to integer XDM field
# ─────────────────────────────────────────────────────────────────────

_INTEGER_XDM_TARGETS = frozenset({
    "xdm.event.duration", "xdm.source.port", "xdm.target.port",
    "xdm.intermediate.port", "xdm.network.bytes", "xdm.network.packets",
    "xdm.source.sent_bytes", "xdm.source.sent_packets",
    "xdm.target.sent_bytes", "xdm.target.sent_packets",
    "xdm.source.process.pid", "xdm.target.process.pid",
})


def _err_015_check(code: str, lines: List[str]) -> List[Violation]:
    violations: List[Violation] = []
    for i, raw in enumerate(lines):
        trimmed = raw.lstrip()
        if trimmed.startswith("//"):
            continue
        code_part = trimmed.split("//", 1)[0]
        m = re.match(r"^(xdm\.[\w.]+)\s*=\s*(.+)", code_part)
        if not m:
            continue
        fp = m.group(1)
        rhs = m.group(2)
        if fp not in _INTEGER_XDM_TARGETS:
            continue
        if not re.search(r"\bto_number\s*\(", rhs):
            continue
        if re.search(r"\bto_integer\s*\(", rhs):
            continue
        violations.append(Violation(
            ruleId="ERR-015",
            ruleName="to_number() result assigned to integer-typed XDM field",
            severity="error",
            category="Cortex Parser Conformance",
            message=f"'{fp}' is integer-typed but is assigned the result of to_number() (which returns float). The Cortex parser rejects this type mismatch",
            recommendation=f"Wrap the to_number() call in to_integer(): {fp} = to_integer(to_number(...))",
            codeSnippet=f"{fp} = to_integer(to_number(_value))",
            line=i + 1,
        ))
    return violations


_ERR_015 = ValidationRule(
    id="ERR-015",
    name="to_number() result assigned to integer-typed XDM field",
    severity="error",
    category="Cortex Parser Conformance",
    pattern=re.compile(r"xdm\.[\w.]+\s*=\s*to_number\s*\("),
    message="to_number() returns float, but several XDM fields are integer-typed",
    recommendation="Wrap to_number() in to_integer(): 'to_integer(to_number(...))'. Common integer XDM targets include xdm.event.duration, xdm.source.port, xdm.target.port, xdm.network.bytes, xdm.network.packets",
    codeSnippet="xdm.event.duration = to_integer(to_number(_duration_ms))",
    appliesTo="modeling",
    customCheck=_err_015_check,
)


# ─────────────────────────────────────────────────────────────────────
# ERR-016 — invented xdm.event.start_time / end_time
# ─────────────────────────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────────────────────────
# ERR-017 — struct binding to alter target
# ─────────────────────────────────────────────────────────────────────

def _err_017_check(code: str, lines: List[str]) -> List[Violation]:
    violations: List[Violation] = []
    reported_lines: set[int] = set()
    bare_re = re.compile(r'arraymap\s*\(\s*([^,]+?)\s*,\s*"@element"\s*\)(?!\s*->)')
    primitive_ctors = re.compile(r"^(?:arraycreate|split|regextract|arrayrange|arrayconcat)\s*\(")
    primitive_array_vars: set[str] = set()
    prim_ctor_asn = re.compile(
        r"(?:^|[,\s|])\s*(_?[A-Za-z_]\w*)\s*=\s*"
        r"(arraycreate|split|regextract|arrayrange|arrayconcat)\s*\("
    )
    for m in prim_ctor_asn.finditer(code):
        primitive_array_vars.add(m.group(1))

    def is_primitive_input(arg: str) -> bool:
        t = arg.strip()
        if primitive_ctors.match(t):
            return True
        bare = re.match(r"^([A-Za-z_]\w*)$", t)
        if bare and bare.group(1) in primitive_array_vars:
            return True
        return False

    assign_re = re.compile(
        r"^\s*(_\w+)\s*=\s*arrayindex\s*\(\s*arrayfilter\s*\(([\s\S]*?)\)\s*,\s*\d+\s*\)\s*,?\s*$"
    )
    object_intermediates: dict[str, int] = {}
    for i, raw in enumerate(lines):
        trimmed = raw.lstrip()
        if trimmed.startswith("//"):
            continue
        code_part = raw.split("//", 1)[0]
        for bm in bare_re.finditer(code_part):
            if is_primitive_input(bm.group(1)):
                continue
            violations.append(Violation(
                ruleId="ERR-017",
                ruleName='Struct passthrough via arraymap(arr, "@element")',
                severity="error",
                category="Cortex Parser Conformance",
                message='arraymap(arr, "@element") returns the original struct array. The Cortex parser rejects this when the input is an array of objects',
                recommendation='Project ONE scalar at a time: arraymap(arr -> [], "@element" -> field_name)',
                line=i + 1,
            ))
            reported_lines.add(i + 1)
            break
        am = assign_re.match(code_part)
        if am:
            var_name = am.group(1)
            inner = am.group(2)
            scalar_projected = bool(re.search(r'arraymap\s*\([^)]*"@element"\s*->\s*\w+', inner))
            if not scalar_projected:
                object_intermediates[var_name] = i + 1

    if object_intermediates:
        for i, raw in enumerate(lines):
            trimmed = raw.lstrip()
            if trimmed.startswith("//"):
                continue
            code_part = raw.split("//", 1)[0]
            for var_name, def_line in list(object_intermediates.items()):
                if i + 1 == def_line:
                    continue
                use_re = re.compile(r"\b" + re.escape(var_name) + r"\s*->\s*\w+")
                if use_re.search(code_part):
                    if i + 1 in reported_lines:
                        continue
                    reported_lines.add(i + 1)
                    violations.append(Violation(
                        ruleId="ERR-017",
                        ruleName="Struct passthrough via object-valued intermediate",
                        severity="error",
                        category="Cortex Parser Conformance",
                        message=f"'{var_name}' is an object-valued intermediate (defined at line {def_line} via arrayindex(arrayfilter(...)) without scalar projection) and is dereferenced via '->' here. The Cortex parser rejects this struct binding",
                        recommendation=f'Push the scalar projection INSIDE the arrayfilter at line {def_line}: arrayindex(arrayfilter(arraymap(arr -> [], if("@element" -> role = "X", "@element" -> field, null)), "@element" != null), 0). Then \'{var_name}\' is already the scalar you need',
                        line=i + 1,
                    ))
    return violations


_ERR_017 = ValidationRule(
    id="ERR-017",
    name="Struct binding to alter target (bare @element passthrough or object-valued intermediate)",
    severity="error",
    category="Cortex Parser Conformance",
    pattern=re.compile(r'arraymap\s*\([^,]+,\s*"@element"\s*\)|arrayindex\s*\(\s*arrayfilter\s*\('),
    message='alter targets must be scalar or primitive-array typed. Common struct-binding mistakes: arraymap(arr, "@element") returns a struct array; arrayindex(arrayfilter(struct_arr, ...)) returns a struct that is then dereferenced via \'->\'',
    recommendation='Project ONE scalar at a time from each struct: arraymap(arr -> [], "@element" -> field_name). For role-tagged arrays, filter and project per-scalar: arrayindex(arrayfilter(arraymap(arr -> [], if("@element" -> role = "X", "@element" -> field, null)), "@element" != null), 0). Never bind an object intermediate and dereference it later',
    appliesTo="modeling",
    customCheck=_err_017_check,
)


# ─────────────────────────────────────────────────────────────────────
# ERR-018 — Missing '-> []' cast on JSON-string column
# ─────────────────────────────────────────────────────────────────────

_JSON_STRING_COLS = frozenset({"tags", "filters", "detail"})


def _err_018_check(code: str, lines: List[str]) -> List[Violation]:
    violations: List[Violation] = []
    arr_func_re = re.compile(r"\b(arraymap|arrayfilter|arraystring|arraydistinct|array_length)\s*\(")
    reported_keys: set[str] = set()
    for stmt in collect_stage_statements(lines):
        for m in arr_func_re.finditer(stmt.text):
            fn = m.group(1)
            p = m.end()
            while p < len(stmt.text) and stmt.text[p].isspace():
                p += 1
            col_match = re.match(r"^([a-zA-Z_]\w*)", stmt.text[p:])
            if not col_match:
                continue
            col = col_match.group(1)
            if col not in _JSON_STRING_COLS:
                continue
            after = stmt.text[p + len(col):p + len(col) + 8]
            if re.match(r"^\s*->", after):
                continue
            col_line = line_at(stmt, p)
            key = f"{col_line}:{col}"
            if key in reported_keys:
                continue
            reported_keys.add(key)
            violations.append(Violation(
                ruleId="ERR-018",
                ruleName="Missing '-> []' cast on JSON-string column",
                severity="error",
                category="Cortex Parser Conformance",
                message=f"'{fn}({col}, ...)' passes a JSON-string column to an array function without the '-> []' cast. The Cortex parser rejects this with a type mismatch",
                recommendation=f"Cast the column first: {fn}({col} -> [], ...). For nested object access use {col} -> field_name",
                codeSnippet=f"{fn}({col} -> [], ...)",
                line=col_line,
            ))
    return violations


_ERR_018 = ValidationRule(
    id="ERR-018",
    name="Missing '-> []' cast on JSON-string column passed to array function",
    severity="error",
    category="Cortex Parser Conformance",
    pattern=re.compile(r"\b(?:arraymap|arrayfilter|arraystring|arraydistinct|array_length)\s*\("),
    message="JSON-string columns (e.g. tags, filters, detail) must be cast with '-> []' before being passed to array functions",
    recommendation="Add '-> []' to cast the JSON-string column to an array, or '-> field' to extract a nested object property. Without the cast, the Cortex parser rejects the call with a type mismatch error",
    codeSnippet="// WRONG: arraymap(tags, ...)\n// RIGHT: arraymap(tags -> [], ...)",
    appliesTo="modeling",
    customCheck=_err_018_check,
)


# ─────────────────────────────────────────────────────────────────────
# ERR-019 — Transitive underscore variable reach
# ─────────────────────────────────────────────────────────────────────

def _err_019_check(code: str, lines: List[str]) -> List[Violation]:
    violations: List[Violation] = []
    if not re.search(r"\[MODEL:", code):
        return violations
    flow = analyse_dataflow(code, lines)
    seen: set[str] = set()
    for d in flow.defs:
        if not d.isUnderscore:
            continue
        if d.name in seen:
            continue
        seen.add(d.name)
        if d.name in flow.reachable:
            continue
        violations.append(Violation(
            ruleId="ERR-019",
            ruleName="Transitive underscore variable reach",
            severity="error",
            category="Cortex Parser Conformance",
            message=f"Underscore variable '{d.name}' is defined but never reaches any xdm.* assignment, even through other _-prefixed intermediaries. Cortex rejects this on _gc_raw datasets as 'unused field'",
            recommendation=f"Either map the tail of the chain originating from '{d.name}' to an xdm.* field, or remove the dead intermediary chain entirely",
            line=d.line,
        ))
    return violations


_ERR_019 = ValidationRule(
    id="ERR-019",
    name="Transitive underscore variable reach (root-cause cascade)",
    severity="error",
    category="Cortex Parser Conformance",
    pattern=re.compile(r"\[MODEL:"),
    message="An underscore-prefixed variable is referenced by another underscore variable but is never reached from any XDM assignment",
    recommendation="If an _foo variable is only consumed by _bar, and _bar is never used in an xdm.* assignment, both will be flagged by Cortex as unused. Either map the chain's tail to an xdm.* field, or remove the dead chain. WARN-019 covers non-underscore intermediaries; this rule covers _-prefixed chains which Cortex also rejects on _gc_raw datasets",
    appliesTo="modeling",
    customCheck=_err_019_check,
)


# ─────────────────────────────────────────────────────────────────────
# ERR-020 — invented xdm.* assignment target
# ─────────────────────────────────────────────────────────────────────

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
        if path in allow:
            continue
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


# ─────────────────────────────────────────────────────────────────────
# ERR-024 — sibling reference inside a single alter stage
# ─────────────────────────────────────────────────────────────────────

def _err_024_check(code: str, lines: List[str]) -> List[Violation]:
    violations: List[Violation] = []
    if not re.search(r"\[MODEL:", code):
        return violations
    code_lines: list[str] = []
    for raw in lines:
        trimmed = raw.lstrip()
        if trimmed.startswith("//"):
            code_lines.append("")
        else:
            code_lines.append(raw.split("//", 1)[0])

    paren_depth = 0
    cur_stage = ""
    stage_of: list[str] = []
    stage_start_idx: list[int] = []
    cur_stage_start = 0
    stage_keywords = {
        "alter", "filter", "fields", "comp", "config", "target", "dedup",
        "sort", "limit", "join", "union", "bin",
    }
    for i, cp in enumerate(code_lines):
        stripped = re.sub(r"'[^']*'", "''", re.sub(r'"[^"]*"', '""', cp))
        if paren_depth == 0:
            sm = re.match(r"^\s*(?:\|\s*)?(\w+)\b", cp)
            if sm and sm.group(1) in stage_keywords:
                cur_stage = sm.group(1).lower()
                cur_stage_start = i
        stage_of.append(cur_stage)
        stage_start_idx.append(cur_stage_start)
        for ch in stripped:
            if ch == "(":
                paren_depth += 1
            elif ch == ")":
                paren_depth = max(0, paren_depth - 1)

    all_slots: list[dict] = []
    pd = 0
    for i, cp in enumerate(code_lines):
        start_depth = pd
        stripped = re.sub(r"'[^']*'", "''", re.sub(r'"[^"]*"', '""', cp))
        for ch in stripped:
            if ch == "(":
                pd += 1
            elif ch == ")":
                pd = max(0, pd - 1)
        if stage_of[i] != "alter":
            continue
        if start_depth > 0:
            continue
        xm = re.match(r"^\s*(xdm\.[\w.]+)\s*=", cp)
        um = None if xm else re.match(r"^\s*(_[A-Za-z][\w]*)\s*=", cp)
        bm = None if (xm or um) else re.match(r"^\s*([A-Za-z][\w]*)\s*=", cp)
        name = ""
        kind = "bare"
        if xm:
            name = xm.group(1)
            kind = "xdm"
        elif um:
            name = um.group(1)
            kind = "_temp"
        elif bm:
            name = bm.group(1)
            kind = "bare"
            if name in stage_keywords:
                continue
        if not name:
            continue
        if name in ("_time", "_raw_log"):
            continue
        all_slots.append({
            "name": name, "line": i + 1, "stage_start": stage_start_idx[i],
            "lhs_kind": kind, "rhs_start": i, "rhs_end": i,
        })

    slot_line_set = {s["rhs_start"] for s in all_slots}
    for s in all_slots:
        end = len(code_lines) - 1
        for j in range(s["rhs_start"] + 1, len(code_lines)):
            if stage_start_idx[j] != s["stage_start"]:
                end = j - 1
                break
            if j in slot_line_set:
                end = j - 1
                break
        s["rhs_end"] = end

    temp_defs = [s for s in all_slots if s["lhs_kind"] == "_temp"]
    reported: set[str] = set()
    for consumer in all_slots:
        siblings = [
            t for t in temp_defs
            if t["stage_start"] == consumer["stage_start"] and t["line"] != consumer["line"]
        ]
        if not siblings:
            continue
        rhs_text = "\n".join(code_lines[consumer["rhs_start"]:consumer["rhs_end"] + 1])
        rhs_body = re.sub(r"^\s*(?:xdm\.[\w.]+|_?[A-Za-z][\w]*)\s*=", "", rhs_text)
        for sib in siblings:
            escaped = re.escape(sib["name"])
            if not re.search(r"\b" + escaped + r"\b", rhs_body):
                continue
            key = f"{consumer['line']}:{sib['name']}"
            if key in reported:
                continue
            reported.add(key)
            violations.append(Violation(
                ruleId="ERR-024",
                ruleName="Sibling reference inside a single alter stage",
                severity="error",
                category="Cortex Parser Conformance",
                message=f"'{consumer['name']}' references sibling temp '{sib['name']}' defined in the same alter stage. Cortex evaluates all targets in one alter in parallel and will reject this as 'unknown field {sib['name']}'",
                recommendation=f"Split this alter stage into two: define '{sib['name']}' (and other leaf temps) in stage N, then reference it from '{consumer['name']}' in stage N+1.",
                line=consumer["line"],
            ))
    return violations


_ERR_024 = ValidationRule(
    id="ERR-024",
    name="Sibling reference inside a single alter stage",
    severity="error",
    category="Cortex Parser Conformance",
    pattern=re.compile(r"\[MODEL:"),
    message="An alter assignment target references a sibling underscore temp defined in the same alter stage. Cortex evaluates all targets in one alter in parallel and reports the reference as 'unknown field'",
    recommendation="Split the offending alter stage into two: define the leaf temp(s) in stage N and the dependent target(s) -- whether _var, bare, or xdm.* -- in stage N+1. Later stages may reference temps from prior stages but never from their own.",
    appliesTo="modeling",
    customCheck=_err_024_check,
)


# ─────────────────────────────────────────────────────────────────────
# ERR-025 — orphan temp hidden inside concat()/arraystring()
# ─────────────────────────────────────────────────────────────────────

def _err_025_check(code: str, lines: List[str]) -> List[Violation]:
    violations: List[Violation] = []
    if not re.search(r"\[MODEL:", code):
        return violations
    code_lines: list[str] = []
    for raw in lines:
        trimmed = raw.lstrip()
        if trimmed.startswith("//"):
            code_lines.append("")
        else:
            code_lines.append(raw.split("//", 1)[0])

    defs: list[dict] = []
    pd = 0
    for i, cp in enumerate(code_lines):
        start_depth = pd
        stripped = re.sub(r"'[^']*'", "''", re.sub(r'"[^"]*"', '""', cp))
        for ch in stripped:
            if ch == "(":
                pd += 1
            elif ch == ")":
                pd = max(0, pd - 1)
        if start_depth > 0:
            continue
        m = re.match(r"^\s*(_[A-Za-z][\w]*)\s*=", cp)
        if not m:
            continue
        name = m.group(1)
        if name in ("_time", "_raw_log"):
            continue
        defs.append({"name": name, "line": i + 1})
    if not defs:
        return violations
    full_text = "\n".join(code_lines)

    def is_inside_hiding_fn(abs_start: int) -> bool:
        before = full_text[:abs_start]
        depth = 0
        k = len(before) - 1
        while k >= 0:
            ch = before[k]
            if ch == ")":
                depth += 1
            elif ch == "(":
                if depth == 0:
                    head = before[:k]
                    fm = re.search(r"([A-Za-z_][\w]*)\s*$", head)
                    if not fm:
                        return False
                    fname = fm.group(1).lower()
                    if fname in ("concat", "arraystring"):
                        return True
                    return is_inside_hiding_fn(k)
                depth -= 1
            k -= 1
        return False

    line_offsets: list[int] = []
    off = 0
    for ln in code_lines:
        line_offsets.append(off)
        off += len(ln) + 1

    for d in defs:
        escaped = re.escape(d["name"])
        regex = re.compile(r"\b" + escaped + r"\b")
        refs: list[dict] = []
        for m in regex.finditer(full_text):
            line_idx = 0
            for li, lo in enumerate(line_offsets):
                if lo <= m.start():
                    line_idx = li
                else:
                    break
            if line_idx + 1 == d["line"]:
                continue
            refs.append({"abs_start": m.start(), "line": line_idx + 1})
        if not refs:
            continue
        all_hidden = all(is_inside_hiding_fn(r["abs_start"]) for r in refs)
        if not all_hidden:
            continue
        example = refs[0]
        violations.append(Violation(
            ruleId="ERR-025",
            ruleName="Orphan temp hidden inside concat() / arraystring() body",
            severity="error",
            category="Cortex Parser Conformance",
            message=f"'{d['name']}' is only referenced inside concat()/arraystring() bodies (e.g. line {example['line']}). Cortex's unused-field tracer will report it as 'unused field' on _gc_raw datasets",
            recommendation=f"Inline the derivation of '{d['name']}' directly into the concat()/arraystring() call, OR drain '{d['name']}' through a bareword identity assignment to an xdm.* field before the consumer.",
            line=d["line"],
        ))
    return violations


_ERR_025 = ValidationRule(
    id="ERR-025",
    name="Orphan temp hidden inside concat() / arraystring() body",
    severity="error",
    category="Cortex Parser Conformance",
    pattern=re.compile(r"\[MODEL:"),
    message="An underscore-prefixed temp's only consumer is inside a concat() or arraystring() body. Cortex's unused-field tracer does not follow references into these function bodies and will reject the temp as 'unused field'",
    recommendation="Either inline the derivation directly into the concat()/arraystring() call site (eliminating the temp entirely), or drain the temp through a bareword identity assignment to an xdm.* field before the concat()/arraystring() consumer.",
    appliesTo="modeling",
    customCheck=_err_025_check,
)


# ─────────────────────────────────────────────────────────────────────
# SUG-014 — ServiceAccount mapped as IDENTITY_TYPE_USER
# ─────────────────────────────────────────────────────────────────────

def _sug_014_check(code: str, lines: List[str]) -> List[Violation]:
    violations: List[Violation] = []
    if not re.search(r"\[MODEL:", code):
        return violations
    pattern = re.compile(
        r"[Ss]ervice\s*[Aa]ccount.*IDENTITY_TYPE_USER|IDENTITY_TYPE_USER.*[Ss]ervice\s*[Aa]ccount"
    )
    for i, line in enumerate(lines):
        trimmed = line.lstrip()
        if trimmed.startswith("//"):
            continue
        code_part = trimmed.split("//", 1)[0]
        if pattern.search(code_part):
            violations.append(Violation(
                ruleId="SUG-014",
                ruleName="ServiceAccount mapped as IDENTITY_TYPE_USER",
                severity="suggestion",
                category="Data Quality",
                message="A ServiceAccount identity is mapped to IDENTITY_TYPE_USER. Service accounts are machine identities and should use IDENTITY_TYPE_MACHINE for accurate classification",
                recommendation='Change the mapping: "ServiceAccount" -> XDM_CONST.IDENTITY_TYPE_MACHINE',
                line=i + 1,
            ))
    return violations


_SUG_014 = ValidationRule(
    id="SUG-014",
    name="ServiceAccount mapped as IDENTITY_TYPE_USER",
    severity="suggestion",
    category="Data Quality",
    pattern=re.compile(r"identity_type"),
    message="ServiceAccount or service account identities should typically use IDENTITY_TYPE_MACHINE, not IDENTITY_TYPE_USER",
    recommendation="Map service accounts, system accounts, and machine identities to XDM_CONST.IDENTITY_TYPE_MACHINE for accurate identity classification",
    codeSnippet='xdm.source.user.identity_type = if(\n    _user_type = "ServiceAccount", XDM_CONST.IDENTITY_TYPE_MACHINE,\n    _user_type = "User", XDM_CONST.IDENTITY_TYPE_USER,\n    XDM_CONST.IDENTITY_TYPE_UNKNOWN),',
    appliesTo="modeling",
    customCheck=_sug_014_check,
)


# ─────────────────────────────────────────────────────────────────────
# ERR-026 — Duplicate [MODEL:] header
# ─────────────────────────────────────────────────────────────────────

def _err_026_check(code: str, lines: List[str]) -> List[Violation]:
    violations: List[Violation] = []
    if not re.search(r"\[MODEL:", code):
        return violations

    def parse_tuple(header: str):
        inside = re.search(r"\[MODEL:\s*([^\]]*)\]", header, re.IGNORECASE)
        if not inside:
            return None
        body = inside.group(1)
        ds_match = re.search(r'\bdataset\s*=\s*"?([A-Za-z_][\w]*)"?', body, re.IGNORECASE)
        if not ds_match:
            return None
        md_match = re.search(r'\bmodel\s*=\s*"?([A-Za-z_][\w]*)"?', body, re.IGNORECASE)
        return {
            "dataset": ds_match.group(1).lower(),
            "model": (md_match.group(1) if md_match else "").lower(),
        }

    headers: list[dict] = []
    for i, line in enumerate(lines):
        trimmed = line.lstrip()
        if trimmed.startswith("//"):
            continue
        if not re.match(r"^\[MODEL:", trimmed, re.IGNORECASE):
            continue
        t = parse_tuple(trimmed)
        if not t:
            continue
        headers.append({"line": i + 1, "tuple": t})
    if len(headers) < 2:
        return violations
    first_seen: dict[str, int] = {}
    for h in headers:
        key = f"{h['tuple']['dataset']}|{h['tuple']['model']}"
        prev = first_seen.get(key)
        if prev is None:
            first_seen[key] = h["line"]
            continue
        tuple_str = (
            f"(dataset={h['tuple']['dataset']}, model={h['tuple']['model']})"
            if h["tuple"]["model"]
            else f"(dataset={h['tuple']['dataset']})"
        )
        violations.append(Violation(
            ruleId="ERR-026",
            ruleName="Duplicate [MODEL:] header for the same (dataset, model) tuple",
            severity="error",
            category="Cortex Parser Conformance",
            message=f"[MODEL: ...] header on line {h['line']} repeats the {tuple_str} tuple already declared on line {prev}. Cortex rejects multiple MODEL blocks for the same (dataset, model) per file; merge this header's content into the earlier MODEL block as another `;`-terminated pipeline",
            recommendation=f"Delete the [MODEL:] header on line {h['line']} and append its body (`call ... | filter ... | alter ...;`) to the MODEL block opened on line {prev}. If the two pipelines genuinely model different views of the dataset, distinguish them with a `model=` qualifier (e.g. model=Audit vs model=Network) so the (dataset, model) tuples are unique",
            line=h["line"],
        ))
    return violations


_ERR_026 = ValidationRule(
    id="ERR-026",
    name="Duplicate [MODEL:] header for the same (dataset, model) tuple",
    severity="error",
    category="Cortex Parser Conformance",
    pattern=re.compile(r"\[MODEL:"),
    message="Two or more [MODEL:] headers in this file resolve to the same (dataset, model) tuple. Cortex permits exactly one MODEL block per (dataset, model) per file; multiple branches of work on the same dataset must live as separate `;`-terminated pipelines INSIDE a single MODEL block",
    recommendation="Delete the duplicate [MODEL: dataset=...] header(s) and place the daemon / event-shape branches as `;`-terminated pipelines inside the single remaining MODEL block. Each pipeline can open with `call shared_header | filter ... | alter ...;`. See Pattern 10 in PRIVATE_DOCS/data_model_rule_building_guide.md (EfficientIP DDI worked example) and the BeyondTrust PRA / ESXi exemplars in PRIVATE_DOCS/all_modeling_rules.txt",
    codeSnippet='[MODEL: dataset = vendor_raw]\n\ncall vendor_common_header\n| filter _syslog_proc = "named"\n| alter ... ;\n\ncall vendor_common_header\n| filter _syslog_proc = "sshd"\n| alter ... ;',
    appliesTo="modeling",
    customCheck=_err_026_check,
)


# ─────────────────────────────────────────────────────────────────────
# SUG-017 / SUG-018 — Repeated alter content (Pattern 10 candidate)
# ─────────────────────────────────────────────────────────────────────

_SHARED_LINE_THRESHOLD = 18


def _sug_strip_line_comment(line: str) -> str:
    in_str = False
    i = 0
    while i < len(line) - 1:
        if in_str and line[i] == "\\":
            i += 2
            continue
        if line[i] == '"':
            in_str = not in_str
            i += 1
            continue
        if not in_str and line[i] == "/" and line[i + 1] == "/":
            return line[:i]
        i += 1
    return line


def _extract_alter_lines(body_lines: List[str]) -> list[str]:
    out: list[str] = []
    in_alter = False
    stage_known = False
    stages = known_xql_stages()
    for raw in body_lines:
        no_comment = _sug_strip_line_comment(raw)
        trimmed = no_comment.strip()
        stage_match = re.match(r"^\s*(?:\|\s*)?(\w+)\b", no_comment)
        looks_like_stage_start = stage_match and (
            re.match(r"^\s*\|\s*\w+", no_comment) is not None or not stage_known
        )
        if looks_like_stage_start and stage_match:
            word = stage_match.group(1).lower()
            if word in stages:
                in_alter = word == "alter"
                stage_known = True
                inline = re.sub(r"^\s*(?:\|\s*)?\w+\b", "", no_comment).strip()
                if in_alter and inline:
                    norm = re.sub(r"\s+", " ", inline)
                    norm = re.sub(r"[,;]+$", "", norm).strip()
                    if norm:
                        out.append(norm)
                continue
        if not in_alter:
            continue
        if not trimmed or trimmed.startswith("//"):
            continue
        norm = re.sub(r"\s+", " ", trimmed)
        norm = re.sub(r"[,;]+$", "", norm).strip()
        if norm:
            out.append(norm)
    return out


def _sug_017_check(code: str, lines: List[str]) -> List[Violation]:
    violations: List[Violation] = []
    if not re.search(r"\[MODEL:", code):
        return violations
    blocks: list[dict] = []
    for i, line in enumerate(lines):
        trimmed = line.lstrip()
        if trimmed.startswith("//"):
            continue
        if re.match(r"^\[MODEL:", trimmed):
            blocks.append({"kind": "MODEL", "line": i + 1})
        elif re.match(r"^\[RULE:", trimmed):
            blocks.append({"kind": "RULE", "line": i + 1})
    model_blocks = [b for b in blocks if b["kind"] == "MODEL"]
    if not model_blocks:
        return violations

    def split_pipelines(body_abs_start: int, body_lines: list[str]) -> list[dict]:
        pipelines: list[dict] = []
        buffer: list[str] = []
        pipeline_anchor = None
        depth = 0
        in_string = False
        for li, raw in enumerate(body_lines):
            no_comment = _sug_strip_line_comment(raw)
            trimmed = no_comment.strip()
            if pipeline_anchor is None and trimmed:
                pipeline_anchor = body_abs_start + li + 1
            buffer.append(raw)
            ci = 0
            while ci < len(no_comment):
                ch = no_comment[ci]
                if in_string:
                    if ch == "\\":
                        ci += 2
                        continue
                    if ch == '"':
                        in_string = False
                    ci += 1
                    continue
                if ch == '"':
                    in_string = True
                    ci += 1
                    continue
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth = max(0, depth - 1)
                elif ch == ";" and depth == 0:
                    if pipeline_anchor is not None:
                        pipelines.append({"anchorLine": pipeline_anchor, "bodyLines": list(buffer)})
                    buffer = []
                    pipeline_anchor = None
                ci += 1
        if any(l.strip() for l in buffer) and pipeline_anchor is not None:
            pipelines.append({"anchorLine": pipeline_anchor, "bodyLines": list(buffer)})
        return pipelines

    for mi, mb in enumerate(model_blocks):
        start = mb["line"]
        end = len(lines)
        for b in blocks:
            if b["line"] > start and b["line"] < end + 1:
                end = b["line"] - 1
        body = lines[start:end]
        pipelines = split_pipelines(start, body)
        if len(pipelines) < 2:
            continue
        alter_by = [_extract_alter_lines(p["bodyLines"]) for p in pipelines]
        counts_by = []
        for ll in alter_by:
            mp: dict[str, int] = {}
            for l in ll:
                mp[l] = mp.get(l, 0) + 1
            counts_by.append(mp)
        for j in range(1, len(counts_by)):
            best_i = -1
            max_shared = 0
            for i in range(j):
                a = counts_by[i]
                b = counts_by[j]
                shared = 0
                for k, va in a.items():
                    vb = b.get(k)
                    if vb:
                        shared += min(va, vb)
                if shared >= _SHARED_LINE_THRESHOLD and shared > max_shared:
                    best_i = i
                    max_shared = shared
            if best_i == -1:
                continue
            anchor_a = pipelines[best_i]["anchorLine"]
            anchor_b = pipelines[j]["anchorLine"]
            violations.append(Violation(
                ruleId="SUG-017",
                ruleName="Repeated alter content across pipelines in a MODEL block (Pattern 10 candidate)",
                severity="suggestion",
                category="Code Reuse",
                message=f"MODEL pipelines starting at line {anchor_a} and line {anchor_b} share {max_shared} lines of identical alter content (threshold: {_SHARED_LINE_THRESHOLD}). Consider factoring the shared logic into a [RULE:] block and calling it from each pipeline (Pattern 10)",
                recommendation="Move the duplicated alter content into a single [RULE: vendor_common_header] block at the top of the file, then replace the duplicated lines in each pipeline with `call vendor_common_header`. See Pattern 10 in PRIVATE_DOCS/data_model_rule_building_guide.md and the EfficientIP DDI worked example",
                line=anchor_b,
            ))
    return violations


_SUG_017 = ValidationRule(
    id="SUG-017",
    name="Repeated alter content across pipelines in a MODEL block (Pattern 10 candidate)",
    severity="suggestion",
    category="Code Reuse",
    pattern=re.compile(r"\[MODEL:"),
    message="Two or more `;`-terminated pipelines inside a single [MODEL:] block share a large block of identical alter content -- the documented threshold for refactoring into a [RULE:] + call (Pattern 10)",
    recommendation="Factor the duplicated header parsing / common-field extraction into a single [RULE: name] block at the top of the file, then `call name` from each pipeline. See Pattern 10 in PRIVATE_DOCS/data_model_rule_building_guide.md (worked example: efficientip_syslog_header)",
    appliesTo="modeling",
    customCheck=_sug_017_check,
)


def _sug_018_check(code: str, lines: List[str]) -> List[Violation]:
    violations: List[Violation] = []
    if not re.search(r"\[RULE:", code):
        return violations
    blocks: list[dict] = []
    for i, line in enumerate(lines):
        trimmed = line.lstrip()
        if trimmed.startswith("//"):
            continue
        rm = re.match(r"^\[RULE:\s*([^\]\s,]+)", trimmed)
        if rm:
            blocks.append({"kind": "RULE", "line": i + 1, "name": rm.group(1)})
            continue
        if re.match(r"^\[MODEL:", trimmed):
            blocks.append({"kind": "MODEL", "line": i + 1, "name": None})
    rule_blocks = [b for b in blocks if b["kind"] == "RULE"]
    if len(rule_blocks) < 2:
        return violations
    bodies: list[list[str]] = []
    for rb in rule_blocks:
        start = rb["line"]
        end = len(lines)
        for b in blocks:
            if b["line"] > start and b["line"] < end + 1:
                end = b["line"] - 1
        bodies.append(lines[start:end])
    alter_by = [_extract_alter_lines(b) for b in bodies]
    counts_by = []
    for ll in alter_by:
        mp: dict[str, int] = {}
        for l in ll:
            mp[l] = mp.get(l, 0) + 1
        counts_by.append(mp)
    for j in range(1, len(counts_by)):
        best_i = -1
        max_shared = 0
        for i in range(j):
            a = counts_by[i]
            b = counts_by[j]
            shared = 0
            for k, va in a.items():
                vb = b.get(k)
                if vb:
                    shared += min(va, vb)
            if shared >= _SHARED_LINE_THRESHOLD and shared > max_shared:
                best_i = i
                max_shared = shared
        if best_i == -1:
            continue
        earlier = rule_blocks[best_i]
        later = rule_blocks[j]
        en = earlier.get("name") or f"(unnamed @ line {earlier['line']})"
        ln = later.get("name") or f"(unnamed @ line {later['line']})"
        violations.append(Violation(
            ruleId="SUG-018",
            ruleName="Repeated alter content across [RULE:] blocks in the same file",
            severity="suggestion",
            category="Code Reuse",
            message=f"[RULE: {ln}] (line {later['line']}) shares {max_shared} lines of identical alter content with [RULE: {en}] (line {earlier['line']}) (threshold: {_SHARED_LINE_THRESHOLD}). Either merge the two RULEs or factor the shared content into a third [RULE:] that both `call`",
            recommendation=f"Inspect [RULE: {en}] and [RULE: {ln}]. If they are genuinely two versions of the same logic, merge them. Otherwise extract the duplicated alter content into a [RULE: {en}_base] block and replace the duplicated lines in each with `call {en}_base`",
            line=later["line"],
        ))
    return violations


_SUG_018 = ValidationRule(
    id="SUG-018",
    name="Repeated alter content across [RULE:] blocks in the same file",
    severity="suggestion",
    category="Code Reuse",
    pattern=re.compile(r"\[RULE:"),
    message="Two or more `[RULE:]` blocks in this file share a large block of identical alter content -- the right refactor is usually to merge the rules or factor a shared base RULE that both `call`",
    recommendation="Either merge the two near-duplicate RULEs into one, or extract their common alter content into a third [RULE: shared_base] block and have each of the two RULEs `call shared_base` before adding their own variant-specific lines",
    appliesTo="modeling",
    customCheck=_sug_018_check,
)


# ─────────────────────────────────────────────────────────────────────
# Registry — source-file order matters for cascade suppression
# ─────────────────────────────────────────────────────────────────────

VALIDATION_RULES: List[ValidationRule] = [
    # ERR-001..ERR-007
    _ERR_001, _ERR_002, _ERR_003, _ERR_004, _ERR_005, _ERR_006, _ERR_007,
    # WARN-001..WARN-010
    _WARN_001, _WARN_002, _WARN_003, _WARN_004, _WARN_005, _WARN_006,
    _WARN_007, _WARN_008, _WARN_009, _WARN_010,
    _WARN_011,
    # INFO-001..INFO-006
    _INFO_001, _INFO_002, _INFO_003, _INFO_004, _INFO_005, _INFO_006,
    # SUG-001..SUG-010
    _SUG_001, _SUG_002, _SUG_003, _SUG_004, _SUG_005,
    _SUG_006, _SUG_007, _SUG_008, _SUG_009, _SUG_010,
    # WARN-012..WARN-015 + INFO-007 + ERR-008 + WARN-016..WARN-018 + INFO-008/009
    _WARN_012, _WARN_013, _WARN_014, _WARN_015,
    _INFO_007,
    _ERR_008,
    _WARN_016, _WARN_017, _WARN_018,
    _INFO_008, _INFO_009,
    # ERR-009, ERR-010, WARN-019, WARN-020, WARN-021
    _ERR_009, _ERR_010,
    _WARN_019, _WARN_020, _WARN_021,
    # INFO-010 + WARN-022..WARN-028 + ERR-011 + INFO-011 + SUG-013
    _INFO_010,
    _WARN_022, _WARN_023, _WARN_024, _WARN_025,
    _WARN_026, _WARN_027, _WARN_028,
    _ERR_011,
    _INFO_011,
    _SUG_013,
    # WARN-029, WARN-030, WARN-035, WARN-036, WARN-031, WARN-032
    _WARN_029, _WARN_030,
    _WARN_035, _WARN_036,
    _WARN_031, _WARN_032,
    # ERR-012..ERR-019
    _ERR_012, _ERR_013, _ERR_014, _ERR_015, _ERR_016,
    _ERR_017, _ERR_018, _ERR_019,
    # ERR-020, ERR-024, ERR-025
    _ERR_020, _ERR_024, _ERR_025,
    # INFO-012 is emitted by the engine, NOT registered as a rule.
    # SUG-014, ERR-026, SUG-017, SUG-018
    _SUG_014, _ERR_026,
    _SUG_017, _SUG_018,
]
