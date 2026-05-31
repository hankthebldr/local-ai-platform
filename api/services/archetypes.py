"""
Step archetypes — declarative purpose hints.

An archetype is a named pattern of (model role + companion MCPs + companion
skills) covering a common step purpose: ``bash_script``, ``documentation``,
``xsiam_analysis``, etc.

What the compiler does with this
--------------------------------

1. **Inference.** When a step doesn't declare ``archetype`` explicitly,
   ``infer_archetype(step)`` matches its (role, declared tools, declared
   skills) against every registered archetype's trigger set. Returns the
   best match if its score crosses a threshold, else None ("generic step,
   no archetype assumptions").

2. **Composer assist.** The ``/api/workflows/composer/assist`` endpoint
   uses ``infer_archetype`` + ``get_archetype`` to surface
   companion-MCP / companion-skill suggestions when an operator declares
   only part of a pattern (Phase 2c.3).

3. **Resource maximization (Phase 2b).** When the compiler downsizes a
   model on a contention step, it stays in-archetype: a ``bash_script``
   step's smaller model is a smaller *coding* model, not a writing model.

The registry is extensible via plugin manifests (Phase 2c.2 design):
``plugins/<id>/archetypes.yaml`` is read at plugin scan time and merged
through ``extend_archetypes``. Plugins can't override built-in archetypes —
collisions log a warning and are ignored.

v1 (1.3.0) ships with the 9 archetypes below. Plugin authors can register
custom ones; demand-driven additions to the built-in set land in 1.4.x.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..logging_config import logger
from ..models.workflow_models import AgentStep

# ── Built-in registry ────────────────────────────────────────────────────


# Each entry:
#   default_role       — role the compiler assumes when the step has no model
#   companion_mcps     — MCPs the composer suggests when the archetype matches
#   companion_skills   — skill ids (no plugin prefix) likewise suggested
#   trigger_mcps       — declared MCP ids that vote FOR this archetype
#   trigger_skills     — declared skill ids that vote FOR this archetype
#   description        — human caption for the composer panel
ARCHETYPES: Dict[str, Dict[str, Any]] = {
    "bash_script": {
        "default_role": "coding",
        "companion_mcps": ["bash-mcp", "filesystem-local"],
        "companion_skills": ["coder"],
        "trigger_mcps": ["bash-mcp"],
        "trigger_skills": [],
        "description": "Generate and execute shell scripts",
    },
    "code_review": {
        "default_role": "coding",
        "companion_mcps": [],
        "companion_skills": ["coder", "reviewer"],
        "trigger_mcps": [],
        "trigger_skills": ["reviewer"],
        "description": "Review diffs or PRs",
    },
    "documentation": {
        "default_role": "reasoning",
        "companion_mcps": ["web-search", "filesystem-local"],
        "companion_skills": ["research", "concise-writer"],
        "trigger_mcps": ["web-search"],
        "trigger_skills": ["research"],
        "description": "Write documentation from sources",
    },
    "research_brief": {
        "default_role": "reasoning",
        "companion_mcps": ["web-search"],
        "companion_skills": ["research"],
        "trigger_mcps": ["web-search"],
        "trigger_skills": ["research"],
        "description": "Topic investigation",
    },
    "extraction": {
        "default_role": "lightweight",
        "companion_mcps": [],
        "companion_skills": ["concise-writer"],
        "trigger_mcps": [],
        "trigger_skills": ["concise-writer"],
        "description": "Pull structured data from text",
    },
    "synthesis": {
        "default_role": "reasoning",
        "companion_mcps": [],
        "companion_skills": ["concise-writer"],
        "trigger_mcps": [],
        "trigger_skills": [],
        "description": "Combine prior outputs",
    },
    "data_lookup": {
        "default_role": "lightweight",
        "companion_mcps": ["filesystem-local", "rag"],
        "companion_skills": [],
        "trigger_mcps": ["filesystem-local", "rag"],
        "trigger_skills": [],
        "description": "Read a file or search a vector store",
    },
    "xsiam_analysis": {
        "default_role": "reasoning",
        "companion_mcps": [],
        "companion_skills": ["xdm-rule-writer", "xql-validator", "rag-query-crafter"],
        "trigger_mcps": [],
        "trigger_skills": ["xdm-rule-writer", "xql-validator"],
        "description": "XSIAM detection-engineering",
    },
    "triage": {
        "default_role": "lightweight",
        "companion_mcps": [],
        "companion_skills": ["concise-writer"],
        "trigger_mcps": [],
        "trigger_skills": [],
        "description": "First-pass classification",
    },
}


_BUILTIN_NAMES = frozenset(ARCHETYPES.keys())

# Minimum trigger-overlap score for inference to claim a match. Below this we
# return None to signal "no confident archetype — treat as generic step". The
# weights are: MCP trigger overlap × 2 + skill trigger overlap × 1 + role bonus.
# Threshold of 2 means "either one MCP trigger, OR a role match plus a skill".
_INFERENCE_THRESHOLD = 2


# ── Public API ──────────────────────────────────────────────────────────


def get_archetype(name: str) -> Optional[Dict[str, Any]]:
    """Return the spec for ``name``, or None when unregistered."""
    return ARCHETYPES.get(name)


def list_archetypes() -> List[Dict[str, Any]]:
    """Snapshot of all registered archetypes — used by the composer."""
    return [{"name": name, **spec} for name, spec in sorted(ARCHETYPES.items())]


def infer_archetype(step: AgentStep) -> Optional[str]:
    """Match ``step`` against ARCHETYPES; return the best id, or None.

    Explicit ``step.archetype`` wins — but only if it names a registered
    archetype (an unknown declared archetype falls through to inference so
    a typo can't pin the step to a phantom).

    Scoring:
      MCP trigger overlap × 2 + skill trigger overlap + (1 if role matches
      default_role else 0). Highest score wins ties; below ``_INFERENCE_
      THRESHOLD`` returns None.
    """
    if step.archetype and step.archetype in ARCHETYPES:
        return step.archetype

    declared_mcps = {t.mcp.split(".", 1)[0] for t in step.tools if t.mcp}
    declared_skills = set()
    for skill_ref in step.skills:
        if "." in skill_ref:
            declared_skills.add(skill_ref.split(".", 1)[1])

    best: Optional[str] = None
    best_score = 0
    for name, spec in ARCHETYPES.items():
        score = len(declared_mcps & set(spec["trigger_mcps"])) * 2 + len(
            declared_skills & set(spec["trigger_skills"])
        )
        if step.role and step.role == spec["default_role"]:
            score += 1
        if score > best_score:
            best, best_score = name, score
    return best if best_score >= _INFERENCE_THRESHOLD else None


def suggest_companions(
    step: AgentStep, archetype_name: Optional[str] = None
) -> Dict[str, Any]:
    """Compute companion suggestions for the composer.

    Returns the inferred archetype (or the one the caller passed), and the
    subset of the archetype's companion MCPs / skills that the step
    *doesn't* already declare — the things the composer should suggest
    adding.

    Used by ``POST /api/workflows/composer/assist`` and any other UI that
    surfaces "complete this pattern" hints.
    """
    arch = archetype_name or infer_archetype(step)
    if arch is None or arch not in ARCHETYPES:
        return {
            "inferred_archetype": None,
            "suggested_role": None,
            "suggested_mcps": [],
            "suggested_skills": [],
            "warnings": [],
        }

    spec = ARCHETYPES[arch]
    declared_mcps = {t.mcp.split(".", 1)[0] for t in step.tools if t.mcp}
    declared_skills = set()
    for skill_ref in step.skills:
        if "." in skill_ref:
            declared_skills.add(skill_ref.split(".", 1)[1])

    suggested_mcps = [m for m in spec["companion_mcps"] if m not in declared_mcps]
    suggested_skills = [s for s in spec["companion_skills"] if s not in declared_skills]

    warnings: List[Dict[str, Any]] = []
    # Archetype mismatch: the operator declared a role that doesn't match the
    # archetype's default — they may have grabbed the wrong tools for the
    # role they had in mind (e.g. role=coding + web-search → archetype
    # research_brief but the role smells like bash_script).
    if step.role and step.role != spec["default_role"]:
        warnings.append(
            {
                "code": "archetype_role_mismatch",
                "archetype": arch,
                "declared_role": step.role,
                "expected_role": spec["default_role"],
                "message": (
                    f"Archetype '{arch}' usually pairs with role "
                    f"'{spec['default_role']}', but step declares '{step.role}'."
                ),
            }
        )

    return {
        "inferred_archetype": arch,
        "suggested_role": spec["default_role"] if not step.role else None,
        "suggested_mcps": suggested_mcps,
        "suggested_skills": suggested_skills,
        "warnings": warnings,
    }


# ── Extension point ─────────────────────────────────────────────────────


def extend_archetypes(plugin_archetypes: Dict[str, Dict[str, Any]]) -> None:
    """Merge plugin-declared archetypes into the registry.

    Plugin authors register custom archetypes via
    ``plugins/<id>/archetypes.yaml``, loaded at plugin scan time. Built-in
    archetypes can't be overridden — a collision logs a warning and the
    plugin entry is ignored.
    """
    for name, spec in plugin_archetypes.items():
        if name in _BUILTIN_NAMES:
            logger.warning(
                "Plugin archetype '%s' clashes with a built-in; ignored", name
            )
            continue
        if name in ARCHETYPES:
            logger.warning(
                "Plugin archetype '%s' already registered by another plugin; ignored",
                name,
            )
            continue
        # Sanity: every registered spec has the same keys.
        defaults = {
            "default_role": "general",
            "companion_mcps": [],
            "companion_skills": [],
            "trigger_mcps": [],
            "trigger_skills": [],
            "description": "",
        }
        merged = {**defaults, **spec}
        ARCHETYPES[name] = merged
        logger.info("Registered plugin archetype '%s'", name)
