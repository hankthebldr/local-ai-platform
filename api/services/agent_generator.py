#!/usr/bin/env python3
"""
Agent Generator — convert reference documents into draft agents.

The generator runs a short LLM-mediated analysis pass over a source
document (or pasted text) and emits a draft AgentDefinition the user
can review, iterate on, and save. It is intentionally conservative: if
the LLM is unavailable or its output isn't parseable, the generator
falls back to a heuristic draft built directly from the source text so
the UI still produces something useful.

Design notes
------------
* The analyzer prompt asks for strict JSON with a known shape so we can
  parse it without LLM-specific cleanup logic.
* The source document is attached to the draft as a `file` context
  source so the agent can reference it during chat without re-reading.
* `evaluate_agent` runs an agent against a set of {prompt, expected}
  cases and returns pass/fail counts plus per-case responses. This is
  the validation loop the operator drives from the UI.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..logging_config import logger
from ..models.agent_models import AgentDefinition
from ..models.project_models import (
    AgentEvaluationCase,
    AgentEvaluationCaseResult,
    AgentEvaluationReport,
    AgentGenerationResult,
)
from .agent_service import AgentService

ANALYZER_SYSTEM_PROMPT = """You are an agent-builder. Read a reference document and emit a JSON
object describing a focused AI assistant ("agent") that an end-user could chat with to
work productively with the document's subject matter.

Return ONLY valid JSON matching this exact shape (no markdown, no commentary):
{
  "id": "<kebab-case-id-1-to-40-chars>",
  "name": "<short human label>",
  "description": "<1-2 sentence summary>",
  "role": "<one of: reasoning|coding|fast|general|uncensored>",
  "system_prompt": "<3-7 paragraph system prompt grounded in the document>",
  "starters": ["<3-5 opening user prompts users could send>", "..."],
  "tags": ["<3-6 short topical tags>"]
}

Rules:
- The system prompt must reference concrete subject-matter from the document, not
  generic advice. Bake in any domain vocabulary, schemas, or constraints you find.
- Choose role=reasoning for analytical work, role=coding for code, role=fast for
  short factual answers, role=uncensored only if the document explicitly requires
  unrestricted responses.
- Starter prompts must be specific to the document (not generic "How can I help?").
- Tags should be lower-case, short, no spaces (use hyphens).
"""


def _slugify(value: str, fallback: str = "agent") -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-").lower()
    if not s:
        return fallback
    return s[:40]


def _safe_id(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value or ""))


def _trim(text: str, limit: int = 12000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n\n[…truncated…]"


def _heuristic_draft(text: str, name_hint: Optional[str] = None) -> Dict[str, Any]:
    """
    Fallback when the LLM analyzer is unavailable. Builds a usable draft
    from the document text alone (first heading / first paragraph).
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    title = name_hint or next(
        (ln.lstrip("# ").strip() for ln in lines if ln.startswith("#")), None
    )
    if not title:
        title = lines[0][:60] if lines else "Reference Agent"

    summary = " ".join(lines[:6])[:400] or "Agent generated from a reference document."

    agent_id = _slugify(title)
    return {
        "id": agent_id,
        "name": title,
        "description": summary[:200],
        "role": "reasoning",
        "system_prompt": (
            f"You are a focused AI assistant for the topic: {title}.\n\n"
            f"Use the attached reference material as your primary source of truth. "
            f"Quote specific sections when relevant, ask clarifying questions before "
            f"guessing, and refuse to invent details not supported by the reference.\n\n"
            f"Summary of the reference:\n{summary}"
        ),
        "starters": [
            f"Summarise the key points from the reference on {title}.",
            "What concrete steps does this material recommend?",
            "Where in the reference does it cover edge cases or pitfalls?",
        ],
        "tags": [t for t in _slugify(title).split("-") if t][:5] or ["reference"],
    }


class AgentGenerator:
    """LLM-mediated converter from reference text → draft agent definition."""

    def __init__(self, ollama_service: Any):
        self._ollama = ollama_service
        self._agents = AgentService()

    # ── doc → agent ────────────────────────────────────────────────

    def generate_from_text(
        self,
        text: str,
        *,
        name_hint: Optional[str] = None,
        role_hint: Optional[str] = None,
        model: Optional[str] = None,
        source_file: Optional[str] = None,
        include_source_as_context: bool = True,
    ) -> AgentGenerationResult:
        if not text or not text.strip():
            raise ValueError("source text is empty")

        analyzer_input = (
            f"Source filename: {source_file or '(pasted text)'}\n\n"
            f"--- BEGIN REFERENCE ---\n{_trim(text)}\n--- END REFERENCE ---"
        )

        draft: Dict[str, Any]
        used_llm = False
        try:
            draft = self._llm_draft(analyzer_input, model=model)
            used_llm = True
        except Exception as exc:  # noqa: BLE001
            logger.info("Agent generator falling back to heuristic draft: %s", exc)
            draft = _heuristic_draft(text, name_hint=name_hint)

        # User-supplied hints take precedence over the analyzer's picks.
        if name_hint:
            draft["name"] = name_hint
            if not draft.get("id"):
                draft["id"] = _slugify(name_hint)
        if role_hint:
            draft["role"] = role_hint

        draft.setdefault("id", _slugify(draft.get("name", "agent")))
        if not _safe_id(draft["id"]):
            draft["id"] = _slugify(draft["id"])
        draft.setdefault("description", "")
        draft.setdefault("system_prompt", "You are a helpful assistant.")
        draft.setdefault("starters", [])
        draft.setdefault("tags", [])

        # Attach the source as a context entry so the chat surface has it.
        context: List[Dict[str, Any]] = []
        if include_source_as_context:
            if source_file:
                context.append(
                    {
                        "type": "file",
                        "value": source_file,
                        "label": Path(source_file).name,
                    }
                )
            else:
                context.append(
                    {
                        "type": "text",
                        "value": _trim(text, 8000),
                        "label": "Pasted reference",
                    }
                )
        draft["context"] = context

        # Validate by round-tripping through Pydantic so we surface errors
        # to the caller before they get a chance to write it to disk.
        AgentDefinition(**draft)

        return AgentGenerationResult(
            draft=draft,
            suggestions={
                "used_llm": used_llm,
                "model": model,
            },
            source={"file": source_file, "chars": len(text)},
        )

    def generate_from_document(
        self,
        document_id: str,
        *,
        name_hint: Optional[str] = None,
        role_hint: Optional[str] = None,
        model: Optional[str] = None,
    ) -> AgentGenerationResult:
        text, file_path = self._load_document_text(document_id)
        return self.generate_from_text(
            text,
            name_hint=name_hint,
            role_hint=role_hint,
            model=model,
            source_file=str(file_path) if file_path else None,
        )

    def save_draft(self, draft: Dict[str, Any], *, overwrite: bool = False) -> str:
        """Persist a (possibly user-edited) draft to agents/<id>.yaml."""
        defn = AgentDefinition(**draft)
        existing = self._agents.get_agent(defn.id)
        if existing is not None and not overwrite:
            raise FileExistsError(defn.id)
        if existing is None:
            return self._agents.create_agent(defn)
        self._agents.update_agent(defn.id, defn)
        return str(self._agents.agents_dir / f"{defn.id}.yaml")

    # ── evaluation loop ────────────────────────────────────────────

    def evaluate_agent(
        self, agent_id: str, cases: List[AgentEvaluationCase]
    ) -> AgentEvaluationReport:
        """
        Run a list of {prompt, expected_contains} cases against an agent
        and return pass/fail counts plus per-case details.

        Each case is sent as a fresh single-turn conversation so cases
        don't poison each other.
        """
        defn = self._agents.get_agent(agent_id)
        if defn is None:
            raise KeyError(agent_id)

        results: List[AgentEvaluationCaseResult] = []
        passed = failed = 0
        for case in cases:
            t0 = time.monotonic()
            response = ""
            try:
                messages = self._agents.build_messages(
                    defn, [{"role": "user", "content": case.prompt}]
                )
                resp = self._ollama.chat(
                    model=defn.model or "dolphin3",
                    messages=messages,
                    options={"temperature": defn.temperature or 0.7},
                )
                response = (resp or {}).get("message", {}).get("content", "") or ""
            except Exception as exc:  # noqa: BLE001
                response = f"[error: {exc}]"

            ok = True
            if case.expected_contains:
                ok = case.expected_contains.lower() in response.lower()
            if ok:
                passed += 1
            else:
                failed += 1
            results.append(
                AgentEvaluationCaseResult(
                    prompt=case.prompt,
                    response=response,
                    expected_contains=case.expected_contains,
                    passed=ok,
                    duration_seconds=round(time.monotonic() - t0, 3),
                )
            )

        return AgentEvaluationReport(
            agent_id=agent_id, passed=passed, failed=failed, cases=results
        )

    # ── internals ──────────────────────────────────────────────────

    def _llm_draft(self, analyzer_input: str, model: Optional[str]) -> Dict[str, Any]:
        """Call the local LLM with the analyzer system prompt and parse the JSON output."""
        pick_model = model or self._pick_model()
        resp = self._ollama.chat(
            model=pick_model,
            messages=[
                {"role": "system", "content": ANALYZER_SYSTEM_PROMPT},
                {"role": "user", "content": analyzer_input},
            ],
            options={"temperature": 0.2},
        )
        content = (resp or {}).get("message", {}).get("content", "") or ""
        # Trim to the JSON object even if the model added prose.
        match = re.search(r"\{[\s\S]*\}", content)
        if not match:
            raise RuntimeError("LLM returned no JSON object")
        return json.loads(match.group(0))

    def _pick_model(self) -> str:
        """Choose a reasoning-friendly local model for the analyzer."""
        try:
            models = self._ollama.list_models() or []
            names = [m.get("name") or "" for m in models]
            for hint in ("reason", "r1", "qwen", "mixtral", "dolphin"):
                for n in names:
                    if hint in n.lower():
                        return n
            if names:
                return names[0]
        except Exception:  # noqa: BLE001
            pass
        return "dolphin3"

    def _load_document_text(self, document_id: str) -> tuple[str, Optional[Path]]:
        """Pull plain text + source path for a previously uploaded document."""
        try:
            from .document_service import DocumentService  # type: ignore
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"document service unavailable: {exc}")

        svc = DocumentService()
        doc = None
        if hasattr(svc, "get_document"):
            doc = svc.get_document(document_id)
        if not doc:
            raise FileNotFoundError(document_id)

        text = ""
        for candidate in ("text", "content", "raw_text"):
            value = doc.get(candidate) if isinstance(doc, dict) else None
            if isinstance(value, str) and value.strip():
                text = value
                break

        path: Optional[Path] = None
        for field in ("path", "file", "storage_path"):
            value = doc.get(field) if isinstance(doc, dict) else None
            if isinstance(value, str) and value:
                path = Path(value)
                break

        if not text and path and path.exists():
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except Exception as exc:  # noqa: BLE001
                raise RuntimeError(f"failed to read document file: {exc}")

        if not text:
            raise RuntimeError("document has no readable text")
        return text, path
