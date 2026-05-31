"""
skill_injector hook — injects plugin skill bodies into the composed prompt
and records each activation on the step result.

Stage: transform_prompt (runs after compose, before the model call, so
the augmented prompt actually reaches the LLM).

Modes (mirroring ``WorkflowDefaults.skill_injection`` from Phase 5):

  ``auto``     — keyword triggers + ``step.skills`` explicit list (default
                 when the hook is configured with no ``mode`` key).
  ``explicit`` — only inject skills the step listed in ``step.skills``.
  ``manual``   — same as explicit; no keyword fallback.
  ``off``      — no-op.

Injection sites are decided by each skill's frontmatter ``inject`` field
(written by `_parse_skill_md` in plugin_service):

  ``"system"`` (default) — body prepended to ``prompt.system`` so the
                            model treats it as governing instruction.
  ``"messages"``         — body appended to ``prompt.user`` as a
                            preamble so the model treats it as
                            user-provided context.

Phase 4.2 — every activated skill produces a ``SkillActivation`` record
on ``ctx.step_result.skills_activated`` with the trigger that fired
(``keyword`` + the matched substring, or ``explicit``) and the injected
character count. ``extension_overhead_ms`` accumulates the per-skill
render time so the operator can ratio skill cost against inference time.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, List, Optional, Tuple

from api.logging_config import logger
from api.services.hook_bus import HookContext, HookResult

# ── Shared PluginService singleton ──────────────────────────────────────


_service_lock = threading.Lock()
_plugin_service: Any = None


def _get_plugin_service():
    global _plugin_service
    if _plugin_service is not None:
        return _plugin_service
    with _service_lock:
        if _plugin_service is None:
            from api.services.plugin_service import PluginService

            svc = PluginService(plugins_dir=os.getenv("PLUGINS_DIR", "plugins"))
            try:
                svc.scan_plugins()
            except Exception as e:
                logger.warning(f"skill_injector: initial scan failed: {e}")
            _plugin_service = svc
    return _plugin_service


def set_plugin_service(service) -> None:
    """Override the module-level plugin service. Intended for tests."""
    global _plugin_service
    _plugin_service = service


# ── Hook ────────────────────────────────────────────────────────────────


_VALID_MODES = ("auto", "explicit", "manual", "off")


@dataclass
class SkillInjectorHook:
    """Declarative skill injection step hook.

    Operators rarely configure this directly — workflow defaults handle
    the common case. When they do declare it, the YAML shape is:

        hooks:
          transform_prompt:
            - name: skill_injector
              config:
                mode: auto         # default
                max_skills: 3      # cap to prevent prompt bloat
    """

    mode: str = "auto"
    # Cap the number of activations per step to keep a single keyword from
    # injecting half a plugin library's worth of bodies. None = no cap.
    max_skills: Optional[int] = 3

    name: str = field(default="skill_injector")
    stage: str = field(default="transform_prompt")

    def __call__(self, ctx: HookContext) -> HookResult:
        try:
            mode = self.mode if self.mode in _VALID_MODES else "auto"
            if mode == "off":
                return HookResult(action="continue")
            if ctx.prompt is None:
                return HookResult(action="continue")

            t_total_start = time.monotonic()
            service = _get_plugin_service()
            step = ctx.step
            explicit_refs = list(getattr(step, "skills", []) or [])

            activations: List[Tuple[str, str, dict, str, Optional[str]]] = (
                []
            )  # (plugin_id, skill_id, skill_dict, trigger, trigger_match)

            # 1. Explicit refs from step.skills always inject (every mode but off).
            for ref in explicit_refs:
                if "." not in ref:
                    logger.debug("skill_injector: skipping malformed skill ref %r", ref)
                    continue
                pid, sid = ref.split(".", 1)
                skill = (
                    service.get_skill(pid, sid)
                    if hasattr(service, "get_skill")
                    else None
                )
                if skill is None:
                    logger.debug(
                        "skill_injector: skill %s.%s not found in registry",
                        pid,
                        sid,
                    )
                    continue
                activations.append((pid, sid, skill, "explicit", None))

            # 2. Keyword matching (auto only). Searches the user message; the
            # match is best-effort and may add to the explicit set.
            if mode == "auto":
                user_text = ctx.prompt.user or ""
                try:
                    auto_matches = service.get_skills(user_text)
                except Exception as exc:  # noqa: BLE001
                    logger.debug(f"skill_injector: get_skills failed: {exc}")
                    auto_matches = []
                already = {(p, s) for p, s, _, _, _ in activations}
                for skill in auto_matches:
                    sid = skill.get("id")
                    pid = _find_plugin_id_for_skill(service, sid)
                    if pid is None or (pid, sid) in already:
                        continue
                    matched_kw = _first_matching_keyword(skill, user_text)
                    activations.append((pid, sid, skill, "keyword", matched_kw))
                    already.add((pid, sid))

            if not activations:
                return HookResult(action="continue")

            if self.max_skills is not None:
                activations = activations[: self.max_skills]

            # 3. Inject + record.
            for pid, sid, skill, trigger, matched in activations:
                body = (skill.get("content") or "").strip()
                if not body:
                    continue
                inject_site = (skill.get("inject") or "system").lower()
                site = "system" if inject_site != "messages" else "messages"
                injected_chars = len(body)
                if site == "system":
                    ctx.prompt.system = (body + "\n\n") + (ctx.prompt.system or "")
                else:
                    ctx.prompt.user = (ctx.prompt.user or "") + ("\n\n" + body)
                self._record(
                    ctx,
                    plugin_id=pid,
                    skill_id=sid,
                    trigger=trigger,
                    trigger_match=matched,
                    injected_into=site,
                    injected_chars=injected_chars,
                )

            elapsed_ms = (time.monotonic() - t_total_start) * 1000.0
            self._bump_overhead(ctx, elapsed_ms)
            return HookResult(action="continue")

        except Exception as e:  # noqa: BLE001 - never block the step on skill issues
            logger.error(
                f"skill_injector failed (step={getattr(ctx.step, 'id', '?')}): {e}"
            )
            return HookResult(action="continue")

    def _record(
        self,
        ctx: HookContext,
        *,
        plugin_id: str,
        skill_id: str,
        trigger: str,
        trigger_match: Optional[str],
        injected_into: str,
        injected_chars: int,
    ) -> None:
        """Append a SkillActivation record onto the step result. No-op when
        the result handle isn't attached (workflow-stage hooks, legacy
        callers)."""
        result = getattr(ctx, "step_result", None)
        if result is None:
            return
        try:
            from api.models.workflow_models import SkillActivation

            result.skills_activated.append(
                SkillActivation(
                    plugin_id=plugin_id,
                    skill_id=skill_id,
                    trigger=trigger,  # type: ignore[arg-type]
                    trigger_match=trigger_match,
                    injected_into=injected_into,  # type: ignore[arg-type]
                    injected_chars=injected_chars,
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"skill_injector: instrumentation skipped: {exc}")

    def _bump_overhead(self, ctx: HookContext, ms: float) -> None:
        result = getattr(ctx, "step_result", None)
        if result is None:
            return
        try:
            result.extension_overhead_ms = round(result.extension_overhead_ms + ms, 3)
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"skill_injector: overhead bump skipped: {exc}")


# ── Small helpers ──────────────────────────────────────────────────────


def _first_matching_keyword(skill: dict, text: str) -> Optional[str]:
    """Return the first keyword from a skill's trigger list that occurs
    (case-insensitive) in ``text``. Used to populate
    ``SkillActivation.trigger_match`` so operators can see which keyword
    actually fired."""
    if not text:
        return None
    lower = text.lower()
    for trigger in skill.get("triggers", []) or []:
        kw = trigger.get("keyword", "") if isinstance(trigger, dict) else ""
        if kw and kw.lower() in lower:
            return kw
    return None


def _find_plugin_id_for_skill(service, skill_id: str) -> Optional[str]:
    """Reverse-lookup ``plugin_id`` for a matched skill dict. ``get_skills``
    flattens across plugins so the skill itself doesn't carry its origin.
    Walks the registry once to find which plugin owns ``skill_id``."""
    plugins = getattr(service, "_plugins", {}) or {}
    for pid, plugin in plugins.items():
        for skill in plugin.get("skills", []):
            if skill.get("id") == skill_id:
                return pid
    return None
