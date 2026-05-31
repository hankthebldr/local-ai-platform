"""Phase 2c — archetype registry + composer assist.

Coverage:
  - ROLE_PATTERNS gained a "lightweight" entry that resolves to small models
  - archetype inference scores MCPs × 2 + skills + role bonus, with a
    threshold below which we return None
  - explicit step.archetype wins when registered; falls through when typo
  - companion suggestion subtracts what's already declared
  - extend_archetypes refuses to override built-ins
  - POST /api/workflows/composer/assist round-trips through the endpoint
"""

from __future__ import annotations


import pytest

from api.models.workflow_models import AgentStep, ToolRef
from api.services.archetypes import (
    ARCHETYPES,
    extend_archetypes,
    get_archetype,
    infer_archetype,
    list_archetypes,
    suggest_companions,
)
from api.services.model_resolver import ROLE_PATTERNS


def _llm_step(**kw) -> AgentStep:
    return AgentStep(id="s", name="s", system_prompt="p", outputs=["x"], **kw)


# ── ROLE_PATTERNS gains lightweight ──────────────────────────────────


def test_lightweight_role_registered_with_small_models():
    """Phase 2c.1 — the new role must exist and point at sub-3B candidates."""
    assert "lightweight" in ROLE_PATTERNS
    light = ROLE_PATTERNS["lightweight"]
    # The first few entries should be small models.
    head = " ".join(light[:5]).lower()
    assert "1.5b" in head or "phi" in head or "3b" in head
    # Existing roles are untouched.
    assert "reasoning" in ROLE_PATTERNS
    assert "coding" in ROLE_PATTERNS


def test_lightweight_role_does_not_shadow_general():
    """The general role still resolves separately — not collateral damage."""
    assert ROLE_PATTERNS["lightweight"] != ROLE_PATTERNS["general"]


# ── Built-in registry shape ──────────────────────────────────────────


def test_registry_has_expected_archetypes():
    expected = {
        "bash_script",
        "code_review",
        "documentation",
        "research_brief",
        "extraction",
        "synthesis",
        "data_lookup",
        "xsiam_analysis",
        "triage",
    }
    assert expected.issubset(set(ARCHETYPES.keys()))


def test_every_archetype_carries_all_keys():
    required = {
        "default_role",
        "companion_mcps",
        "companion_skills",
        "trigger_mcps",
        "trigger_skills",
        "description",
    }
    for name, spec in ARCHETYPES.items():
        missing = required - set(spec.keys())
        assert not missing, f"{name} missing keys: {missing}"


def test_get_archetype_returns_spec_or_none():
    assert get_archetype("bash_script")["default_role"] == "coding"
    assert get_archetype("nope") is None


def test_list_archetypes_sorted():
    names = [a["name"] for a in list_archetypes()]
    assert names == sorted(names)


# ── infer_archetype ──────────────────────────────────────────────────


def test_inference_bash_script_from_mcp_trigger():
    step = _llm_step(role="coding", tools=[ToolRef(mcp="bash-mcp.run")])
    assert infer_archetype(step) == "bash_script"


def test_inference_code_review_from_skill_plus_role():
    """Score: 0 MCPs + 1 skill (reviewer) + 1 role bonus = 2 ≥ threshold."""
    step = _llm_step(role="coding", skills=["gs.reviewer"])
    assert infer_archetype(step) == "code_review"


def test_inference_xsiam_from_skill_trigger():
    step = _llm_step(
        role="reasoning",
        skills=["xdm-toolkit.xdm-rule-writer", "xdm-toolkit.xql-validator"],
    )
    assert infer_archetype(step) == "xsiam_analysis"


def test_inference_returns_none_below_threshold():
    """A bare reasoning step with no triggers shouldn't claim an archetype."""
    step = _llm_step(role="reasoning")
    assert infer_archetype(step) is None


def test_explicit_archetype_wins_when_registered():
    """An operator-declared archetype overrides inference."""
    step = _llm_step(role="coding", archetype="documentation")
    # Without the explicit tag, inference might pick code_review etc.; with
    # it, documentation wins.
    assert infer_archetype(step) == "documentation"


def test_unknown_declared_archetype_falls_through():
    """A typo'd archetype can't pin the step — we fall back to inference."""
    step = _llm_step(
        role="coding", tools=[ToolRef(mcp="bash-mcp.run")], archetype="bash_scripts"
    )  # typo
    assert infer_archetype(step) == "bash_script"  # inference still wins


def test_mcp_score_outweighs_skill_score():
    """A declared MCP trigger is worth more than a skill trigger."""
    # web-search MCP → research_brief / documentation triggers
    # reviewer skill → code_review trigger
    # MCP wins.
    step = _llm_step(
        role="reasoning",
        tools=[ToolRef(mcp="web-search.query")],
        skills=["gs.reviewer"],
    )
    arch = infer_archetype(step)
    assert arch in ("research_brief", "documentation")


# ── suggest_companions ────────────────────────────────────────────────


def test_suggest_companions_for_partial_bash_script():
    """Operator declared only bash-mcp — composer should suggest coder skill."""
    step = _llm_step(tools=[ToolRef(mcp="bash-mcp.run")])
    out = suggest_companions(step)
    assert out["inferred_archetype"] == "bash_script"
    assert "coder" in out["suggested_skills"]
    # filesystem-local is a companion MCP that wasn't declared.
    assert "filesystem-local" in out["suggested_mcps"]
    # The step has no role, so the composer should suggest one.
    assert out["suggested_role"] == "coding"


def test_suggest_companions_doesnt_double_suggest():
    step = _llm_step(
        role="coding",
        tools=[ToolRef(mcp="bash-mcp.run"), ToolRef(mcp="filesystem-local.read")],
        skills=["gs.coder"],
    )
    out = suggest_companions(step)
    # Both companion MCPs already declared.
    assert "bash-mcp" not in out["suggested_mcps"]
    assert "filesystem-local" not in out["suggested_mcps"]
    assert "coder" not in out["suggested_skills"]
    # Role already declared — no suggestion.
    assert out["suggested_role"] is None


def test_suggest_companions_warns_on_role_mismatch():
    """Bash-script archetype + reasoning role = mismatch."""
    step = _llm_step(role="reasoning", tools=[ToolRef(mcp="bash-mcp.run")])
    out = suggest_companions(step)
    assert out["inferred_archetype"] == "bash_script"
    warnings = out["warnings"]
    assert any(w["code"] == "archetype_role_mismatch" for w in warnings)
    assert warnings[0]["expected_role"] == "coding"
    assert warnings[0]["declared_role"] == "reasoning"


def test_suggest_companions_with_no_match_returns_empty_shape():
    step = _llm_step()
    out = suggest_companions(step)
    assert out["inferred_archetype"] is None
    assert out["suggested_mcps"] == []
    assert out["suggested_skills"] == []
    assert out["warnings"] == []


# ── extend_archetypes ────────────────────────────────────────────────


def test_extend_archetypes_registers_new_pattern():
    extend_archetypes(
        {
            "slack_message": {
                "default_role": "fast",
                "companion_mcps": ["slack-mcp"],
                "companion_skills": [],
                "trigger_mcps": ["slack-mcp"],
                "trigger_skills": [],
                "description": "Compose a Slack message",
            }
        }
    )
    try:
        assert get_archetype("slack_message")["default_role"] == "fast"
        step = _llm_step(role="fast", tools=[ToolRef(mcp="slack-mcp.send")])
        assert infer_archetype(step) == "slack_message"
    finally:
        ARCHETYPES.pop("slack_message", None)


def test_extend_archetypes_refuses_to_override_builtin():
    """A plugin can't redefine bash_script."""
    original = dict(ARCHETYPES["bash_script"])
    extend_archetypes(
        {
            "bash_script": {
                "default_role": "uncensored",
                "companion_mcps": ["evil-mcp"],
            }
        }
    )
    assert ARCHETYPES["bash_script"] == original


def test_extend_archetypes_fills_missing_keys_with_defaults():
    extend_archetypes(
        {
            "minimal_thing": {
                "default_role": "coding",
                "description": "barely declared",
            }
        }
    )
    try:
        spec = get_archetype("minimal_thing")
        assert spec["trigger_mcps"] == []
        assert spec["companion_skills"] == []
    finally:
        ARCHETYPES.pop("minimal_thing", None)


# ── /api/workflows/composer/assist endpoint ──────────────────────────


@pytest.fixture
def client(monkeypatch):
    from unittest.mock import patch

    from fastapi.testclient import TestClient

    # Auth off + provide a benign OllamaService for the engine init.
    monkeypatch.setenv("ENABLE_API_AUTH", "false")
    with patch("api.services.ollama_service.OllamaService"):
        from api.main import app

        yield TestClient(app)


def test_composer_assist_endpoint_suggests_companions(client):
    partial = {
        "id": "s1",
        "tools": [{"mcp": "bash-mcp.run"}],
    }
    r = client.post("/api/workflows/composer/assist", json={"step": partial})
    assert r.status_code == 200
    body = r.json()
    assert body["inferred_archetype"] == "bash_script"
    assert body["suggested_role"] == "coding"
    assert "coder" in body["suggested_skills"]


def test_composer_assist_endpoint_handles_empty_step(client):
    """A bare draft should return empty suggestions, not 422."""
    r = client.post("/api/workflows/composer/assist", json={"step": {}})
    assert r.status_code == 200
    assert r.json() == {
        "inferred_archetype": None,
        "suggested_role": None,
        "suggested_mcps": [],
        "suggested_skills": [],
        "warnings": [],
    }


def test_composer_assist_endpoint_tolerates_malformed_payload(client):
    """Garbage inside tools[] shouldn't crash the endpoint — composer types
    fast and partial drafts happen."""
    r = client.post(
        "/api/workflows/composer/assist",
        json={"step": {"tools": [{"not_a_real_field": "blah"}]}},
    )
    assert r.status_code == 200
    # Either an empty shape (validation falls through) or a None archetype.
    body = r.json()
    assert body["inferred_archetype"] is None
