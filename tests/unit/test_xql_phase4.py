# SPDX-FileCopyrightText: ohno llc
# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Phase 4 — tests for the analyse_xql_gate hook, xdm_snippets tool, and
rag_lookup tool.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock


_REPO_ROOT = Path(__file__).resolve().parents[2]
_TOOLS_DIR = _REPO_ROOT / "plugins" / "xdm-toolkit" / "tools"


# ── Helper: load hyphenated plugin tool by path ──────────────────────
def _load_tool(name: str, file: str):
    parent_name = "_xql_phase4_pkg"
    if parent_name not in sys.modules:
        parent_spec = importlib.util.spec_from_loader(parent_name, loader=None)
        parent = importlib.util.module_from_spec(parent_spec)
        parent.__path__ = [str(_TOOLS_DIR)]
        sys.modules[parent_name] = parent
    full = f"{parent_name}.{name}"
    if full in sys.modules:
        return sys.modules[full]
    spec = importlib.util.spec_from_file_location(full, _TOOLS_DIR / file)
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = parent_name
    sys.modules[full] = mod
    spec.loader.exec_module(mod)
    return mod


# Pre-load engine support so analyse_xql resolves under the same package alias.
for n, f in [
    ("_types", "_types.py"),
    ("_schema", "_schema.py"),
    ("_dataflow", "_dataflow.py"),
    ("_rules", "_rules.py"),
    ("_engine", "_engine.py"),
    ("analyse_xql", "analyse_xql.py"),
    ("xdm_snippets", "xdm_snippets.py"),
    ("rag_lookup", "rag_lookup.py"),
]:
    _load_tool(n, f)


# ──────────────────────────────────────────────────────────────────────
# xdm_snippets tool
# ──────────────────────────────────────────────────────────────────────


def test_snippets_loaded_from_phase1_corpus():
    snippets = sys.modules["_xql_phase4_pkg.xdm_snippets"]
    result = snippets.execute(query="")  # empty query — match anything in scoring
    assert (
        result["total_snippets"] == 112
    ), "Phase 1 shipped 112 snippets; this asserts the loader reads the corpus."


def test_snippets_query_matches_title_tags():
    snippets = sys.modules["_xql_phase4_pkg.xdm_snippets"]
    result = snippets.execute(query="boilerplate", top_k=3)
    assert result["matches"], "Boilerplate query should return matches"
    titles = [m["title"].lower() for m in result["matches"]]
    assert any("boilerplate" in t for t in titles)


def test_snippets_category_filter():
    snippets = sys.modules["_xql_phase4_pkg.xdm_snippets"]
    result = snippets.execute(query="model", category="Data Model Rules", top_k=5)
    assert result["matches"], "Data Model Rules category should match"
    assert all(m["category"] == "Data Model Rules" for m in result["matches"])


def test_snippets_pattern_a_hint_narrows_to_json_field_extraction():
    snippets = sys.modules["_xql_phase4_pkg.xdm_snippets"]
    result = snippets.execute(query="extract", pattern="A", top_k=5)
    assert result["matches"], "Pattern A hint should match field-extraction snippets"
    # Pattern A maps to Field Extraction / Data Model Rules categories.
    for m in result["matches"]:
        assert m["category"] in {"Field Extraction", "Data Model Rules"}


# ──────────────────────────────────────────────────────────────────────
# rag_lookup tool
# ──────────────────────────────────────────────────────────────────────


def test_rag_lookup_empty_query_returns_error_payload():
    rag = sys.modules["_xql_phase4_pkg.rag_lookup"]
    result = rag.execute(query="")
    assert result["matches"] == []
    assert "error" in result


def test_rag_lookup_missing_collection_returns_soft_miss():
    """When xql_corpus hasn't been ingested, return empty matches with an error
    string rather than raising. Workflows treat this as a fall-through."""
    rag = sys.modules["_xql_phase4_pkg.rag_lookup"]
    # Clear cached collection so we get the live miss path.
    rag._collection.cache_clear()
    # Point at a non-existent chroma dir.
    original = rag._CHROMA_DIR
    rag._CHROMA_DIR = Path("/tmp/__nonexistent_xql_corpus__")
    try:
        result = rag.execute(query="anything", top_k=3)
        assert result["matches"] == []
        # Either collection-missing or backend-unavailable — both are soft misses.
        assert "error" in result
    finally:
        rag._CHROMA_DIR = original
        rag._collection.cache_clear()


# ──────────────────────────────────────────────────────────────────────
# analyse_xql_gate hook
# ──────────────────────────────────────────────────────────────────────


def _make_ctx(output: str, parsed=None):
    """Build a HookContext-like object the hook can read."""
    sys.path.insert(0, str(_REPO_ROOT))
    from api.services.hook_bus import HookContext

    ctx = HookContext()
    ctx.output = output
    ctx.parsed = parsed
    ctx.workflow = None
    ctx.step = None
    return ctx


def _make_gate(**kwargs):
    sys.path.insert(0, str(_REPO_ROOT))
    from api.hooks.builtins.analyse_xql_gate import AnalyseXqlGateHook

    return AnalyseXqlGateHook(**kwargs)


def test_gate_passes_clean_rule(monkeypatch):
    """A clean MODEL rule should pass the gate (action=continue)."""
    sys.path.insert(0, str(_REPO_ROOT))
    from api.hooks.builtins import analyse_xql_gate as gate_mod

    fake_service = MagicMock()
    fake_service.call_tool.return_value = {
        "verdict": "READY-TO-DEPLOY",
        "violations": [],
        "suggestions": [],
        "score": 100,
        "summary": {"errors": 0, "warnings": 0, "info": 0, "suggestions": 0},
    }
    monkeypatch.setattr(gate_mod, "_get_plugin_service", lambda: fake_service)

    hook = _make_gate()
    result = hook(
        _make_ctx(output="[MODEL: dataset = v_p_raw]\nalter xdm.event.id = id")
    )
    assert result.action == "continue"
    fake_service.call_tool.assert_called_once()


def test_gate_retries_on_blockers(monkeypatch):
    """A rule with a BLOCKER should trigger action=retry with structured feedback."""
    sys.path.insert(0, str(_REPO_ROOT))
    from api.hooks.builtins import analyse_xql_gate as gate_mod

    fake_service = MagicMock()
    fake_service.call_tool.return_value = {
        "verdict": "NEEDS-FIXES",
        "violations": [
            {
                "ruleId": "ERR-020",
                "line": 2,
                "message": "'xdm.event.bogus' is not a known XDM field",
            },
            {"ruleId": "ERR-006", "line": 3, "message": "Unknown XDM category"},
        ],
        "suggestions": [],
        "score": 60,
        "summary": {"errors": 2, "warnings": 0, "info": 0, "suggestions": 0},
    }
    monkeypatch.setattr(gate_mod, "_get_plugin_service", lambda: fake_service)

    hook = _make_gate(retryable=True)
    result = hook(
        _make_ctx(output="[MODEL: dataset = v_p_raw]\nalter xdm.event.bogus = x")
    )
    assert result.action == "retry"
    assert "ERR-020" in (result.feedback or "")
    assert "ERR-006" in (result.feedback or "")


def test_gate_fails_when_not_retryable(monkeypatch):
    """retryable=False maps BLOCKERs to action=fail."""
    sys.path.insert(0, str(_REPO_ROOT))
    from api.hooks.builtins import analyse_xql_gate as gate_mod

    fake_service = MagicMock()
    fake_service.call_tool.return_value = {
        "verdict": "REWRITE-RECOMMENDED",
        "violations": [{"ruleId": "ERR-020", "line": 1, "message": "x"}],
        "suggestions": [],
        "score": 30,
        "summary": {"errors": 5, "warnings": 0, "info": 0, "suggestions": 0},
    }
    monkeypatch.setattr(gate_mod, "_get_plugin_service", lambda: fake_service)

    hook = _make_gate(retryable=False)
    result = hook(_make_ctx(output="garbage"))
    assert result.action == "fail"


def test_gate_continues_when_analyser_raises(monkeypatch):
    """Analyser failure must not break the workflow — soft-fail to continue."""
    sys.path.insert(0, str(_REPO_ROOT))
    from api.hooks.builtins import analyse_xql_gate as gate_mod

    fake_service = MagicMock()
    fake_service.call_tool.side_effect = RuntimeError("plugin discovery failed")
    monkeypatch.setattr(gate_mod, "_get_plugin_service", lambda: fake_service)

    hook = _make_gate()
    result = hook(_make_ctx(output="some rule"))
    assert result.action == "continue"
    assert "could not run" in (result.feedback or "")


def test_gate_empty_output_skips_gracefully():
    """No output means no rule to analyse — return continue without calling the tool."""
    hook = _make_gate()
    result = hook(_make_ctx(output=""))
    assert result.action == "continue"


def test_gate_factory_registration():
    """The hook is registered in workflow_engine._instantiate_hook factory."""
    sys.path.insert(0, str(_REPO_ROOT))
    # We don't construct WorkflowEngine here (it touches disk + service deps);
    # just verify the import path the factory uses is live.
    from api.hooks.builtins.analyse_xql_gate import AnalyseXqlGateHook  # noqa: F401
