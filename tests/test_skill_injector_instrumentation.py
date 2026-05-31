"""Phase 4.2 — skill activation capture via the skill_injector hook.

Coverage:
  - PluginService.get_skill returns the full skill dict or None
  - skill_injector mode literal: off / auto / explicit / manual
  - explicit step.skills always inject regardless of keyword match
  - auto mode also injects keyword-matched skills
  - injection sites: "system" (default) prepends to prompt.system;
    "messages" appends to prompt.user
  - SkillActivation records carry trigger ("explicit" or "keyword"),
    trigger_match, injected_into, injected_chars
  - extension_overhead_ms accumulates
  - max_skills caps the total injections per step
  - missing skill refs / malformed refs are logged but never raise
  - aggregate_extension_stats picks up skills_activated_total
  - engine factory registers the hook
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import List

import pytest

from api.hooks.builtins.skill_injector import (
    SkillInjectorHook,
    set_plugin_service,
)
from api.models.workflow_models import (
    SkillActivation,
    StepResult,
    WorkflowContext,
    WorkflowRun,
    aggregate_extension_stats,
)
from api.services.hook_bus import HookContext

# ── Fake PluginService for the hook to query ─────────────────────────


@dataclass
class _FakeService:
    """Stand-in for PluginService. Implements just the surface
    skill_injector uses (_plugins dict, get_skill, get_skills)."""

    _plugins: dict = field(default_factory=dict)

    def add_skill(
        self,
        plugin_id: str,
        skill_id: str,
        *,
        content: str = "skill body",
        inject: str = "system",
        triggers=None,
    ) -> None:
        skill = {
            "id": skill_id,
            "name": skill_id,
            "description": "test",
            "inject": inject,
            "content": content,
            "triggers": triggers or [],
        }
        self._plugins.setdefault(plugin_id, {"id": plugin_id, "skills": []})[
            "skills"
        ].append(skill)

    def get_skill(self, plugin_id, skill_id):
        plugin = self._plugins.get(plugin_id)
        if not plugin:
            return None
        for skill in plugin.get("skills", []):
            if skill["id"] == skill_id:
                return skill
        return None

    def get_skills(self, user_message: str) -> List[dict]:
        out = []
        lower = user_message.lower()
        for plugin in self._plugins.values():
            for skill in plugin.get("skills", []):
                for trigger in skill.get("triggers", []) or []:
                    kw = trigger.get("keyword", "")
                    if kw and kw.lower() in lower:
                        out.append(skill)
                        break
        return out


@pytest.fixture
def fake_service():
    svc = _FakeService()
    set_plugin_service(svc)
    yield svc
    set_plugin_service(None)


def _prompt(system: str = "base system", user: str = "user content"):
    return SimpleNamespace(system=system, user=user, params={})


def _step(*, skills=None):
    return SimpleNamespace(id="s1", skills=skills or [])


def _ctx(step_result, prompt, step):
    context = WorkflowContext(seed={}, workspace={})
    workflow_run = SimpleNamespace(context=context, run_id="run-X")
    return HookContext(
        workflow=workflow_run,
        step=step,
        prompt=prompt,
        step_result=step_result,
    )


# ── PluginService.get_skill ──────────────────────────────────────────


def test_plugin_service_get_skill_returns_dict_or_none(tmp_path):
    from api.services.plugin_service import PluginService

    system = tmp_path / "system" / "plugins"
    plugin_dir = system / "gs"
    plugin_dir.mkdir(parents=True)
    skills_dir = plugin_dir / "skills"
    skills_dir.mkdir()
    (skills_dir / "concise.md").write_text(
        "---\nname: concise\ndescription: be brief\ninject: system\n---\n" "Be concise."
    )
    (plugin_dir / "plugin.yaml").write_text(
        'id: gs\nname: gs\nversion: "1.0"\n'
        "skills:\n"
        "  - id: concise\n    file: skills/concise.md\n"
        "    triggers:\n      - keyword: concise\n"
        "tools: []\n"
    )

    svc = PluginService(system_dir=system)
    svc.scan_plugins()
    skill = svc.get_skill("gs", "concise")
    assert skill is not None
    assert skill["id"] == "concise"
    assert "Be concise" in skill["content"]
    assert svc.get_skill("gs", "missing") is None
    assert svc.get_skill("nope", "concise") is None


# ── Hook shape ───────────────────────────────────────────────────────


def test_hook_name_and_stage():
    hook = SkillInjectorHook()
    assert hook.name == "skill_injector"
    assert hook.stage == "transform_prompt"


def test_mode_off_is_noop(fake_service):
    fake_service.add_skill("gs", "concise", triggers=[{"keyword": "concise"}])
    hook = SkillInjectorHook(mode="off")
    sr = StepResult(step_id="s1")
    prompt = _prompt(system="orig", user="please be concise")
    ctx = _ctx(sr, prompt, _step(skills=["gs.concise"]))
    hook(ctx)
    assert prompt.system == "orig"
    assert prompt.user == "please be concise"
    assert sr.skills_activated == []


# ── explicit refs always inject ──────────────────────────────────────


def test_explicit_skill_injects_into_system_and_records(fake_service):
    fake_service.add_skill("gs", "rule", content="ALWAYS BE BRIEF", inject="system")
    hook = SkillInjectorHook(mode="explicit")
    sr = StepResult(step_id="s1")
    prompt = _prompt(system="role: writer", user="unrelated user message")
    ctx = _ctx(sr, prompt, _step(skills=["gs.rule"]))
    hook(ctx)
    assert prompt.system.startswith("ALWAYS BE BRIEF")
    assert "role: writer" in prompt.system
    assert len(sr.skills_activated) == 1
    activation = sr.skills_activated[0]
    assert activation.plugin_id == "gs"
    assert activation.skill_id == "rule"
    assert activation.trigger == "explicit"
    assert activation.trigger_match is None
    assert activation.injected_into == "system"
    assert activation.injected_chars == len("ALWAYS BE BRIEF")
    assert sr.extension_overhead_ms > 0


def test_explicit_skill_with_messages_injection_appends_to_user(fake_service):
    fake_service.add_skill("gs", "footer", content="—signed Enclave", inject="messages")
    hook = SkillInjectorHook(mode="explicit")
    sr = StepResult(step_id="s1")
    prompt = _prompt(user="please draft a note")
    ctx = _ctx(sr, prompt, _step(skills=["gs.footer"]))
    hook(ctx)
    assert prompt.user.endswith("—signed Enclave")
    assert sr.skills_activated[0].injected_into == "messages"


def test_missing_explicit_skill_is_logged_not_raised(fake_service):
    hook = SkillInjectorHook(mode="explicit")
    sr = StepResult(step_id="s1")
    ctx = _ctx(sr, _prompt(), _step(skills=["gs.does-not-exist"]))
    result = hook(ctx)
    assert result.action == "continue"
    assert sr.skills_activated == []


def test_malformed_explicit_ref_is_skipped(fake_service):
    hook = SkillInjectorHook(mode="explicit")
    sr = StepResult(step_id="s1")
    ctx = _ctx(sr, _prompt(), _step(skills=["no-dot-here"]))
    hook(ctx)
    assert sr.skills_activated == []


# ── auto mode: keyword triggers ──────────────────────────────────────


def test_auto_mode_keyword_match_injects(fake_service):
    fake_service.add_skill(
        "gs",
        "concise",
        content="Be brief.",
        triggers=[{"keyword": "concise"}],
    )
    hook = SkillInjectorHook(mode="auto")
    sr = StepResult(step_id="s1")
    prompt = _prompt(user="please be CONCISE in your answer")
    ctx = _ctx(sr, prompt, _step())
    hook(ctx)
    assert prompt.system.startswith("Be brief.")
    activation = sr.skills_activated[0]
    assert activation.trigger == "keyword"
    assert activation.trigger_match == "concise"


def test_auto_mode_no_match_is_noop(fake_service):
    fake_service.add_skill(
        "gs",
        "concise",
        content="Be brief.",
        triggers=[{"keyword": "brevity"}],
    )
    hook = SkillInjectorHook(mode="auto")
    sr = StepResult(step_id="s1")
    prompt = _prompt(user="nothing here matches")
    ctx = _ctx(sr, prompt, _step())
    hook(ctx)
    assert prompt.system == "base system"
    assert sr.skills_activated == []


def test_auto_mode_explicit_takes_precedence_over_keyword(fake_service):
    """A skill listed in step.skills should not be double-injected when its
    keyword also fires."""
    fake_service.add_skill(
        "gs",
        "concise",
        content="Be brief.",
        triggers=[{"keyword": "concise"}],
    )
    hook = SkillInjectorHook(mode="auto")
    sr = StepResult(step_id="s1")
    prompt = _prompt(user="please be concise")
    ctx = _ctx(sr, prompt, _step(skills=["gs.concise"]))
    hook(ctx)
    assert len(sr.skills_activated) == 1
    assert sr.skills_activated[0].trigger == "explicit"


def test_manual_mode_does_not_keyword_match(fake_service):
    fake_service.add_skill(
        "gs",
        "concise",
        content="Be brief.",
        triggers=[{"keyword": "concise"}],
    )
    hook = SkillInjectorHook(mode="manual")
    sr = StepResult(step_id="s1")
    prompt = _prompt(user="please be concise")
    ctx = _ctx(sr, prompt, _step())  # no explicit skills
    hook(ctx)
    assert sr.skills_activated == []


# ── max_skills cap ───────────────────────────────────────────────────


def test_max_skills_caps_activations(fake_service):
    for i in range(5):
        fake_service.add_skill("gs", f"s{i}", content=f"body{i}", inject="system")
    hook = SkillInjectorHook(mode="explicit", max_skills=2)
    sr = StepResult(step_id="s1")
    ctx = _ctx(
        sr,
        _prompt(),
        _step(skills=[f"gs.s{i}" for i in range(5)]),
    )
    hook(ctx)
    assert len(sr.skills_activated) == 2


def test_max_skills_none_means_unlimited(fake_service):
    for i in range(4):
        fake_service.add_skill("gs", f"s{i}", content=f"b{i}")
    hook = SkillInjectorHook(mode="explicit", max_skills=None)
    sr = StepResult(step_id="s1")
    ctx = _ctx(sr, _prompt(), _step(skills=[f"gs.s{i}" for i in range(4)]))
    hook(ctx)
    assert len(sr.skills_activated) == 4


# ── instrumentation no-op without step_result ────────────────────────


def test_instrumentation_skips_when_no_step_result(fake_service):
    fake_service.add_skill("gs", "rule", content="x")
    hook = SkillInjectorHook(mode="explicit")
    ctx = _ctx(None, _prompt(), _step(skills=["gs.rule"]))
    result = hook(ctx)
    # The hook still injects (prompt is mutated) but doesn't crash on
    # missing step_result.
    assert result.action == "continue"


# ── Aggregation picks up Phase 4.2 records ──────────────────────────


def test_aggregate_extension_stats_counts_skill_activations():
    sr1 = StepResult(
        step_id="s1",
        skills_activated=[
            SkillActivation(
                plugin_id="gs",
                skill_id="a",
                trigger="explicit",
                injected_into="system",
                injected_chars=10,
            ),
            SkillActivation(
                plugin_id="gs",
                skill_id="b",
                trigger="keyword",
                trigger_match="brief",
                injected_into="system",
                injected_chars=20,
            ),
        ],
        extension_overhead_ms=12.0,
    )
    run = WorkflowRun(
        workflow_id="w",
        context=WorkflowContext(seed={}),
        step_results=[sr1],
    )
    aggregate_extension_stats(run)
    assert run.skills_activated_total == 2
    assert run.extension_overhead_seconds == pytest.approx(0.012)


# ── Engine factory recognizes the hook ──────────────────────────────


def test_engine_factory_registers_skill_injector():
    from api.models.workflow_models import HookSpec
    from api.services.ollama_service import OllamaService
    from api.services.workflow_engine import WorkflowEngine

    engine = WorkflowEngine(OllamaService())
    spec = HookSpec(name="skill_injector", config={"mode": "auto"})
    hook = engine._instantiate_hook(spec, "transform_prompt")  # noqa: SLF001
    assert isinstance(hook, SkillInjectorHook)
    assert hook.mode == "auto"
