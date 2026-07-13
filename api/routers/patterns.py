"""Patterns library — Composer pattern presets as a first-class Library kind (PT-1).

A **PatternSchema** is a persisted, taggable blueprint for a whole agentic
sub-DAG: the exact shape the Composer's Patterns bench drops onto the canvas
(``id · name · complexity · kind · desc · steps [· budget_presets]``). The
Patterns library manages, creates, edits, promotes, and deletes these presets
and feeds the Composer Patterns bench a "Library" section AFTER the 8 built-in
statics — WITHOUT ever mutating the frozen ``dfPatternTemplates`` array in
main.js (the bench renders the statics from JS; user patterns ride their own
``dfUserPatterns`` Map + the same ``application/df-pattern`` drop MIME).

Storage is LAYERED (the prompts.py precedent), but the oob layer is a single
curated CATALOG file (the tasks.py precedent), not a directory:

  oob  -> api/config/patterns_catalog.json          the 8 statics, source:builtin
  user -> user_storage_root/patterns/<id>.json      writable operator layer

Listing merges both layers with user shadowing builtin by id; each record
carries ``provenance: 'oob'|'user'`` derived from the winning layer. ALL writes
land user-side: create writes there directly (409 when the id already exists in
EITHER layer — edit/promote a shipped one instead), PATCH of a builtin id
performs copy-on-write into the user layer (auto-promote — provenance flips
honestly), DELETE removes the user copy (reverting to the builtin when one
exists) and returns 403 on a pure-builtin id. POST /{id}/promote copies the
builtin record into the user layer explicitly (409 when a user copy exists).

SAFETY RAIL: every stored pattern's ``steps`` must construct through
``WorkflowDefinition(**...)`` (the frozen model IS the scaffoldability
validator) — an un-scaffoldable DAG is rejected 422 at save time, before it can
poison the bench or a drop. The model is imported READ-ONLY; the frozen engine
files are never edited.

Path traversal is rejected by an id-charset allowlist AND resolved-path
containment (the same discipline as prompts.py ``_path`` — this repo had a real
glob-traversal incident). Writes are atomic (tmp+replace). CRUD writes are
master-key gated (``require_master_key``); reads stay open. There is no
discovery/egress surface for patterns — presets are local by design.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..logging_config import logger
from ..middleware import require_master_key

router = APIRouter(prefix="/api/patterns", tags=["patterns"])

_REPO_ROOT = Path(__file__).resolve().parents[2]
# Curated oob layer — the COPY'd repo tree (persistence seam 1). Ships with the
# image, never written to; the 8 dfPatternTemplates as source:builtin seeds.
_CATALOG_FILE = _REPO_ROOT / "api" / "config" / "patterns_catalog.json"
# user layer fallback when no deployment is detected (bare unit tests / dev).
_USER_FALLBACK = _REPO_ROOT / "data" / "patterns"

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")
Complexity = Literal["SIMPLE", "COMPLEX"]


def _patterns_root() -> Path:
    """user_storage_root/patterns — deployment-resolved, test-patchable."""
    try:
        from ..services.deployment import _get_current

        return _get_current().user_storage_root / "patterns"
    except Exception:  # noqa: BLE001 — no deployment detected (unit tests)
        return _USER_FALLBACK


def _pattern_path(pattern_id: str, must_exist: bool = True) -> Path:
    """Resolve one pattern id to its user-layer JSON file with full containment."""
    if not _ID_RE.match(pattern_id or ""):
        raise HTTPException(
            status_code=400,
            detail="invalid pattern id (alnum start, alnum/_/-, <=80)",
        )
    base = _patterns_root().resolve()
    candidate = (base / f"{pattern_id}.json").resolve()
    try:
        candidate.relative_to(base)
    except ValueError:
        raise HTTPException(status_code=400, detail="path escapes pattern library")
    if must_exist and not candidate.is_file():
        raise HTTPException(
            status_code=404, detail=f"pattern '{pattern_id}' not found"
        )
    return candidate


def _write_atomic(p: Path, data: Dict[str, Any]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(p)  # atomic


# ── Schema model ─────────────────────────────────────────────────────────────


class PatternSchema(BaseModel):
    id: str
    name: str
    complexity: Complexity = "SIMPLE"
    kind: str = "llm"
    desc: str = ""
    # The pattern's top-level engine steps — opaque here, validated through
    # WorkflowDefinition (the safety rail). A COMPLEX pattern nests body /
    # branches / gather / workers inside these entries.
    steps: List[Dict[str, Any]] = Field(default_factory=list)
    # Optional ralph-style budget presets keyed by name (standard / long_running).
    budget_presets: Optional[Dict[str, Dict[str, Any]]] = None
    tags: List[str] = Field(default_factory=list)
    provenance: Optional[Dict[str, Any]] = None
    source: Literal["builtin", "user"] = "user"


class PatternPatch(BaseModel):
    """PATCH body — a full edit of the mutable fields (copy-on-write for a
    builtin id). id is taken from the path; source is always forced to 'user'."""

    name: Optional[str] = None
    complexity: Optional[Complexity] = None
    kind: Optional[str] = None
    desc: Optional[str] = None
    steps: List[Dict[str, Any]] = Field(default_factory=list)
    budget_presets: Optional[Dict[str, Dict[str, Any]]] = None
    tags: Optional[List[str]] = None


# ── Safety rail: every stored pattern must scaffold ──────────────────────────


def _validate_scaffoldable(pattern_id: str, name: str, steps: List[Dict[str, Any]]) -> None:
    """A stored pattern's steps MUST construct through the frozen
    WorkflowDefinition (the model IS the scaffoldability validator). An
    un-scaffoldable DAG is a 422, not a silently-broken bench card. The model
    is imported READ-ONLY — the frozen engine files are never touched."""
    from ..models.workflow_models import WorkflowDefinition

    if not steps:
        raise HTTPException(
            status_code=422, detail="a pattern must declare at least one step"
        )
    try:
        WorkflowDefinition(id=f"pattern-{pattern_id}", name=name or pattern_id, steps=steps)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 — pydantic/value errors → 422
        raise HTTPException(
            status_code=422,
            detail=f"pattern steps are not a scaffoldable workflow: {exc}",
        )


def _clean_schema(
    body: PatternSchema, *, pattern_id: str, source: str
) -> Dict[str, Any]:
    """Normalize a schema for persistence: force id/source, run the safety rail,
    drop an empty budget_presets."""
    data = body.model_dump()
    data["id"] = pattern_id
    data["source"] = source
    _validate_scaffoldable(pattern_id, data.get("name") or "", data.get("steps") or [])
    if not data.get("budget_presets"):
        data.pop("budget_presets", None)
    if not data.get("provenance"):
        data.pop("provenance", None)
    return data


# ── Curated catalog (oob) + user layer (read side) ──────────────────────────


def _load_catalog() -> List[Dict[str, Any]]:
    """The 8 curated builtin seeds from the COPY'd tree. Never raises."""
    try:
        doc = json.loads(_CATALOG_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("patterns_catalog.json unreadable — no builtin seeds")
        return []
    pats = doc.get("patterns") if isinstance(doc, dict) else doc
    out: List[Dict[str, Any]] = []
    for rec in pats if isinstance(pats, list) else []:
        if isinstance(rec, dict) and rec.get("id"):
            rec = dict(rec)
            rec["source"] = "builtin"
            out.append(rec)
    return out


def _catalog_map() -> Dict[str, Dict[str, Any]]:
    return {r["id"]: r for r in _load_catalog() if r.get("id")}


def _read_pattern_file(p: Path) -> Optional[Dict[str, Any]]:
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    data.setdefault("id", p.stem)
    data["source"] = "user"
    return data


def _list_user_patterns() -> List[Dict[str, Any]]:
    base = _patterns_root()
    if not base.exists():
        return []
    out: List[Dict[str, Any]] = []
    for p in sorted(base.glob("*.json")):
        if p.name.endswith(".tmp"):
            continue
        rec = _read_pattern_file(p)
        if rec:
            out.append(rec)
    return out


def _merged() -> Dict[str, Dict[str, Any]]:
    """Builtin ∪ user, user shadowing builtin by id; each record's provenance
    reflects the WINNING layer."""
    merged: Dict[str, Dict[str, Any]] = {}
    for rec in _load_catalog():
        r = dict(rec)
        r["provenance"] = "oob"
        merged[r["id"]] = r
    for rec in _list_user_patterns():
        r = dict(rec)
        r["provenance"] = "user"
        merged[r["id"]] = r
    return merged


def _resolve(pattern_id: str) -> Tuple[Dict[str, Any], str]:
    """(record, layer) for the WINNING copy — user shadows builtin. 404 if
    neither. Charset-checked so a hostile id never reaches the catalog map."""
    if not _ID_RE.match(pattern_id or ""):
        raise HTTPException(status_code=400, detail="invalid pattern id")
    user_p = _pattern_path(pattern_id, must_exist=False)
    if user_p.is_file():
        rec = _read_pattern_file(user_p)
        if rec is None:
            raise HTTPException(
                status_code=400, detail=f"pattern '{pattern_id}' is corrupt"
            )
        return rec, "user"
    builtin = _catalog_map().get(pattern_id)
    if builtin is not None:
        return dict(builtin), "oob"
    raise HTTPException(status_code=404, detail=f"pattern '{pattern_id}' not found")


# ── CRUD ─────────────────────────────────────────────────────────────────────


@router.get("", response_model=List[PatternSchema])
async def list_patterns(
    tag: Optional[str] = None, complexity: Optional[str] = None
) -> List[PatternSchema]:
    """List merged patterns (builtin ∪ user, user shadows builtin). Optional
    ?tag= (exact tag membership) and ?complexity= filters. Never 500s — a
    corrupt user file is skipped, not fatal."""
    rows = [_merged()[k] for k in sorted(_merged())]
    if tag:
        rows = [r for r in rows if tag in (r.get("tags") or [])]
    if complexity:
        rows = [r for r in rows if r.get("complexity") == complexity]
    out: List[PatternSchema] = []
    for r in rows:
        try:
            out.append(PatternSchema(**{k: v for k, v in r.items() if k != "provenance"}))
        except Exception:  # noqa: BLE001 — a malformed user file never sinks the list
            continue
    return out


@router.get("/{pattern_id}", response_model=PatternSchema)
async def get_pattern(pattern_id: str) -> PatternSchema:
    rec, _layer = _resolve(pattern_id)
    return PatternSchema(**{k: v for k, v in rec.items() if k != "provenance"})


@router.post(
    "",
    response_model=PatternSchema,
    status_code=201,
    dependencies=[Depends(require_master_key)],
)
async def create_pattern(body: PatternSchema) -> PatternSchema:
    """Create an operator pattern — always source='user', user layer. 409 when
    the id already exists in EITHER layer (edit/promote a shipped one instead)."""
    p = _pattern_path(body.id, must_exist=False)
    if p.is_file():
        raise HTTPException(
            status_code=409, detail=f"pattern '{body.id}' already exists"
        )
    if body.id in _catalog_map():
        raise HTTPException(
            status_code=409,
            detail=(
                f"pattern '{body.id}' already exists in the shipped (oob) layer "
                "— edit it (copy-on-write) or promote it instead"
            ),
        )
    data = _clean_schema(body, pattern_id=body.id, source="user")
    _write_atomic(p, data)
    logger.info("pattern created (user layer): %s", body.id)
    return PatternSchema(**data)


@router.patch(
    "/{pattern_id}",
    response_model=PatternSchema,
    dependencies=[Depends(require_master_key)],
)
async def update_pattern(pattern_id: str, patch: PatternPatch) -> PatternSchema:
    """Edit a pattern (full replace of the mutable fields). A builtin id is
    copied-on-write into the user layer (auto-promote) — the shipped catalog is
    never touched. 404 when the id is in neither layer."""
    current, layer = _resolve(pattern_id)  # 404 when in neither layer
    fields = patch.model_dump(exclude_none=True)
    merged = {**current, **fields, "id": pattern_id, "source": "user"}
    schema = PatternSchema(**{k: v for k, v in merged.items() if k != "provenance"})
    data = _clean_schema(schema, pattern_id=pattern_id, source="user")
    dst = _pattern_path(pattern_id, must_exist=False)
    _write_atomic(dst, data)
    if layer == "oob":
        logger.info("pattern '%s' copy-on-write promoted to user layer", pattern_id)
    return PatternSchema(**data)


@router.delete("/{pattern_id}", dependencies=[Depends(require_master_key)])
async def delete_pattern(pattern_id: str):
    """Delete the USER copy (reverting to the builtin when shipped). Pure-builtin
    ids are protected — a container rebuild would silently restore them anyway."""
    user_p = _pattern_path(pattern_id, must_exist=False)
    if user_p.is_file():
        user_p.unlink()
        reverted = pattern_id in _catalog_map()
        logger.info(
            "pattern user copy deleted: %s%s",
            pattern_id,
            " (reverted to oob)" if reverted else "",
        )
        return {"deleted": pattern_id, "reverted_to_oob": reverted}
    if pattern_id in _catalog_map():
        raise HTTPException(
            status_code=403,
            detail=(
                f"pattern '{pattern_id}' is a shipped (oob) preset and cannot be "
                "deleted — editing it creates a user-layer copy you can delete "
                "to revert"
            ),
        )
    raise HTTPException(status_code=404, detail=f"pattern '{pattern_id}' not found")


@router.post(
    "/{pattern_id}/promote",
    response_model=PatternSchema,
    status_code=201,
    dependencies=[Depends(require_master_key)],
)
async def promote_pattern(pattern_id: str) -> PatternSchema:
    """Copy the shipped (oob) preset into the user layer — physical promote.
    404 when there is no builtin; 409 when a user copy already exists."""
    builtin = _catalog_map().get(pattern_id)
    if builtin is None:
        raise HTTPException(
            status_code=404, detail=f"no shipped (oob) pattern '{pattern_id}' to promote"
        )
    user_p = _pattern_path(pattern_id, must_exist=False)
    if user_p.is_file():
        raise HTTPException(
            status_code=409, detail=f"pattern '{pattern_id}' already has a user-layer copy"
        )
    schema = PatternSchema(**{k: v for k, v in builtin.items() if k != "provenance"})
    data = _clean_schema(schema, pattern_id=pattern_id, source="user")
    _write_atomic(user_p, data)
    logger.info("pattern promoted to user layer: %s", pattern_id)
    return PatternSchema(**data)
