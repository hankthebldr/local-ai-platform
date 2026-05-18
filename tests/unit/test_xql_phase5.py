"""
Phase 5 — structural validation tests for the two new agents,
`xdm-vendor-pack.yaml` workflow, and `vendor-pack-author` skill.

These tests are structural: they verify the YAML/markdown shapes load
correctly and the wiring is coherent (rule IDs / tool IDs / agent IDs
referenced in the workflow exist). End-to-end functional smoke (running
the workflow against a real log + Ollama) is the operator's Gate 5 check.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


# ──────────────────────────────────────────────────────────────────────
# Agent: xql-snippet-curator
# ──────────────────────────────────────────────────────────────────────


def test_snippet_curator_yaml_loads():
    agent = _load_yaml(_REPO_ROOT / "agents" / "xql-snippet-curator.yaml")
    assert agent["id"] == "xql-snippet-curator"
    assert agent["role"] == "fast"
    assert "llama3.2:3b" in agent["model"]


def test_snippet_curator_declares_corpus_tools():
    """The curator's job is corpus retrieval — it must declare rag_lookup and xdm_snippets."""
    agent = _load_yaml(_REPO_ROOT / "agents" / "xql-snippet-curator.yaml")
    tool_ids = {t["tool_id"] for t in agent.get("tools", [])}
    assert {"rag_lookup", "xdm_snippets"}.issubset(
        tool_ids
    ), f"Curator must call rag_lookup + xdm_snippets; got {tool_ids}"


def test_snippet_curator_references_packs_index():
    agent = _load_yaml(_REPO_ROOT / "agents" / "xql-snippet-curator.yaml")
    paths = {c["value"] for c in agent.get("context", [])}
    assert any(
        "packs_index.md" in p for p in paths
    ), "Snippet curator should load packs_index.md as static grounding"


# ──────────────────────────────────────────────────────────────────────
# Agent: xql-rules-reviewer
# ──────────────────────────────────────────────────────────────────────


def test_rules_reviewer_yaml_loads():
    agent = _load_yaml(_REPO_ROOT / "agents" / "xql-rules-reviewer.yaml")
    assert agent["id"] == "xql-rules-reviewer"
    assert agent["role"] == "reasoning"


def test_rules_reviewer_can_invoke_analyser():
    """The reviewer cites rule IDs — it must be able to call analyse_xql to confirm fixes."""
    agent = _load_yaml(_REPO_ROOT / "agents" / "xql-rules-reviewer.yaml")
    tool_ids = {t["tool_id"] for t in agent.get("tools", [])}
    assert (
        "analyse_xql" in tool_ids
    ), f"Rules reviewer must declare analyse_xql; got {tool_ids}"


def test_rules_reviewer_references_rules_engine_doc():
    agent = _load_yaml(_REPO_ROOT / "agents" / "xql-rules-reviewer.yaml")
    paths = {c["value"] for c in agent.get("context", [])}
    assert any(
        "rules_engine_reference.md" in p for p in paths
    ), "Reviewer should load rules_engine_reference.md so its citations are grounded"


# ──────────────────────────────────────────────────────────────────────
# Workflow: xdm-vendor-pack.yaml
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def vendor_pack():
    return _load_yaml(_REPO_ROOT / "workflows" / "xdm-vendor-pack.yaml")


def test_vendor_pack_yaml_loads(vendor_pack):
    assert vendor_pack["id"] == "xdm-vendor-pack"
    assert vendor_pack["schema_version"] == 1


def test_vendor_pack_has_six_steps(vendor_pack):
    step_ids = [s["id"] for s in vendor_pack["steps"]]
    expected = [
        "analyse_log_structure",
        "curate_pack",
        "write_parser",
        "write_datamodel",
        "write_documentation",
        "assemble_pack",
    ]
    assert step_ids == expected, f"Step order changed: {step_ids}"


def test_vendor_pack_dag_dependencies(vendor_pack):
    """DAG sanity: every dependency must reference a real step ID."""
    steps = {s["id"]: s for s in vendor_pack["steps"]}
    for sid, step in steps.items():
        for dep in step.get("depends_on", []) or []:
            assert dep in steps, f"step '{sid}' depends on unknown '{dep}'"


def test_vendor_pack_dag_topological(vendor_pack):
    """Every dependency must appear before its dependent in the steps list."""
    order = {s["id"]: i for i, s in enumerate(vendor_pack["steps"])}
    for s in vendor_pack["steps"]:
        for dep in s.get("depends_on", []) or []:
            assert (
                order[dep] < order[s["id"]]
            ), f"step '{s['id']}' depends on '{dep}' which comes later"


def test_vendor_pack_both_writers_gate_with_analyse_xql(vendor_pack):
    """write_parser and write_datamodel must both declare analyse_xql_gate."""
    by_id = {s["id"]: s for s in vendor_pack["steps"]}
    for step_id in ("write_parser", "write_datamodel"):
        step = by_id[step_id]
        hooks = step.get("hooks", {}) or {}
        validate_hooks = hooks.get("validate_output", []) or []
        names = {h.get("name") for h in validate_hooks}
        assert (
            "analyse_xql_gate" in names
        ), f"{step_id} must declare validate_output: analyse_xql_gate"


def test_vendor_pack_parser_uses_parsing_kind(vendor_pack):
    by_id = {s["id"]: s for s in vendor_pack["steps"]}
    parser = by_id["write_parser"]
    gate = parser["hooks"]["validate_output"][0]
    assert (
        gate["config"]["kind"] == "parsing"
    ), "Parser gate must analyse with kind='parsing' not 'modeling'"


def test_vendor_pack_datamodel_uses_modeling_kind(vendor_pack):
    by_id = {s["id"]: s for s in vendor_pack["steps"]}
    datamodel = by_id["write_datamodel"]
    gate = datamodel["hooks"]["validate_output"][0]
    assert (
        gate["config"]["kind"] == "modeling"
    ), "Datamodel gate must analyse with kind='modeling' not 'parsing'"


def test_vendor_pack_assembler_emits_three_artefacts(vendor_pack):
    """The final step's output schema must declare parser.xql, datamodel.xql, documentation.md."""
    by_id = {s["id"]: s for s in vendor_pack["steps"]}
    assemble = by_id["assemble_pack"]
    schema = assemble.get("output_schema") or {}
    files_def = (schema.get("properties") or {}).get("files") or {}
    required = set(files_def.get("required") or [])
    assert {
        "parser.xql",
        "datamodel.xql",
        "documentation.md",
    } == required, (
        f"assemble_pack must require all three artefact files; got {required}"
    )


# ──────────────────────────────────────────────────────────────────────
# Skill: vendor-pack-author.md
# ──────────────────────────────────────────────────────────────────────


def test_vendor_pack_skill_exists_and_has_frontmatter():
    skill_path = (
        _REPO_ROOT / "plugins" / "xdm-toolkit" / "skills" / "vendor-pack-author.md"
    )
    body = skill_path.read_text(encoding="utf-8")
    assert 'name: "Vendor Pack Author"' in body
    assert 'inject: "system"' in body


def test_vendor_pack_skill_registered_in_plugin_yaml():
    plugin = _load_yaml(_REPO_ROOT / "plugins" / "xdm-toolkit" / "plugin.yaml")
    skill_ids = {s["id"] for s in plugin.get("skills", [])}
    assert (
        "vendor-pack-author" in skill_ids
    ), f"vendor-pack-author must be registered in plugin.yaml; got {skill_ids}"


def test_vendor_pack_skill_triggers_include_pack_keywords():
    plugin = _load_yaml(_REPO_ROOT / "plugins" / "xdm-toolkit" / "plugin.yaml")
    skills = {s["id"]: s for s in plugin.get("skills", [])}
    skill = skills["vendor-pack-author"]
    triggers = [t for t in skill.get("triggers", []) if isinstance(t, dict)]
    keywords = {t["keyword"] for t in triggers if "keyword" in t}
    # At least one of these must trigger the skill so the operator surface fires.
    assert keywords & {
        "vendor pack",
        "onboard vendor",
        "new data source",
    }, f"vendor-pack-author must trigger on at least one pack-onboarding keyword; got {keywords}"
