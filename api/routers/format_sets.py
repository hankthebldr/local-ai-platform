"""Format sets — a small library of output-format instruction presets.

O5 of the Operate plane. A *format set* is a named bundle of output-shaping
instructions (produce a self-contained HTML page / Obsidian-style markdown / a
tabular index …) that the Composer bakes into a step's ``prompt.constraints[]``
as a fenced sentinel block at serialize time (see §4.2). The engine stays frozen:
raw extra YAML keys are dropped by Pydantic, so the modeled ``constraints`` list
is the only durable seam — this router owns the *authoring* of what goes in it.

Storage is ``prompts/formats/<id>.md`` with the **exact prompts.py discipline**
(``_ID_RE`` charset allowlist + resolved-path containment per layer, atomic
tmp+replace writes) and the same LAYERED oob/user split so a container's
read-only image ships the three built-ins while operator edits land user-side:

  oob   repo ``prompts/formats/``                      read-only shipped layer
  user  ``user_storage_root/prompts/formats/``         writable operator layer

Body = markdown instructions + minimal front-matter
``{name, summary, target: html|markdown|sheet, version}``.

Reads are scope-``workflows`` (the SCOPE_MAP entry ships with this unit — F9).
ALL writes are ``require_master_key`` from day one. Three seeded built-ins
(``html-standard``, ``markdown-graph-assets``, ``sheet-index``) are re-creatable
files, never database rows.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..logging_config import logger
from ..middleware import require_master_key

router = APIRouter(prefix="/api/format-sets", tags=["format-sets"])

_REPO_ROOT = Path(__file__).resolve().parents[2]
_OOB_ROOT = _REPO_ROOT / "prompts" / "formats"
_USER_FALLBACK = _REPO_ROOT / "data" / "prompts" / "formats"

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")
_TARGETS = ("html", "markdown", "sheet")
# Sentinel grammar shared with the Composer (§4.2): the block the format set
# serializes into prompt.constraints[]. Kept here as the single source of truth.
_SENTINEL_OPEN = "[format:{id}@{version}]"
_SENTINEL_CLOSE = "[/format]"
# Workflow-YAML scan for GET /{id}/refs — a workflow references a set when any
# constraint line carries its opener token.
_WORKFLOWS_DIR = _REPO_ROOT / "workflows"


def _user_root() -> Path:
    """user_storage_root/prompts/formats — deployment-resolved, test-patchable."""
    try:
        from ..services.deployment import _get_current

        return _get_current().user_storage_root / "prompts" / "formats"
    except Exception:  # noqa: BLE001 — no deployment detected (unit tests)
        return _USER_FALLBACK


def _base(layer: str) -> Path:
    return (_user_root() if layer == "user" else _OOB_ROOT).resolve()


class FormatSetSummary(BaseModel):
    id: str
    name: str
    summary: str = ""
    target: str = "markdown"
    version: int = 1
    provenance: str = "oob"  # 'oob' | 'user'


class FormatSet(FormatSetSummary):
    body: str
    meta: Dict[str, Any] = Field(default_factory=dict)


class FormatSetWrite(BaseModel):
    id: str
    body: str


class FormatSetPatch(BaseModel):
    body: str


# ── path + parse helpers (prompts.py discipline) ─────────────────────────────


def _path(fid: str, layer: str, must_exist: bool = True) -> Path:
    if not _ID_RE.match(fid or ""):
        raise HTTPException(
            status_code=400, detail="invalid format-set id (alnum/_/-, <=80)"
        )
    base = _base(layer)
    candidate = (base / f"{fid}.md").resolve()
    try:
        candidate.relative_to(base)
    except ValueError:
        raise HTTPException(status_code=400, detail="path escapes format library")
    if must_exist and not candidate.is_file():
        raise HTTPException(status_code=404, detail=f"format set '{fid}' not found")
    return candidate


def _resolve(fid: str) -> Tuple[Path, str]:
    """(path, layer) for the winning copy — user shadows oob. 404 if neither."""
    for layer in ("user", "oob"):
        p = _path(fid, layer, must_exist=False)
        if p.is_file():
            return p, layer
    raise HTTPException(status_code=404, detail=f"format set '{fid}' not found")


def _write_atomic(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(p)  # atomic


def _split_frontmatter(text: str) -> Tuple[Dict[str, Any], str]:
    """(front-matter dict, markdown rest). Empty dict when absent/non-mapping."""
    if not text.startswith("---"):
        return {}, text
    parts = text.split("\n---", 2)
    if len(parts) < 2:
        return {}, text
    try:
        meta = yaml.safe_load(parts[0][3:])
    except yaml.YAMLError:
        return {}, text
    if not isinstance(meta, dict):
        return {}, text
    rest = parts[1]
    if len(parts) == 3:
        rest = parts[1] + "\n---" + parts[2]
    return meta, rest.lstrip("\n")


def _validate_document(text: str) -> Dict[str, Any]:
    """Save-time validation: front-matter present with a valid ``target`` and a
    positive integer ``version``. Returns the parsed meta."""
    meta, _rest = _split_frontmatter(text)
    if not meta:
        raise HTTPException(
            status_code=400,
            detail="format set body must start with YAML front-matter "
            "(--- name/summary/target/version ---)",
        )
    target = meta.get("target")
    if target not in _TARGETS:
        raise HTTPException(
            status_code=400,
            detail=f"format set target {target!r} must be one of {list(_TARGETS)}",
        )
    version = meta.get("version", 1)
    if not isinstance(version, int) or version < 1:
        raise HTTPException(
            status_code=400, detail="format set version must be a positive integer"
        )
    return meta


def _instruction_lines(text: str) -> List[str]:
    """Non-empty markdown body lines — the constraint payload between the
    sentinel open/close. Front-matter is stripped first."""
    _meta, rest = _split_frontmatter(text)
    return [ln.rstrip() for ln in rest.splitlines() if ln.strip()]


def _serialize_constraints(fid: str, meta: Dict[str, Any], text: str) -> List[str]:
    """The EXACT constraint lines the Composer bakes into prompt.constraints[].
    Pure function — the preview endpoint and the client serializer agree byte
    for byte via this one implementation."""
    version = meta.get("version", 1)
    lines = [_SENTINEL_OPEN.format(id=fid, version=version)]
    lines.extend(_instruction_lines(text))
    lines.append(_SENTINEL_CLOSE)
    return lines


def _summary_of(p: Path, layer: str) -> FormatSetSummary:
    text = p.read_text(encoding="utf-8")
    meta, _rest = _split_frontmatter(text)
    return FormatSetSummary(
        id=p.stem,
        name=str(meta.get("name") or p.stem),
        summary=str(meta.get("summary") or ""),
        target=str(meta.get("target") or "markdown"),
        version=meta.get("version", 1) if isinstance(meta.get("version"), int) else 1,
        provenance=layer,
    )


# ── read endpoints ───────────────────────────────────────────────────────────


@router.get("", response_model=List[FormatSetSummary])
async def list_format_sets() -> List[FormatSetSummary]:
    """List format sets merged across layers — a user copy shadows the shipped
    one by id and flips the row's provenance to 'user'."""
    merged: Dict[str, FormatSetSummary] = {}
    for layer in ("oob", "user"):
        base = _base(layer)
        if not base.exists():
            continue
        for p in sorted(base.glob("*.md")):
            try:
                merged[p.stem] = _summary_of(p, layer)
            except OSError:
                continue
    return [merged[k] for k in sorted(merged)]


@router.get("/{fid}", response_model=FormatSet)
async def get_format_set(fid: str) -> FormatSet:
    p, layer = _resolve(fid)
    text = p.read_text(encoding="utf-8")
    meta, _rest = _split_frontmatter(text)
    rec = _summary_of(p, layer)
    return FormatSet(body=text, meta=meta, **rec.model_dump())


@router.post("/{fid}/preview")
async def preview_format_set(fid: str) -> Dict[str, Any]:
    """The exact serialized constraint lines this set injects — a pure preview
    of what the Composer bakes into ``prompt.constraints[]``. Read-open (no
    egress, no model call): serialization is deterministic string work."""
    p, _layer = _resolve(fid)
    text = p.read_text(encoding="utf-8")
    meta, _rest = _split_frontmatter(text)
    constraints = _serialize_constraints(fid, meta, text)
    return {
        "id": fid,
        "version": meta.get("version", 1),
        "target": meta.get("target"),
        "constraints": constraints,
        "text": "\n".join(constraints),
    }


@router.get("/{fid}/refs")
async def format_set_refs(fid: str) -> Dict[str, Any]:
    """Workflow-YAML sentinel scan: which workflow files reference this set via
    its ``[format:<id>@…]`` opener token. Surfaced in the delete Confirm so an
    operator sees what a deletion would strand. Read-only; scans repo workflows/."""
    if not _ID_RE.match(fid or ""):
        raise HTTPException(status_code=400, detail="invalid format-set id")
    token_at = f"[format:{fid}@"
    token_bare = f"[format:{fid}]"
    refs: List[str] = []
    if _WORKFLOWS_DIR.is_dir():
        for wf in sorted(_WORKFLOWS_DIR.glob("*.yaml")):
            try:
                content = wf.read_text(encoding="utf-8")
            except OSError:
                continue
            if token_at in content or token_bare in content:
                refs.append(wf.name)
    return {"id": fid, "refs": refs, "count": len(refs)}


# ── write endpoints (master-key gated) ───────────────────────────────────────


@router.post(
    "",
    response_model=FormatSet,
    status_code=201,
    dependencies=[Depends(require_master_key)],
)
async def create_format_set(body: FormatSetWrite) -> FormatSet:
    """Create a format set — writes ALWAYS land in the user layer."""
    _validate_document(body.body)
    user_p = _path(body.id, "user", must_exist=False)
    if user_p.is_file():
        raise HTTPException(
            status_code=409, detail=f"format set '{body.id}' already exists"
        )
    if _path(body.id, "oob", must_exist=False).is_file():
        raise HTTPException(
            status_code=409,
            detail=(
                f"format set '{body.id}' already exists in the shipped (oob) "
                "layer — edit it (copy-on-write) instead"
            ),
        )
    _write_atomic(user_p, body.body)
    logger.info("format set created (user layer): %s", body.id)
    return await get_format_set(body.id)


@router.put(
    "/{fid}",
    response_model=FormatSet,
    dependencies=[Depends(require_master_key)],
)
async def update_format_set(fid: str, patch: FormatSetPatch) -> FormatSet:
    """Edit a format set. An oob id is copied-on-write into the user layer
    (auto-promote) — the shipped file is never touched."""
    _validate_document(patch.body)
    _src, layer = _resolve(fid)  # 404 when in neither layer
    dst = _path(fid, "user", must_exist=False)
    _write_atomic(dst, patch.body)
    if layer == "oob":
        logger.info("format set %s copy-on-write promoted to user layer", fid)
    return await get_format_set(fid)


@router.delete("/{fid}", dependencies=[Depends(require_master_key)])
async def delete_format_set(fid: str) -> Dict[str, Any]:
    """Delete the USER copy (reverting to the shipped oob file when present).
    A pure-oob set is protected — a container rebuild would restore it anyway."""
    user_p = _path(fid, "user", must_exist=False)
    oob_p = _path(fid, "oob", must_exist=False)
    if user_p.is_file():
        user_p.unlink()
        reverted = oob_p.is_file()
        logger.info(
            "format set user copy deleted: %s%s",
            fid,
            " (reverted to oob)" if reverted else "",
        )
        return {"deleted": fid, "reverted_to_oob": reverted}
    if oob_p.is_file():
        raise HTTPException(
            status_code=403,
            detail=(
                f"format set '{fid}' is a shipped (oob) built-in and cannot be "
                "deleted — editing it creates a user-layer copy you can delete "
                "to revert"
            ),
        )
    raise HTTPException(status_code=404, detail=f"format set '{fid}' not found")
