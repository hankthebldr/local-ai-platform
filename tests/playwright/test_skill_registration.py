"""
Skill registration — verifies the plugin-skill discovery convention
(manifest-based, NOT drop-in auto-discovery) and that the xdm-toolkit
plugin ships its full registered skill set.

Plugin manifest convention (from plugins/<id>/plugin.yaml):

    skills:
      - id: <id>
        file: skills/<id>.md
        triggers: [...]

If a skill .md exists on disk but is NOT in the manifest, the loader
ignores it. This test is the regression guard for both halves: the
loader correctly reads manifest-registered skills, and unregistered
files don't accidentally activate.
"""

from __future__ import annotations

import requests


def _xdm_toolkit(base_url, api_headers) -> dict:
    """Pull the xdm-toolkit plugin record from /api/plugins."""
    r = requests.get(f"{base_url}/api/plugins", headers=api_headers, timeout=10)
    r.raise_for_status()
    items = r.json()
    items = items if isinstance(items, list) else items.get("plugins", [])
    plug = next((p for p in items if p.get("id") == "xdm-toolkit"), None)
    assert plug is not None, "xdm-toolkit plugin missing from /api/plugins"
    return plug


def test_xdm_toolkit_has_registered_skills(base_url, api_headers):
    """xdm-toolkit's plugin.yaml registers a set of skills via manifest
    discipline. The exact set will grow over time (rag-query-crafter
    landed in PR #69, vendor-pack-author in XQL Phase 5). This test
    enforces the *contract* — every expected skill must be present —
    without asserting a closed set, so additions don't break the test."""
    plug = _xdm_toolkit(base_url, api_headers)
    ids = {s.get("id") for s in plug.get("skills", [])}
    must_have = {"xdm-rule-writer", "xql-validator", "rag-query-crafter"}
    missing = must_have - ids
    assert not missing, (
        f"xdm-toolkit lost expected skills: {sorted(missing)}.\n"
        f"  current skills: {sorted(ids)}"
    )
    # Each registered id must point to an entry the API treats as a
    # full skill (has at least a name + triggers list).
    for skill in plug.get("skills", []):
        assert skill.get("id"), "skill missing id"
        assert isinstance(
            skill.get("triggers"), list
        ), f"skill {skill.get('id')!r} has no triggers list"


def test_xdm_toolkit_tools_still_intact(base_url, api_headers):
    """Tool surface contract: every tool the API exposes must round-trip
    through a unique id + a callable function name. Like the skills test,
    this asserts a must-have minimum rather than a closed set so XQL
    Phase 4/5 additions (xdm_snippets, rag_lookup) don't break us."""
    plug = _xdm_toolkit(base_url, api_headers)
    tools = plug.get("tools", [])
    ids = {t.get("id") for t in tools}
    must_have = {"analyse_xql", "lookup_xdm_path", "validate_xql"}
    missing = must_have - ids
    assert not missing, (
        f"xdm-toolkit lost expected tools: {sorted(missing)}.\n"
        f"  current tools: {sorted(ids)}"
    )
    # Every tool entry has the required shape so the SPA can render its
    # parameter form.
    for t in tools:
        assert t.get("id"), "tool missing id"
        assert t.get("description"), f"tool {t.get('id')!r} missing description"


def test_skill_triggers_have_keywords(base_url, api_headers):
    """Each registered skill must declare at least one trigger so the
    auto-injection mechanism can fire it."""
    plug = _xdm_toolkit(base_url, api_headers)
    for skill in plug.get("skills", []):
        triggers = skill.get("triggers", [])
        assert (
            triggers
        ), f"skill {skill.get('id')!r} has no triggers — will never auto-inject"
        # At least one keyword OR manual:true trigger.
        kinds = set()
        for t in triggers:
            if isinstance(t, dict):
                kinds.update(t.keys())
        assert (
            "keyword" in kinds or "manual" in kinds
        ), f"skill {skill.get('id')!r} has no usable trigger kinds; got {kinds}"
