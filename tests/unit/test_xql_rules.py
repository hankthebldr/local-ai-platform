# SPDX-FileCopyrightText: ohno llc
# SPDX-License-Identifier: AGPL-3.0-or-later
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
    """A minimal valid modeling rule should produce READY-TO-DEPLOY."""
    code = "[MODEL: dataset = v_p_raw]\nalter xdm.event.id = id"
    result = analyse(rule=code, kind="modeling")
    assert result["verdict"] == "READY-TO-DEPLOY"
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
