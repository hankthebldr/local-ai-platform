"""
Spec capture — turn a chat conversation into an editable workflow spec.

This is *pre-execution authoring* for the chat-led Composer. It reads a whole
conversation and distills the user's durable GOAL, the INPUTS a future run
would need (seed inputs), and the validation CHECKS that define "done well".

The call runs entirely on a LOCAL model via :class:`OllamaService` (no cloud,
no telemetry). It never imports the workflow engine. The output feeds the
Composer "plan card", where the operator reviews/edits the spec before it is
scaffolded into a runnable DAG.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from ..logging_config import logger
from ..services.model_resolver import ModelResolver
from ..services.ollama_service import OllamaService

_SYSTEM_PROMPT = """You are the planning front-end of a LOCAL, self-hosted AI platform.
A user has been chatting to solve a problem. Read the WHOLE conversation and distill it
into a compact, structured SPEC for an agentic workflow that would accomplish the user's
underlying goal reliably and repeatably.

Return ONLY a JSON object, no prose, with exactly this shape:
{
  "goal": "<one or two sentences: what the workflow should accomplish>",
  "inputs": [
    {"key": "<snake_case_key>", "description": "<what the user supplies at run time>"}
  ],
  "checks": ["<a validation / quality criterion the final output must satisfy>"]
}

Rules:
- "goal" is the durable intent, not a transcript. Generalize lightly so it is reusable.
- "inputs" are the seed values a future run needs (e.g. a subject, a URL pasted as text,
  a desired tone). 1-4 inputs, snake_case keys. Return [] if none are needed.
- "checks" are concrete acceptance criteria implied by the conversation (e.g. "tone is
  firm but warm", "no factual over-promising", "valid YAML"). 1-5 checks, [] if none.
- Be faithful to the conversation; do not invent requirements the user never implied.
"""


class SpecCaptureService:
    """Extract an editable workflow spec from a chat thread (local LLM)."""

    def __init__(self, ollama: OllamaService, resolver: Optional[ModelResolver] = None):
        self.ollama = ollama
        self.resolver = resolver or ModelResolver(ollama)

    def capture(
        self,
        messages: List[Dict[str, Any]],
        model: Optional[str] = None,
        role: Optional[str] = "reasoning",
    ) -> Dict[str, Any]:
        """Return ``{goal, inputs, checks, model}``.

        Tolerant by design: a model that returns prose, malformed JSON, or
        nothing at all degrades to a heuristic goal rather than failing the UI.
        """
        # Resolve guarded: with Ollama down, resolve() itself raises a
        # 503-class error. Degrade to a usable spec (heuristic goal) rather
        # than 503-ing the UI — capture must always return something loadable.
        try:
            resolved = self.resolver.resolve(
                model=model, role=role, default_role="reasoning"
            )
        except Exception as exc:  # noqa: BLE001
            logger.info("Spec capture model resolve failed: %s", exc)
            resolved = model or "local model"
        thread = _format_thread(messages)
        data: Dict[str, Any] = {}
        try:
            result = self.ollama.chat(
                model=resolved,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": thread},
                ],
                temperature=0.2,
                max_tokens=1024,
            )
            content = (result or {}).get("content", "") or ""
            data = _extract_json(content)
        except Exception as exc:  # noqa: BLE001 — never hard-fail the UI
            logger.info("Spec capture falling back to heuristic: %s", exc)

        goal = str(data.get("goal") or "").strip() or _heuristic_goal(messages)
        return {
            "goal": goal,
            "inputs": _coerce_inputs(data.get("inputs")),
            "checks": _coerce_checks(data.get("checks")),
            "model": resolved,
        }


def _format_thread(messages: List[Dict[str, Any]]) -> str:
    lines: List[str] = []
    for m in messages:
        role = str(m.get("role") or "user").upper()
        content = str(m.get("content") or "").strip()
        if content:
            lines.append(f"{role}: {content}")
    return "\n\n".join(lines)


def _extract_json(content: str) -> Dict[str, Any]:
    """Pull the first JSON object out of a possibly-chatty model response."""
    match = re.search(r"\{[\s\S]*\}", content)
    if not match:
        return {}
    try:
        parsed = json.loads(match.group(0))
    except (ValueError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _coerce_inputs(raw: Any) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if isinstance(item, dict):
            key = str(item.get("key") or item.get("name") or "").strip()
            if key:
                out.append(
                    {
                        "key": _slug(key),
                        "description": str(item.get("description") or "").strip(),
                    }
                )
        elif isinstance(item, str) and item.strip():
            out.append({"key": _slug(item), "description": ""})
    return out


def _coerce_checks(raw: Any) -> List[str]:
    out: List[str] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
        elif isinstance(item, dict):
            v = item.get("check") or item.get("description") or item.get("text")
            if v:
                out.append(str(v).strip())
    return out


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", str(text).strip().lower()).strip("_")
    return s or "input"


def _heuristic_goal(messages: List[Dict[str, Any]]) -> str:
    for m in reversed(messages):
        if m.get("role") == "user" and str(m.get("content") or "").strip():
            return str(m["content"]).strip()[:200]
    return "Accomplish the task discussed in the conversation."
