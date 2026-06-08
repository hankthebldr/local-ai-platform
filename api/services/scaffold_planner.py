"""
Scaffold planner — turn an editable spec into a runnable workflow DEFINITION.

Hybrid, local-first authoring for the chat-led Composer:

  1. TEMPLATE MATCH — score the spec against the curated workflow index; if a
     strong match exists, reuse that proven workflow (it already loads in the
     Composer and runs on the engine).
  2. LOCAL LLM PLAN — otherwise a local model composes a fresh chain bound to
     the user's INSTALLED LOCAL primitives (roles / agents), each step labelled
     with the LOCAL model it will run on, so the Composer can show "who handles
     what, on which local model".
  3. FALLBACK — if the model is unavailable or returns junk, a deterministic
     intake -> work -> validate chain is synthesized so the UI always primes.

Pre-execution authoring only: emits the same ``WorkflowDefinition`` JSON the
Composer already loads (``GET /api/workflows/{id}``). Never imports the engine.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from ..logging_config import logger
from ..models.workflow_models import WorkflowDefinition
from ..services.model_resolver import ModelResolver
from ..services.ollama_service import OllamaService
from ..services.workflow_index import get_workflow_index

# Roles the resolver understands; the planner binds steps to these by default.
_KNOWN_ROLES = ["reasoning", "coding", "fast", "general", "uncensored"]

# A match must clear this Jaccard-ish overlap to reuse a template; below it we
# compose a fresh plan instead of forcing a poor fit.
_MATCH_THRESHOLD = 0.16

_STOPWORDS = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "of",
    "to",
    "for",
    "with",
    "in",
    "on",
    "is",
    "that",
    "this",
    "it",
    "be",
    "as",
    "by",
    "from",
    "at",
    "into",
    "your",
    "you",
    "make",
    "want",
    "need",
    "should",
    "would",
    "create",
    "build",
    "workflow",
}

_PLAN_SYSTEM_PROMPT = """You are the workflow planner of a LOCAL, self-hosted AI platform.
Given a SPEC (goal, inputs, checks) and the LOCAL primitives installed on this machine,
compose a small agentic workflow as a DAG. Every step runs on a LOCAL model.

Return ONLY a JSON object, no prose, with exactly this shape:
{
  "name": "<short human name>",
  "description": "<one sentence>",
  "steps": [
    {
      "id": "<snake_case_id>",
      "name": "<short name>",
      "role": "<one of the provided roles>",
      "system_prompt": "<the instruction this step follows>",
      "inputs": ["seed.<input_key>" or "<upstream_step_id>.<output>"],
      "outputs": ["<snake_case_output>"],
      "depends_on": ["<upstream_step_id>"]
    }
  ]
}

Rules:
- 2-5 steps. The first step reads from the seed inputs (seed.<key>). Chain the rest with
  depends_on and reference upstream outputs as "<step_id>.<output>".
- Bind each step's "role" to one of the provided roles, matched to the work it does.
- Turn each CHECK into (or fold into) a validation step near the end.
- Every step MUST have at least one output. Keep ids unique and snake_case.
"""


class ScaffoldPlannerService:
    """Compose a runnable workflow definition from an editable spec."""

    def __init__(self, ollama: OllamaService, resolver: Optional[ModelResolver] = None):
        self.ollama = ollama
        self.resolver = resolver or ModelResolver(ollama)

    # ── public API ────────────────────────────────────────────────────
    def scaffold(
        self,
        goal: str,
        inputs: Optional[List[Dict[str, str]]] = None,
        checks: Optional[List[str]] = None,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        inputs = _norm_inputs(inputs or [])
        checks = [c for c in (checks or []) if str(c).strip()]

        # 1) Template match against the curated index.
        match_id, match_defn = self._best_template(goal, checks)
        if match_defn is not None:
            definition = match_defn
            source = "template"
        else:
            match_id = None
            # 2) Local LLM plan, else 3) deterministic fallback.
            definition = self._llm_plan(goal, inputs, checks, model) or _fallback_plan(
                goal, inputs, checks
            )
            source = "llm" if definition.get("_planned") else "fallback"
            definition.pop("_planned", None)

        # Resolve each step's concrete local model (for the plan card) + validate.
        self._bind_models(definition)
        definition = _validated(definition)
        return {
            "definition": definition,
            "source": source,
            "matched_workflow_id": match_id,
            "bindings": _bindings(definition),
        }

    # ── template matching ─────────────────────────────────────────────
    def _best_template(
        self, goal: str, checks: List[str]
    ) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        try:
            index = get_workflow_index().build_index()
        except Exception as exc:  # noqa: BLE001
            logger.info("Workflow index unavailable for scaffold match: %s", exc)
            return None, None

        query = _tokens(" ".join([goal] + checks))
        if not query:
            return None, None

        best_id, best_file, best_score = None, None, 0.0
        for wf in index.get("workflows", []):
            hay = _tokens(
                " ".join(
                    [
                        str(wf.get("name") or ""),
                        str(wf.get("description") or ""),
                        " ".join(wf.get("tags") or []),
                        str(wf.get("category") or ""),
                    ]
                )
            )
            score = _overlap(query, hay)
            if score > best_score:
                best_id, best_file, best_score = wf.get("id"), wf.get("file"), score

        if best_score < _MATCH_THRESHOLD or not best_file:
            return None, None

        defn = _load_yaml(best_file)
        if defn is None:
            return None, None
        logger.info("Scaffold matched template %s (score=%.2f)", best_id, best_score)
        return best_id, defn

    # ── local LLM plan ────────────────────────────────────────────────
    def _llm_plan(
        self,
        goal: str,
        inputs: List[Dict[str, str]],
        checks: List[str],
        model: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        primitives = self._enumerate_primitives()
        user = json.dumps(
            {
                "spec": {"goal": goal, "inputs": inputs, "checks": checks},
                "available": primitives,
            },
            indent=2,
        )
        try:
            # Resolve INSIDE the guard: with Ollama down, resolve() raises a
            # 503-class error too. Returning None here lets scaffold() fall
            # through to the deterministic _fallback_plan, honouring the
            # always-primes contract instead of 503-ing the UI.
            resolved = self.resolver.resolve(
                model=model, role="reasoning", default_role="reasoning"
            )
            result = self.ollama.chat(
                model=resolved,
                messages=[
                    {"role": "system", "content": _PLAN_SYSTEM_PROMPT},
                    {"role": "user", "content": user},
                ],
                temperature=0.3,
                max_tokens=2048,
            )
            data = _extract_json((result or {}).get("content", "") or "")
        except Exception as exc:  # noqa: BLE001
            logger.info("Scaffold LLM plan failed, using fallback: %s", exc)
            return None

        steps = data.get("steps")
        if not isinstance(steps, list) or not steps:
            return None

        clean_steps = _sanitize_steps(steps)
        if not clean_steps:
            return None

        defn = _assemble(
            name=str(data.get("name") or "").strip() or _name_from_goal(goal),
            description=str(data.get("description") or "").strip() or goal,
            inputs=inputs,
            steps=clean_steps,
        )
        defn["_planned"] = True
        return defn

    def _enumerate_primitives(self) -> Dict[str, Any]:
        """Best-effort, in-process enumeration of installed local primitives.

        Every probe is guarded — a missing service just yields fewer options,
        never a failed scaffold."""
        agents: List[str] = []
        try:
            from ..services.agent_service import AgentService

            svc = AgentService()
            listed = svc.list_agents()
            if isinstance(listed, dict):
                agents = list(listed.keys())
            elif isinstance(listed, list):
                agents = [
                    str(a.get("id") or a.get("name"))
                    for a in listed
                    if isinstance(a, dict) and (a.get("id") or a.get("name"))
                ]
        except Exception as exc:  # noqa: BLE001
            logger.debug("agent enumeration skipped: %s", exc)
        return {"roles": _KNOWN_ROLES, "agents": agents[:24]}

    # ── model binding ─────────────────────────────────────────────────
    def _bind_models(self, definition: Dict[str, Any]) -> None:
        """Stamp each step with the concrete LOCAL model it will run on, so the
        plan card can show provenance. Guarded — leaves model unset on failure."""
        for step in definition.get("steps", []):
            if step.get("model"):
                continue
            role = step.get("role") or definition.get("defaults", {}).get("role")
            try:
                step["model"] = self.resolver.resolve(role=role, default_role="general")
            except Exception:  # noqa: BLE001
                pass


# ── module helpers ────────────────────────────────────────────────────
def _validated(definition: Dict[str, Any]) -> Dict[str, Any]:
    """Validate against the Pydantic model; on failure fall back to a minimal
    valid plan so the Composer always receives loadable JSON."""
    try:
        WorkflowDefinition(**definition)
        return definition
    except Exception as exc:  # noqa: BLE001
        logger.info("Scaffold definition failed validation, minimizing: %s", exc)
        # Defensive: a malformed definition may carry a non-dict context or a
        # non-list inputs — coerce before re-deriving so the fallback can't
        # itself throw.
        ctx = definition.get("context")
        ctx_inputs = ctx.get("inputs") if isinstance(ctx, dict) else None
        minimal = _fallback_plan(
            str(definition.get("description") or definition.get("name") or "task"),
            _norm_inputs(ctx_inputs if isinstance(ctx_inputs, list) else []),
            [],
        )
        minimal.pop("_planned", None)
        return minimal


def _assemble(
    name: str,
    description: str,
    inputs: List[Dict[str, str]],
    steps: List[Dict[str, Any]],
) -> Dict[str, Any]:
    return {
        "id": _slug(name) or "composed-workflow",
        "name": name,
        "description": description,
        "version": "0.1",
        "schema_version": 1,
        "context": {"inputs": inputs},
        "defaults": {"role": "reasoning", "temperature": 0.5, "max_tokens": 4096},
        "steps": steps,
    }


def _fallback_plan(
    goal: str, inputs: List[Dict[str, str]], checks: List[str]
) -> Dict[str, Any]:
    """Deterministic intake -> draft -> validate chain. Always valid."""
    seed = inputs[0]["key"] if inputs else "request"
    if not inputs:
        inputs = [{"key": "request", "description": "What you want accomplished"}]
    check_text = (
        "; ".join(checks) if checks else "Output is correct, complete, and on-spec."
    )
    steps = [
        {
            "id": "intake",
            "name": "Frame the request",
            "role": "general",
            "system_prompt": "Restate the request precisely and list what a good result must include.",
            "inputs": [f"seed.{seed}"],
            "outputs": ["framing"],
            "depends_on": [],
        },
        {
            "id": "draft",
            "name": "Do the work",
            "role": "reasoning",
            "system_prompt": f"Accomplish the goal: {goal}",
            "inputs": ["intake.framing", f"seed.{seed}"],
            "outputs": ["draft"],
            "depends_on": ["intake"],
        },
        {
            "id": "validate",
            "name": "Validate & finalize",
            "role": "reasoning",
            "system_prompt": f"Review the draft against these checks: {check_text}. "
            "Fix issues and return the final result.",
            "inputs": ["draft.draft"],
            "outputs": ["result"],
            "depends_on": ["draft"],
        },
    ]
    return _assemble(_name_from_goal(goal), goal, inputs, steps)


def _sanitize_steps(steps: List[Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen: set = set()
    for i, raw in enumerate(steps):
        if not isinstance(raw, dict):
            continue
        sid = _slug(str(raw.get("id") or raw.get("name") or f"step_{i + 1}"))
        if not sid or sid in seen:
            sid = f"step_{i + 1}"
        seen.add(sid)
        outputs = raw.get("outputs")
        if not isinstance(outputs, list) or not outputs:
            outputs = ["output"]
        outputs = [_slug(str(o)) for o in outputs if str(o).strip()] or ["output"]
        inputs = raw.get("inputs")
        inputs = (
            [str(x).strip() for x in inputs if str(x).strip()]
            if isinstance(inputs, list)
            else []
        )
        deps = raw.get("depends_on")
        deps = (
            [_slug(str(d)) for d in deps if str(d).strip()]
            if isinstance(deps, list)
            else []
        )
        role = str(raw.get("role") or "reasoning").strip()
        out.append(
            {
                "id": sid,
                "name": str(raw.get("name") or sid.replace("_", " ").title()),
                "role": role,
                "system_prompt": str(
                    raw.get("system_prompt") or raw.get("prompt") or ""
                ).strip()
                or f"Complete the '{sid}' step.",
                "inputs": inputs,
                "outputs": outputs,
                "depends_on": deps,
            }
        )
    return out


def _bindings(definition: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Flatten the per-step "who handles this, on which local model" view."""
    out: List[Dict[str, Any]] = []
    for step in definition.get("steps", []):
        out.append(
            {
                "step_id": step.get("id"),
                "name": step.get("name"),
                "role": step.get("role"),
                "model": step.get("model"),
                "kind": step.get("kind", "llm"),
            }
        )
    return out


def _load_yaml(rel_path: str) -> Optional[Dict[str, Any]]:
    """Load a workflow template by the index 'file' path. The index stores
    paths relative to the repo root, but we don't assume cwd == repo root:
    try the path as-is, then cwd-relative, then by name under WORKFLOWS_DIR."""
    p = Path(rel_path)
    candidates = [p]
    if not p.is_absolute():
        candidates.append(Path.cwd() / rel_path)
        wf_dir = os.getenv("WORKFLOWS_DIR")
        if wf_dir:
            candidates.append(Path(wf_dir) / p.name)
    for c in candidates:
        try:
            if c.is_file():
                data = yaml.safe_load(c.read_text(encoding="utf-8"))
                return data if isinstance(data, dict) else None
        except Exception as exc:  # noqa: BLE001
            logger.info("Could not load workflow template %s: %s", c, exc)
    logger.info("Workflow template not found: %s", rel_path)
    return None


def _extract_json(content: str) -> Dict[str, Any]:
    match = re.search(r"\{[\s\S]*\}", content)
    if not match:
        return {}
    try:
        parsed = json.loads(match.group(0))
    except (ValueError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _norm_inputs(inputs: List[Any]) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for item in inputs or []:
        if isinstance(item, dict) and (item.get("key") or item.get("name")):
            out.append(
                {
                    "key": _slug(str(item.get("key") or item.get("name"))),
                    "description": str(item.get("description") or "").strip(),
                }
            )
        elif isinstance(item, str) and item.strip():
            out.append({"key": _slug(item), "description": ""})
    return out


def _tokens(text: str) -> set:
    raw = re.findall(r"[a-z0-9]+", str(text).lower())
    return {t for t in raw if len(t) > 2 and t not in _STOPWORDS}


def _overlap(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", str(text).strip().lower()).strip("_")
    return s


def _name_from_goal(goal: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", goal)[:5]
    return (" ".join(words)).title() or "Composed Workflow"
