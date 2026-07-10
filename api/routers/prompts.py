"""Prompts library — a first-class object over two prompt layers.

The role library (prompts/roles/*.md) already shipped read-only via
api/routers/roles.py; this promotes Prompts to a full library kind with write
CRUD + a live render preview, mirroring the mcp.py CRUD surface. Two kinds:

  role     -> roles/<id>.md      (persona text; the StepPrompt.role_ref target)
  template -> templates/<id>.jinja (5-part Jinja skeleton)

Storage is LAYERED (LB0-U3, the plugins precedent):

  oob  -> repo prompts/{roles,templates}/            read-only shipped layer
  user -> user_storage_root/prompts/{roles,templates}/  writable operator layer

Listing merges both layers with user shadowing oob by id; each record carries
``provenance: 'oob'|'user'`` derived from the winning layer. ALL writes land
user-side: creates write there directly, PATCH of an oob id performs
copy-on-write into the user layer (auto-promote — provenance flips honestly),
DELETE removes the user copy (reverting to oob when a shipped copy exists) and
returns 403 on a pure-oob id. POST /{kind}/{pid}/promote copies the oob file
into the user layer explicitly (409 when a user copy already exists).

Path traversal is rejected by id-charset allowlist AND resolved-path
containment per layer (same discipline as roles.py — see the workspace
glob-traversal incident). Writes are atomic (tmp+replace). Render reuses
PromptComposer as a pure library, so the frozen workflow engine is untouched.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import List, Literal, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..logging_config import logger
from ..middleware import require_master_key

router = APIRouter(prefix="/api/prompts", tags=["prompts"])

_REPO_ROOT = Path(__file__).resolve().parents[2]
# oob layer: the COPY'd repo tree — shipped with the image, never written to.
_OOB_ROOT = _REPO_ROOT / "prompts"
# user layer fallback when no deployment is detected (bare unit tests / dev):
# repo data/ == user_storage_root in containers (deployment.py:120-122).
_USER_FALLBACK = _REPO_ROOT / "data" / "prompts"

_SUBDIR = {"role": "roles", "template": "templates"}
_EXT = {"role": ".md", "template": ".jinja"}
PromptKind = Literal["role", "template"]
PromptLayer = Literal["oob", "user"]
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")
_VAR_RE = re.compile(r"{{\s*([a-zA-Z_][a-zA-Z0-9_]*)")


def _user_root() -> Path:
    """user_storage_root/prompts — deployment-resolved, test-patchable."""
    try:
        from ..services.deployment import _get_current

        return _get_current().user_storage_root / "prompts"
    except Exception:  # noqa: BLE001 — no deployment detected (unit tests)
        return _USER_FALLBACK


def _base(layer: str, kind: str) -> Path:
    root = _user_root() if layer == "user" else _OOB_ROOT
    return (root / _SUBDIR[kind]).resolve()


class PromptSummary(BaseModel):
    id: str
    kind: PromptKind
    name: str
    summary: str
    variables: List[str] = Field(default_factory=list)
    provenance: PromptLayer = "oob"


class Prompt(PromptSummary):
    body: str


class PromptWrite(BaseModel):
    id: str
    kind: PromptKind = "role"
    body: str


class PromptPatch(BaseModel):
    body: str


class RenderRequest(BaseModel):
    task: str = "Draft a concise plan."
    context: str = ""
    constraints: List[str] = Field(default_factory=list)
    template_ref: Optional[str] = None


def _path(kind: str, pid: str, layer: str, must_exist: bool = True) -> Path:
    """Resolve one (kind, id) inside ONE layer with full containment checks."""
    if kind not in _SUBDIR:
        raise HTTPException(status_code=400, detail=f"unknown prompt kind {kind!r}")
    if not _ID_RE.match(pid or ""):
        raise HTTPException(status_code=400, detail="invalid prompt id (alnum/_/-, <=80)")
    base = _base(layer, kind)
    candidate = (base / f"{pid}{_EXT[kind]}").resolve()
    try:
        candidate.relative_to(base)
    except ValueError:
        raise HTTPException(status_code=400, detail="path escapes prompt library")
    if must_exist and not candidate.is_file():
        raise HTTPException(status_code=404, detail=f"{kind} '{pid}' not found")
    return candidate


def _resolve(kind: str, pid: str) -> Tuple[Path, str]:
    """(path, layer) for the WINNING copy — user shadows oob. 404 if neither."""
    for layer in ("user", "oob"):
        p = _path(kind, pid, layer, must_exist=False)
        if p.is_file():
            return p, layer
    raise HTTPException(status_code=404, detail=f"{kind} '{pid}' not found")


def _write_atomic(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(p)  # atomic


def _name_from_id(pid: str) -> str:
    return pid.replace("_", " ").replace("-", " ").title()


def _summarize(text: str) -> str:
    for line in text.splitlines():
        s = line.strip().lstrip("#").strip()
        if s:
            return s[:140]
    return ""


def _variables(text: str) -> List[str]:
    return sorted(set(_VAR_RE.findall(text)))


def _summary(kind: str, p: Path, layer: str) -> PromptSummary:
    text = p.read_text(encoding="utf-8")
    return PromptSummary(
        id=p.stem, kind=kind, name=_name_from_id(p.stem),
        summary=_summarize(text), variables=_variables(text), provenance=layer,
    )


@router.get("", response_model=List[PromptSummary])
async def list_prompts(kind: Optional[PromptKind] = None) -> List[PromptSummary]:
    """List roles ∪ templates (or one kind), merged across layers.

    oob scans first, then user — later wins, so a user copy shadows the
    shipped one by id and the row's provenance flips to 'user'."""
    out: List[PromptSummary] = []
    for k in _SUBDIR:
        if kind and k != kind:
            continue
        merged: dict[str, PromptSummary] = {}
        for layer in ("oob", "user"):
            base = _base(layer, k)
            if not base.exists():
                continue
            for p in sorted(base.glob(f"*{_EXT[k]}")):
                try:
                    merged[p.stem] = _summary(k, p, layer)
                except OSError:
                    continue
        out.extend(merged[pid] for pid in sorted(merged))
    return out


@router.get("/{kind}/{pid}", response_model=Prompt)
async def get_prompt(kind: PromptKind, pid: str) -> Prompt:
    p, layer = _resolve(kind, pid)
    text = p.read_text(encoding="utf-8")
    return Prompt(
        id=pid, kind=kind, name=_name_from_id(pid), summary=_summarize(text),
        variables=_variables(text), body=text, provenance=layer,
    )


@router.post("", response_model=Prompt, status_code=201)
async def create_prompt(body: PromptWrite) -> Prompt:
    """Create a prompt — writes ALWAYS land in the user layer."""
    user_p = _path(body.kind, body.id, "user", must_exist=False)
    if user_p.is_file():
        raise HTTPException(status_code=409, detail=f"{body.kind} '{body.id}' already exists")
    if _path(body.kind, body.id, "oob", must_exist=False).is_file():
        raise HTTPException(
            status_code=409,
            detail=(f"{body.kind} '{body.id}' already exists in the shipped (oob) "
                    "layer — edit it (copy-on-write) or promote it instead"),
        )
    _write_atomic(user_p, body.body)
    logger.info("prompt created (user layer): %s/%s", body.kind, body.id)
    return await get_prompt(body.kind, body.id)


@router.patch("/{kind}/{pid}", response_model=Prompt)
async def update_prompt(kind: PromptKind, pid: str, patch: PromptPatch) -> Prompt:
    """Edit a prompt. An oob id is copied-on-write into the user layer
    (auto-promote) — the shipped file is never touched."""
    _src, layer = _resolve(kind, pid)  # 404 when in neither layer
    dst = _path(kind, pid, "user", must_exist=False)
    _write_atomic(dst, patch.body)
    if layer == "oob":
        logger.info("prompt %s/%s copy-on-write promoted to user layer", kind, pid)
    return await get_prompt(kind, pid)


@router.delete("/{kind}/{pid}")
async def delete_prompt(kind: PromptKind, pid: str):
    """Delete the USER copy (reverting to oob when shipped). Pure-oob ids are
    protected — a container rebuild would silently restore them anyway."""
    user_p = _path(kind, pid, "user", must_exist=False)
    oob_p = _path(kind, pid, "oob", must_exist=False)
    if user_p.is_file():
        user_p.unlink()
        reverted = oob_p.is_file()
        logger.info("prompt user copy deleted: %s/%s%s", kind, pid,
                    " (reverted to oob)" if reverted else "")
        return {"deleted": f"{kind}/{pid}", "reverted_to_oob": reverted}
    if oob_p.is_file():
        raise HTTPException(
            status_code=403,
            detail=(f"{kind} '{pid}' is a shipped (oob) prompt and cannot be "
                    "deleted — editing it creates a user-layer copy you can "
                    "delete to revert"),
        )
    raise HTTPException(status_code=404, detail=f"{kind} '{pid}' not found")


@router.post(
    "/{kind}/{pid}/promote",
    response_model=Prompt,
    status_code=201,
    dependencies=[Depends(require_master_key)],
)
async def promote_prompt(kind: PromptKind, pid: str) -> Prompt:
    """Copy the shipped (oob) file into the user layer — physical promote.
    409 when a user copy already exists; atomic tmp+replace; master-key."""
    oob_p = _path(kind, pid, "oob", must_exist=False)
    if not oob_p.is_file():
        raise HTTPException(status_code=404, detail=f"no shipped (oob) {kind} '{pid}' to promote")
    user_p = _path(kind, pid, "user", must_exist=False)
    if user_p.is_file():
        raise HTTPException(status_code=409, detail=f"{kind} '{pid}' already has a user-layer copy")
    _write_atomic(user_p, oob_p.read_text(encoding="utf-8"))
    logger.info("prompt promoted to user layer: %s/%s", kind, pid)
    return await get_prompt(kind, pid)


def _template_search_dir(name: str) -> Path:
    """Layer-resolve a template FILENAME (user shadows oob) for the composer.

    Containment is enforced against each layer base so a template_ref like
    '../x.jinja' can never escape; unknown names fall through to the oob dir
    and surface as the composer's own not-found -> 400."""
    for layer in ("user", "oob"):
        base = _base(layer, "template")
        candidate = (base / name).resolve()
        try:
            candidate.relative_to(base)
        except ValueError:
            raise HTTPException(status_code=400, detail="template_ref escapes prompt library")
        if candidate.is_file():
            return base
    return _base("oob", "template")


@router.post("/{kind}/{pid}/render")
async def render_prompt(kind: PromptKind, pid: str, req: RenderRequest):
    """Live preview — reuse PromptComposer as a pure library (engine untouched)."""
    p, _layer = _resolve(kind, pid)
    body = p.read_text(encoding="utf-8")
    from ..services.prompt_composer import PromptComposer

    if kind == "role":
        template_name = req.template_ref or "five_part.jinja"
        templates_dir = _template_search_dir(template_name)
    else:  # template: render a sample persona through this exact (layered) file
        template_name = f"{pid}.jinja"
        templates_dir = p.parent
    composer = PromptComposer(str(_base("oob", "role")), str(templates_dir))
    try:
        if kind == "role":
            composed = composer.compose(
                role_ref=None, role_inline=body, context=req.context, task=req.task,
                constraints=req.constraints, output_schema={},
                template_name=template_name,
            )
        else:
            composed = composer.compose(
                role_ref=None, role_inline="You are a helpful assistant.",
                context=req.context, task=req.task, constraints=req.constraints,
                output_schema={}, template_name=template_name,
            )
    except Exception as e:  # bad template / missing var -> 400, not 500
        raise HTTPException(status_code=400, detail=f"render failed: {e}")
    return {"system": composed.system, "user": composed.user, "params": composed.params}
