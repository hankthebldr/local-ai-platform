#!/usr/bin/env python3
"""LB1-U1 parity gate — router-side skill injection vs the engine builtin.

POST /api/workflows/test-step accepts skills[] and injects them router-side
(the engine files are frozen). This test pins the router helper's output
against api/hooks/builtins/skill_injector.py — text AND activation records
must be identical, including the builtin's default max_skills cap and its
injection-site grammar (system: body + "\\n\\n" prepended; messages:
"\\n\\n" + body appended). If the builtin's semantics ever change, this file
fails and the router path must be revisited in the same change.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from api.hooks.builtins import skill_injector
from api.hooks.builtins.skill_injector import SkillInjectorHook
from api.routers.workflows import _apply_skill_injection
from api.services.hook_bus import HookContext
from api.services.prompt_composer import ComposedPrompt

SYSTEM_BODY = "Always cross-check at least two sources."
MESSAGES_BODY = "Prefer primary sources."
EXTRA_BODIES = ["Rule A.", "Rule B."]


class StubPluginService:
    """Minimal PluginService shape the injector consumes."""

    def __init__(self):
        skills = [
            {
                "id": "search-strategy",
                "name": "Search Strategy",
                "content": SYSTEM_BODY,
                "inject": "system",
                "triggers": [{"keyword": "search"}],
            },
            {
                "id": "context-notes",
                "name": "Context Notes",
                "content": MESSAGES_BODY,
                "inject": "messages",
                "triggers": [{"keyword": "notes"}],
            },
            {
                "id": "rule-a",
                "name": "Rule A",
                "content": EXTRA_BODIES[0],
                "inject": "system",
                "triggers": [],
            },
            {
                "id": "rule-b",
                "name": "Rule B",
                "content": EXTRA_BODIES[1],
                "inject": "system",
                "triggers": [],
            },
        ]
        self._plugins = {"websearch": {"id": "websearch", "skills": skills}}

    def get_skill(self, plugin_id, skill_id):
        for skill in self._plugins.get(plugin_id, {}).get("skills", []):
            if skill["id"] == skill_id:
                return skill
        return None

    def get_skills(self, user_message):
        return []


@pytest.fixture(autouse=True)
def stub_service():
    saved = skill_injector._plugin_service
    stub = StubPluginService()
    skill_injector.set_plugin_service(stub)
    yield stub
    skill_injector.set_plugin_service(saved)


def _run_builtin(system: str, user: str, refs: list[str]):
    """Ground truth: the engine builtin in explicit mode on a synthetic ctx."""
    prompt = ComposedPrompt(system=system, user=user)
    handle = SimpleNamespace(skills_activated=[], extension_overhead_ms=0.0)
    ctx = HookContext(
        step=SimpleNamespace(id="s1", skills=list(refs)),
        prompt=prompt,
        step_result=handle,
    )
    result = SkillInjectorHook(mode="explicit")(ctx)
    assert result.action == "continue"
    return prompt.system, prompt.user, [a.model_dump() for a in handle.skills_activated]


REF_SETS = [
    ["websearch.search-strategy"],
    ["websearch.context-notes"],
    ["websearch.search-strategy", "websearch.context-notes"],
    # 4 refs — exercises the builtin's default max_skills=3 cap.
    [
        "websearch.search-strategy",
        "websearch.context-notes",
        "websearch.rule-a",
        "websearch.rule-b",
    ],
    # Malformed + missing refs are skipped, never fatal.
    ["no-dot-ref", "websearch.missing", "websearch.search-strategy"],
    [],
]


@pytest.mark.parametrize("refs", REF_SETS, ids=[",".join(r) or "empty" for r in REF_SETS])
def test_router_injection_matches_builtin(refs):
    system, user = "SYS instructions.", "USER question."
    b_system, b_user, b_acts = _run_builtin(system, user, refs)
    r_system, r_user, r_acts = _apply_skill_injection(system, user, refs)
    assert r_system == b_system
    assert r_user == b_user
    assert r_acts == b_acts


def test_injected_text_grammar_pinned():
    """Golden expectation for the injection grammar itself — if the builtin
    changes, this fails loudly instead of both paths silently drifting."""
    system, user, acts = _run_builtin(
        "SYS", "hi", ["websearch.search-strategy", "websearch.context-notes"]
    )
    assert system == SYSTEM_BODY + "\n\n" + "SYS"
    assert user == "hi" + "\n\n" + MESSAGES_BODY
    assert [(a["skill_id"], a["trigger"], a["injected_into"]) for a in acts] == [
        ("search-strategy", "explicit", "system"),
        ("context-notes", "explicit", "messages"),
    ]
    assert acts[0]["injected_chars"] == len(SYSTEM_BODY)


def test_max_skills_cap_applies_to_router_path():
    _, _, acts = _apply_skill_injection("SYS", "hi", REF_SETS[3])
    assert len(acts) == 3  # builtin default max_skills=3
