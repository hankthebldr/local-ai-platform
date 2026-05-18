"""
Test fixtures for the XQL/XDM rules engine port.

Parametrised one-fixture-per-rule pattern. Each rule's fixture has:
    - `code`     — minimal failing snippet
    - `rule_id`  — expected fired rule ID
    - `kind`     — "modeling" or "parsing"
    - `negative` — optional clean snippet that must NOT trigger the rule

Phase 3a (this commit): covers the 9 rules ported in the initial port
batch (ERR-001..007, ERR-016, ERR-024). Phase 3b will add fixtures for
the remaining ~75 rules as they land.

Derived from gocortex-xql-ide/server/data/rules-engine*.test.ts (AGPL-3.0).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

# The plugin dir is hyphenated (`plugins/xdm-toolkit/`), which Python imports
# can't traverse. Load the tools package by path the way the runtime does.
_TOOLS_DIR = Path(__file__).resolve().parents[2] / "plugins" / "xdm-toolkit" / "tools"


def _load_module(name: str, file: str):
    full_name = f"_xql_test_{name}"
    if full_name in sys.modules:
        return sys.modules[full_name]
    spec = importlib.util.spec_from_file_location(
        full_name,
        _TOOLS_DIR / file,
        submodule_search_locations=[str(_TOOLS_DIR)],
    )
    mod = importlib.util.module_from_spec(spec)
    # Register a synthetic parent package so relative imports inside the module work.
    parent_name = "_xql_test_pkg"
    if parent_name not in sys.modules:
        parent_spec = importlib.util.spec_from_loader(parent_name, loader=None)
        parent = importlib.util.module_from_spec(parent_spec)
        parent.__path__ = [str(_TOOLS_DIR)]
        sys.modules[parent_name] = parent
    # Make submodule imports (._types, ._schema, ._engine, ._rules, .analyse_xql) resolvable.
    mod.__package__ = parent_name
    sys.modules[f"{parent_name}.{name}"] = mod
    sys.modules[full_name] = mod
    spec.loader.exec_module(mod)
    return mod


# Pre-load the support modules so relative imports inside analyse_xql resolve.
for _name, _file in [
    ("_types", "_types.py"),
    ("_schema", "_schema.py"),
    ("_rules", "_rules.py"),
    ("_engine", "_engine.py"),
    ("analyse_xql", "analyse_xql.py"),
    ("validate_xql", "validate_xql.py"),
]:
    _load_module(_name, _file)

analyse = sys.modules["_xql_test_pkg.analyse_xql"].execute


def _fired(result: dict, rule_id: str) -> bool:
    """Did the given rule fire in the analyser output?"""
    for v in result["violations"]:
        if v["ruleId"] == rule_id:
            return True
    for v in result["suggestions"]:
        if v["ruleId"] == rule_id:
            return True
    return False


# ── ERR-001..ERR-005 — Required Fields (parsing) ──────────────────────


@pytest.mark.parametrize(
    "rule_id,bad,good",
    [
        (
            "ERR-001",
            '[INGEST: product="X", target_dataset="x_raw"]\n_time = to_timestamp(t, "%Y-%m-%d")',
            '[INGEST: vendor="V", product="X", target_dataset="x_raw"]\n_time = to_timestamp(t, "%Y-%m-%d")',
        ),
        (
            "ERR-002",
            '[INGEST: vendor="V", target_dataset="x_raw"]\n_time = to_timestamp(t, "%Y-%m-%d")',
            '[INGEST: vendor="V", product="X", target_dataset="x_raw"]\n_time = to_timestamp(t, "%Y-%m-%d")',
        ),
        (
            "ERR-003",
            '[INGEST: vendor="V", product="X"]\n_time = to_timestamp(t, "%Y-%m-%d")',
            '[INGEST: vendor="V", product="X", target_dataset="x_raw"]\n_time = to_timestamp(t, "%Y-%m-%d")',
        ),
        (
            "ERR-005",
            '[INGEST: vendor="V", product="X", target_dataset="x_raw"]\nalter x = y',
            '[INGEST: vendor="V", product="X", target_dataset="x_raw"]\n_time = to_timestamp(t, "%Y-%m-%d")',
        ),
    ],
)
def test_parsing_required_fields(rule_id: str, bad: str, good: str) -> None:
    """ERR-001/002/003/005: parsing-rule required INGEST fields."""
    assert _fired(
        analyse(rule=bad, kind="parsing"), rule_id
    ), f"{rule_id} should fire on bad snippet"
    assert not _fired(
        analyse(rule=good, kind="parsing"), rule_id
    ), f"{rule_id} should NOT fire on good snippet"


# ── ERR-004 — Missing dataset in MODEL header ─────────────────────────


def test_err_004_missing_dataset() -> None:
    bad = "[MODEL: ]\nalter xdm.event.id = id"
    good = "[MODEL: dataset = v_p_raw]\nalter xdm.event.id = id"
    assert _fired(analyse(rule=bad, kind="modeling"), "ERR-004")
    assert not _fired(analyse(rule=good, kind="modeling"), "ERR-004")


# ── ERR-006 — Invalid XDM category ────────────────────────────────────


def test_err_006_unknown_category() -> None:
    """An xdm.<unknown>.<field> path should fire ERR-006."""
    bad = "[MODEL: dataset = v_p_raw]\nalter xdm.bogus.field = x"
    assert _fired(analyse(rule=bad, kind="modeling"), "ERR-006")


def test_err_006_known_category_clean() -> None:
    """Valid xdm.event.* path should not trigger ERR-006."""
    good = "[MODEL: dataset = v_p_raw]\nalter xdm.event.id = x"
    assert not _fired(analyse(rule=good, kind="modeling"), "ERR-006")


# ── ERR-007 — Unknown XQL function ────────────────────────────────────


def test_err_007_unknown_function() -> None:
    bad = "[MODEL: dataset = v_p_raw]\nalter xdm.event.id = fakefunc(x)"
    assert _fired(analyse(rule=bad, kind="modeling"), "ERR-007")


def test_err_007_known_function_clean() -> None:
    good = "[MODEL: dataset = v_p_raw]\nalter xdm.event.id = to_string(x)"
    assert not _fired(analyse(rule=good, kind="modeling"), "ERR-007")


# ── ERR-016 — Invented xdm.event.start_time / xdm.event.end_time ──────


def test_err_016_invented_start_time() -> None:
    """xdm.event.start_time doesn't exist; should fire ERR-016."""
    bad = "[MODEL: dataset = v_p_raw]\nalter xdm.event.start_time = to_number(_ts_ms)"
    assert _fired(analyse(rule=bad, kind="modeling"), "ERR-016")


def test_err_016_invented_end_time() -> None:
    """xdm.event.end_time doesn't exist either."""
    bad = "[MODEL: dataset = v_p_raw]\nalter xdm.event.end_time = to_number(_end_ms)"
    assert _fired(analyse(rule=bad, kind="modeling"), "ERR-016")


def test_err_016_clean_duration() -> None:
    """xdm.event.duration is the canonical replacement and should not fire ERR-016."""
    good = (
        "[MODEL: dataset = v_p_raw]\n"
        "alter xdm.event.duration = to_integer(subtract(to_number(_end_ms), to_number(_start_ms)))"
    )
    assert not _fired(analyse(rule=good, kind="modeling"), "ERR-016")


# ── ERR-020 — Invented xdm.* assignment target ────────────────────────


def test_err_020_invented_leaf() -> None:
    """An xdm.event.<bogus_leaf> on its own assignment line should fire ERR-020.

    ERR-020's regex anchors on the LHS at line start; multi-line alter stages
    (the canonical format) put each assignment on its own line.
    """
    bad = (
        "[MODEL: dataset = v_p_raw]\n"
        "alter\n"
        "    xdm.event.totally_made_up_leaf_field = x"
    )
    result = analyse(rule=bad, kind="modeling")
    assert _fired(result, "ERR-020"), f"ERR-020 should fire; got {result['summary']}"


def test_err_020_real_leaf_clean() -> None:
    """A real XDM leaf path should not fire ERR-020."""
    good = "[MODEL: dataset = v_p_raw]\n" "alter\n" "    xdm.event.id = id"
    assert not _fired(analyse(rule=good, kind="modeling"), "ERR-020")


# ── End-to-end: verdict + scoring ─────────────────────────────────────


def test_verdict_clean_rule() -> None:
    """A reasonably-complete modeling rule should produce READY-TO-DEPLOY.

    Phase 3b note: now that 84 rules are active the bar is higher — we need
    observer.vendor/product, event.type/outcome/description plus a trailing
    semicolon to avoid the data-quality WARN/INFO findings that block 90+.
    """
    code = (
        "[MODEL: dataset = v_p_raw]\n"
        "alter\n"
        "    xdm.event.id = coalesce(id, _id),\n"
        "    xdm.event.type = XDM_CONST.EVENT_TYPE_NETWORK,\n"
        "    xdm.event.outcome = XDM_CONST.OUTCOME_SUCCESS,\n"
        '    xdm.event.description = concat("event ", id),\n'
        '    xdm.observer.vendor = "vendor_name",\n'
        '    xdm.observer.product = "product_name";\n'
    )
    result = analyse(rule=code, kind="modeling")
    assert result["verdict"] == "READY-TO-DEPLOY", (
        f"got verdict={result['verdict']} score={result['score']} "
        f"summary={result['summary']}"
    )
    assert result["score"] >= 90


def test_verdict_blocker_rule() -> None:
    """A rule missing the MODEL dataset should produce NEEDS-FIXES."""
    code = "[MODEL: ]\nalter xdm.event.id = id"
    result = analyse(rule=code, kind="modeling")
    assert result["verdict"] in {"NEEDS-FIXES", "REWRITE-RECOMMENDED"}


def test_legacy_shim_translation() -> None:
    """The legacy validate_xql shim should translate severities correctly."""
    legacy = sys.modules["_xql_test_pkg.validate_xql"].execute
    code = "[MODEL: ]\nalter xdm.event.id = id"
    result = legacy(rule=code)
    assert "verdict" in result
    assert "issues" in result
    assert any(
        i["severity"] == "BLOCKER" for i in result["issues"]
    ), "ERR-004 (missing dataset) should map to BLOCKER in legacy shape"


# ═════════════════════════════════════════════════════════════════════
# Phase 3b — new fixtures for the bulk of ports
# ═════════════════════════════════════════════════════════════════════


# ── ERR-008..ERR-019, 024..026 (heavy customCheck ports) ──────────────


def test_err_008_invalid_json_at_path() -> None:
    bad = '[MODEL: dataset = v_p_raw]\n_ts = json_extract_scalar(_raw_log, "$.@timestamp");'
    good = "[MODEL: dataset = v_p_raw]\n_ts = json_extract_scalar(_raw_log, \"$['@timestamp']\");"
    assert _fired(analyse(rule=bad, kind="modeling"), "ERR-008")
    assert not _fired(analyse(rule=good, kind="modeling"), "ERR-008")


def test_err_009_missing_semicolon() -> None:
    bad = "[MODEL: dataset = v_p_raw]\nalter\n    xdm.event.id = id"
    good = "[MODEL: dataset = v_p_raw]\nalter\n    xdm.event.id = id;"
    assert _fired(analyse(rule=bad, kind="modeling"), "ERR-009")
    assert not _fired(analyse(rule=good, kind="modeling"), "ERR-009")


def test_err_010_trailing_comma_before_semi() -> None:
    bad = "[MODEL: dataset = v_p_raw]\nalter\n    xdm.event.id = id, ;"
    assert _fired(analyse(rule=bad, kind="modeling"), "ERR-010")


def test_err_011_self_reference() -> None:
    bad = (
        "[MODEL: dataset = v_p_raw]\n"
        "alter\n"
        "    xdm.target.ipv4 = coalesce(xdm.target.ipv4, _client_ip);"
    )
    assert _fired(analyse(rule=bad, kind="modeling"), "ERR-011")


def test_err_012_infix_arithmetic() -> None:
    bad = (
        "[MODEL: dataset = v_p_raw]\n"
        "| alter\n"
        "    _duration_ms = _end_ms - _start_ms;\n"
    )
    assert _fired(analyse(rule=bad, kind="modeling"), "ERR-012")


def test_err_013_compound_null_guard() -> None:
    bad = (
        "[MODEL: dataset = v_p_raw]\n"
        "| alter\n"
        "    x = if(a != null and b != null, subtract(a, b));\n"
    )
    assert _fired(analyse(rule=bad, kind="modeling"), "ERR-013")


def test_err_014_bareword_bool_on_string() -> None:
    bad = (
        "[MODEL: dataset = v_p_raw]\n"
        '| filter json_extract_scalar(_raw_log, "$.external") = true;\n'
    )
    assert _fired(analyse(rule=bad, kind="modeling"), "ERR-014")


def test_err_015_to_number_into_int_field() -> None:
    bad = (
        "[MODEL: dataset = v_p_raw]\n"
        "alter\n"
        "    xdm.event.duration = to_number(_duration_ms);"
    )
    good = (
        "[MODEL: dataset = v_p_raw]\n"
        "alter\n"
        "    xdm.event.duration = to_integer(to_number(_duration_ms));"
    )
    assert _fired(analyse(rule=bad, kind="modeling"), "ERR-015")
    assert not _fired(analyse(rule=good, kind="modeling"), "ERR-015")


def test_err_017_bare_at_element_passthrough() -> None:
    bad = (
        "[MODEL: dataset = v_p_raw]\n"
        "alter\n"
        '    _participants = arraymap(participants, "@element");\n'
    )
    assert _fired(analyse(rule=bad, kind="modeling"), "ERR-017")


def test_err_018_missing_array_cast() -> None:
    bad = (
        "[MODEL: dataset = v_p_raw]\n"
        '| alter _tags = arraymap(tags, json_extract_scalar("@element", "$.n"));\n'
    )
    good = (
        "[MODEL: dataset = v_p_raw]\n"
        '| alter _tags = arraymap(tags -> [], json_extract_scalar("@element", "$.n"));\n'
    )
    assert _fired(analyse(rule=bad, kind="modeling"), "ERR-018")
    assert not _fired(analyse(rule=good, kind="modeling"), "ERR-018")


def test_err_019_transitive_unreached_underscore() -> None:
    """An _foo defined but never reaching any xdm.* should fire ERR-019."""
    bad = (
        "[MODEL: dataset = v_p_raw]\n"
        "alter\n"
        '    _dead_temp = json_extract_scalar(_raw_log, "$.x"),\n'
        "    xdm.event.id = id;\n"
    )
    assert _fired(analyse(rule=bad, kind="modeling"), "ERR-019")


def test_err_024_sibling_temp_reference() -> None:
    """Run customCheck directly so we don't get drowned out by the cascade
    suppressor (ERR-019 on the same line would otherwise win when both
    underscore temps fail to reach an xdm.* sink)."""
    rules_mod = sys.modules["_xql_test_pkg._rules"]
    bad = (
        "[MODEL: dataset = v_p_raw]\n"
        "alter\n"
        '    _a = json_extract_scalar(_raw_log, "$.x"),\n'
        "    _b = _a,\n"
        "    xdm.event.id = _b;\n"
    )
    fired = [v.ruleId for v in rules_mod._err_024_check(bad, bad.split("\n"))]
    assert "ERR-024" in fired, f"got rules: {fired}"


def test_err_025_orphan_temp_in_concat() -> None:
    """Underscore temp only referenced inside concat() should fire ERR-025."""
    bad = (
        "[MODEL: dataset = v_p_raw]\n"
        "alter\n"
        '    _msg = json_extract_scalar(_raw_log, "$.m"),\n'
        '    xdm.event.description = concat("hi ", _msg);\n'
    )
    assert _fired(analyse(rule=bad, kind="modeling"), "ERR-025")


def test_err_026_duplicate_model_header() -> None:
    bad = (
        "[MODEL: dataset = v_p_raw]\nalter xdm.event.id = a;\n\n"
        "[MODEL: dataset = v_p_raw]\nalter xdm.event.id = b;\n"
    )
    assert _fired(analyse(rule=bad, kind="modeling"), "ERR-026")


# ── WARN-* spot-checks (positive + negative for 8 representative rules) ─


def test_warn_001_overly_broad_regex() -> None:
    bad = '[MODEL: dataset = v_p_raw]\nalter x = regextract(y, ".*");'
    good = '[MODEL: dataset = v_p_raw]\nalter x = regextract(y, "[a-z]+");'
    assert _fired(analyse(rule=bad, kind="modeling"), "WARN-001")
    assert not _fired(analyse(rule=good, kind="modeling"), "WARN-001")


def test_warn_005_json_extract_scalar_form() -> None:
    bad = '[MODEL: dataset = v_p_raw]\n_x = json_extract(_raw_log, "$.user");'
    good = '[MODEL: dataset = v_p_raw]\n_x = json_extract_scalar(_raw_log, "$.user");'
    assert _fired(analyse(rule=bad, kind="modeling"), "WARN-005")
    assert not _fired(analyse(rule=good, kind="modeling"), "WARN-005")


def test_warn_007_missing_observer_product() -> None:
    bad = "[MODEL: dataset = v_p_raw]\nalter xdm.event.id = id;"
    good = (
        "[MODEL: dataset = v_p_raw]\nalter\n"
        '    xdm.observer.product = "p",\n'
        "    xdm.event.id = id;"
    )
    assert _fired(analyse(rule=bad, kind="modeling"), "WARN-007")
    assert not _fired(analyse(rule=good, kind="modeling"), "WARN-007")


def test_warn_009_missing_no_hit() -> None:
    bad = (
        '[INGEST:vendor="V", product="P", target_dataset="x"]\n_time = current_time();'
    )
    good = '[INGEST:vendor="V", product="P", target_dataset="x", no_hit=drop]\n_time = current_time();'
    assert _fired(analyse(rule=bad, kind="parsing"), "WARN-009")
    assert not _fired(analyse(rule=good, kind="parsing"), "WARN-009")


def test_warn_014_quoted_xdm_const() -> None:
    bad = '[MODEL: dataset = v_p_raw]\nalter xdm.event.outcome = "XDM_CONST.OUTCOME_SUCCESS";'
    assert _fired(analyse(rule=bad, kind="modeling"), "WARN-014")


def test_warn_015_quoted_dataset_in_model() -> None:
    bad = '[MODEL: dataset = "v_p_raw"]\nalter xdm.event.id = id;'
    good = "[MODEL: dataset = v_p_raw]\nalter xdm.event.id = id;"
    assert _fired(analyse(rule=bad, kind="modeling"), "WARN-015")
    assert not _fired(analyse(rule=good, kind="modeling"), "WARN-015")


def test_warn_018_time_in_model_rule() -> None:
    bad = (
        "[MODEL: dataset = v_p_raw]\n_time = current_time(),\nalter xdm.event.id = id;"
    )
    assert _fired(analyse(rule=bad, kind="modeling"), "WARN-018")


def test_warn_022_arraycreate_no_null_guard() -> None:
    bad = "[MODEL: dataset = v_p_raw]\nalter xdm.source.host.ipv4_addresses = arraycreate(ip_addr);"
    good = "[MODEL: dataset = v_p_raw]\nalter xdm.source.host.ipv4_addresses = if(ip_addr != null, arraycreate(ip_addr));"
    assert _fired(analyse(rule=bad, kind="modeling"), "WARN-022")
    assert not _fired(analyse(rule=good, kind="modeling"), "WARN-022")


def test_warn_023_mitre_techniques_compat() -> None:
    bad = "[MODEL: dataset = v_p_raw]\nalter xdm.alert.mitre_techniques = t;"
    assert _fired(analyse(rule=bad, kind="modeling"), "WARN-023")


# ── INFO-* + SUG-* spot-checks ───────────────────────────────────────


def test_info_002_event_type_not_set() -> None:
    bad = "[MODEL: dataset = v_p_raw]\nalter xdm.event.id = id;"
    good = "[MODEL: dataset = v_p_raw]\nalter xdm.event.type = XDM_CONST.EVENT_TYPE_NETWORK;"
    assert _fired(analyse(rule=bad, kind="modeling"), "INFO-002")
    assert not _fired(analyse(rule=good, kind="modeling"), "INFO-002")


def test_sug_001_regex_ip_match() -> None:
    bad = '[MODEL: dataset = v_p_raw]\nalter x = if(ip ~= "10\\\\..*", "match");'
    assert _fired(analyse(rule=bad, kind="modeling"), "SUG-001")


def test_sug_004_xdm_const_for_event_type() -> None:
    bad = '[MODEL: dataset = v_p_raw]\nalter xdm.event.type = "NETWORK";'
    assert _fired(analyse(rule=bad, kind="modeling"), "SUG-004")


# ── Registry sanity: all 84 rule IDs present ──────────────────────────


def test_validation_rules_registry_complete() -> None:
    """Every rule ID we promised to port appears in VALIDATION_RULES."""
    rules_mod = sys.modules["_xql_test_pkg._rules"]
    ids = {r.id for r in rules_mod.VALIDATION_RULES}
    expected = {
        # ERR
        "ERR-001",
        "ERR-002",
        "ERR-003",
        "ERR-004",
        "ERR-005",
        "ERR-006",
        "ERR-007",
        "ERR-008",
        "ERR-009",
        "ERR-010",
        "ERR-011",
        "ERR-012",
        "ERR-013",
        "ERR-014",
        "ERR-015",
        "ERR-016",
        "ERR-017",
        "ERR-018",
        "ERR-019",
        "ERR-020",
        "ERR-024",
        "ERR-025",
        "ERR-026",
        # WARN
        "WARN-001",
        "WARN-002",
        "WARN-003",
        "WARN-004",
        "WARN-005",
        "WARN-006",
        "WARN-007",
        "WARN-008",
        "WARN-009",
        "WARN-010",
        "WARN-011",
        "WARN-012",
        "WARN-013",
        "WARN-014",
        "WARN-015",
        "WARN-016",
        "WARN-017",
        "WARN-018",
        "WARN-019",
        "WARN-020",
        "WARN-021",
        "WARN-022",
        "WARN-023",
        "WARN-024",
        "WARN-025",
        "WARN-026",
        "WARN-027",
        "WARN-028",
        "WARN-029",
        "WARN-030",
        "WARN-031",
        "WARN-032",
        "WARN-035",
        "WARN-036",
        # INFO
        "INFO-001",
        "INFO-002",
        "INFO-003",
        "INFO-004",
        "INFO-005",
        "INFO-006",
        "INFO-007",
        "INFO-008",
        "INFO-009",
        "INFO-010",
        "INFO-011",
        # SUG
        "SUG-001",
        "SUG-002",
        "SUG-003",
        "SUG-004",
        "SUG-005",
        "SUG-006",
        "SUG-007",
        "SUG-008",
        "SUG-009",
        "SUG-010",
        "SUG-013",
        "SUG-014",
        "SUG-017",
        "SUG-018",
    }
    missing = expected - ids
    assert not missing, f"missing rule IDs: {sorted(missing)}"


# ═════════════════════════════════════════════════════════════════════
# Scaffold engine tests
# ═════════════════════════════════════════════════════════════════════


def test_scaffold_pattern_a_json() -> None:
    """Pattern A: pure JSON sample produces JSON-extract scaffold."""
    scaffold = _load_module("scaffold_xql", "scaffold_xql.py")
    result = scaffold.execute(
        '{"timestamp": 1718000000000, "user": "alice", "src_ip": "10.0.0.1"}',
        vendor="acme",
        product="widget",
    )
    assert result["dominantFormat"] == "json"
    assert result["dominantPattern"] == "A"
    assert "[INGEST:" in result["parsing"]["code"]
    assert "[MODEL:" in result["modeling"]["code"]
    temp_names = {t["tempName"] for t in result["temps"]}
    # Common fields should produce a temp
    assert any(n.endswith("user") for n in temp_names)
    assert any("src_ip" in n or "ip" in n for n in temp_names)


def test_scaffold_pattern_d_text_fallback() -> None:
    """Pattern D: opaque text sample yields a minimal scaffold with _time stub."""
    scaffold = _load_module("scaffold_xql", "scaffold_xql.py")
    result = scaffold.execute("an opaque syslog-ish line with no structure")
    assert result["dominantFormat"] == "text"
    assert result["dominantPattern"] == "D"
    # parsing rule still includes a _time stub so ERR-005 doesn't fire
    assert "_time" in result["parsing"]["code"]
