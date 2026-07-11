"""Prompt meta sidecars + the shared classification taxonomy (LB2-U1).

Roles and templates carry classification in a ``<id>.meta.json`` sidecar next
to the prompt file in whichever layer owns it — frontmatter would leak into
PromptComposer output (prompt_composer.py renders the file verbatim). Hooks
carry their meta inside YAML frontmatter instead (their body never reaches
the composer), so this module only owns the SIDECAR seam plus the taxonomy
constants shared verbatim with LB4 (model task tags) and LB6 (task schemas)
— one vocabulary across the platform.

Sidecars are runtime-mutable state: they live in the user layer for user
prompts and travel with copy-on-write promotion for oob prompts (the router
owns that dance). Writes are atomic (tmp+replace). Listing globs are
extension-scoped (roles ``*.md``, templates ``*.jinja``) so ``*.meta.json``
never surfaces as a prompt — a guard test pins that.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── Shared taxonomy (LB2/LB4/LB6 — keep these strings in lockstep) ─────────
# Task-type categories (mapped to intended output kinds).
CATEGORIES = (
    "code",
    "analysis",
    "extraction",
    "classification",
    "planning",
    "review",
    "writing",
    "security",
)
# Prompting techniques.
TECHNIQUES = (
    "few-shot",
    "chain-of-thought",
    "persona",
    "structured-output",
    "critique",
    "guardrail",
)
# Model role classes — same vocabulary as dfRoleColors (main.js) and
# data/discovery/model_benchmarks.json role_fit. model_fit[] entries may be
# one of these OR an exact model-id pin (free-form), so only the role-class
# subset is validated.
MODEL_ROLE_CLASSES = ("reasoning", "coding", "fast", "general", "uncensored")
# Output types — dfFmtDescs keys (display vocabulary, not validated strictly).
OUTPUT_TYPES = (
    "raw",
    "json",
    "json_array",
    "markdown_sections",
    "key_value",
    "csv",
    "regex",
)

# Fields a meta sidecar may carry (client-writable subset excludes
# token_estimate/provenance — those are computed/stamped server-side).
META_FIELDS = (
    "tags",
    "category",
    "technique",
    "intended_output",
    "model_fit",
    "input_scope",
    "output_scope",
    "token_estimate",
    "provenance",
)
WRITABLE_META_FIELDS = (
    "tags",
    "category",
    "technique",
    "intended_output",
    "model_fit",
    "input_scope",
    "output_scope",
)

# chars-per-token heuristic — presented as APPROXIMATE everywhere.
_CHARS_PER_TOKEN = 3.6


def estimate_tokens(text: str) -> int:
    """ceil(chars / 3.6) — approximate, never a gate."""
    return math.ceil(len(text or "") / _CHARS_PER_TOKEN)


def sidecar_path(prompt_path: Path) -> Path:
    """<dir>/<id>.meta.json next to the prompt file (id charset has no dots,
    so with_suffix is unambiguous)."""
    return prompt_path.with_suffix(".meta.json")


def read_meta(prompt_path: Path) -> Optional[Dict[str, Any]]:
    """Sidecar contents for a prompt file, or None. Never raises."""
    sc = sidecar_path(prompt_path)
    try:
        if not sc.is_file():
            return None
        data = json.loads(sc.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def write_meta(prompt_path: Path, meta: Dict[str, Any]) -> None:
    """Atomic tmp+replace sidecar write."""
    sc = sidecar_path(prompt_path)
    sc.parent.mkdir(parents=True, exist_ok=True)
    tmp = sc.with_suffix(sc.suffix + ".tmp")
    tmp.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(sc)  # atomic


def delete_meta(prompt_path: Path) -> bool:
    """Unlink the sidecar (delete_prompt calls this). True when one existed."""
    sc = sidecar_path(prompt_path)
    if sc.is_file():
        sc.unlink()
        return True
    return False


def validate_meta_fields(patch: Dict[str, Any]) -> List[str]:
    """Taxonomy validation for a meta patch. Returns human-readable errors
    (empty == valid). category/technique are validated against the shared
    vocabulary; tags/model_fit/scopes stay free-form (model_fit legally mixes
    role classes with exact model-id pins)."""
    errors: List[str] = []
    cat = patch.get("category")
    if cat is not None and cat not in CATEGORIES:
        errors.append(f"category {cat!r} not in {list(CATEGORIES)}")
    tech = patch.get("technique")
    if tech is not None:
        if not isinstance(tech, list):
            errors.append("technique must be a list")
        else:
            bad = [t for t in tech if t not in TECHNIQUES]
            if bad:
                errors.append(f"technique {bad!r} not in {list(TECHNIQUES)}")
    for key in ("tags", "model_fit"):
        val = patch.get(key)
        if val is not None and (
            not isinstance(val, list) or not all(isinstance(x, str) for x in val)
        ):
            errors.append(f"{key} must be a list of strings")
    for key in ("intended_output", "input_scope", "output_scope"):
        val = patch.get(key)
        if val is not None and not isinstance(val, str):
            errors.append(f"{key} must be a string")
    return errors


def merge_meta(
    existing: Optional[Dict[str, Any]],
    patch: Dict[str, Any],
    body_text: str,
) -> Dict[str, Any]:
    """Merge a validated patch over the existing sidecar and (re)compute
    token_estimate from the prompt body. Only WRITABLE_META_FIELDS merge in;
    None values in the patch are 'not provided', not deletions."""
    merged: Dict[str, Any] = dict(existing or {})
    for key in WRITABLE_META_FIELDS:
        if key in patch and patch[key] is not None:
            merged[key] = patch[key]
    merged["token_estimate"] = estimate_tokens(body_text)
    return merged
