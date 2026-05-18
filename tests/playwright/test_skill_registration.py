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
    """xdm-toolkit's plugin.yaml registers 3 skills."""
    plug = _xdm_toolkit(base_url, api_headers)
    skills = plug.get("skills", [])
    ids = sorted(s.get("id") for s in skills)
    expected = ["rag-query-crafter", "xdm-rule-writer", "xql-validator"]
    assert ids == expected, (
        f"xdm-toolkit skill set drifted from manifest.\n"
        f"  expected: {expected}\n  actual:   {ids}"
    )


def test_xdm_toolkit_tools_still_intact(base_url, api_headers):
    """Regression: registering a new skill must not affect tool registration."""
    plug = _xdm_toolkit(base_url, api_headers)
    tool_ids = sorted(t.get("id") for t in plug.get("tools", []))
    expected = sorted(["analyse_xql", "lookup_xdm_path", "validate_xql"])
    assert (
        tool_ids == expected
    ), f"xdm-toolkit tools drifted.\n  expected: {expected}\n  actual: {tool_ids}"


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
