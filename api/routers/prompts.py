"""Prompts library — a first-class object over prompts/{roles,templates}/.

The role library (prompts/roles/*.md) already shipped read-only via
api/routers/roles.py; this promotes Prompts to a full library kind with write
CRUD + a live render preview, mirroring the mcp.py CRUD surface. Two kinds:

  role     -> prompts/roles/<id>.md      (persona text; the StepPrompt.role_ref target)
  template -> prompts/templates/<id>.jinja (5-part Jinja skeleton)

Path traversal is rejected by id-charset allowlist AND resolved-path containment
(same discipline as roles.py — see the workspace glob-traversal incident). Render
reuses PromptComposer as a pure library, so the frozen workflow engine is untouched.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import List, Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..logging_config import logger

router = APIRouter(prefix="/api/prompts", tags=["prompts"])

_ROOT = Path(__file__).resolve().parents[2] / "prompts"
_DIRS = {
    "role": (_ROOT / "roles").resolve(),
    "template": (_ROOT / "templates").resolve(),
}
_EXT = {"role": ".md", "template": ".jinja"}
PromptKind = Literal["role", "template"]
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")
_VAR_RE = re.compile(r"{{\s*([a-zA-Z_][a-zA-Z0-9_]*)")


class PromptSummary(BaseModel):
    id: str
    kind: PromptKind
    name: str
    summary: str
    variables: List[str] = Field(default_factory=list)


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


def _path(kind: str, pid: str, must_exist: bool = True) -> Path:
    if kind not in _DIRS:
        raise HTTPException(status_code=400, detail=f"unknown prompt kind {kind!r}")
    if not _ID_RE.match(pid or ""):
        raise HTTPException(status_code=400, detail="invalid prompt id (alnum/_/-, <=80)")
    base = _DIRS[kind]
    candidate = (base / f"{pid}{_EXT[kind]}").resolve()
    try:
        candidate.relative_to(base)
    except ValueError:
        raise HTTPException(status_code=400, detail="path escapes prompt library")
    if must_exist and not candidate.is_file():
        raise HTTPException(status_code=404, detail=f"{kind} '{pid}' not found")
    return candidate


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


def _summary(kind: str, p: Path) -> PromptSummary:
    text = p.read_text(encoding="utf-8")
    return PromptSummary(
        id=p.stem, kind=kind, name=_name_from_id(p.stem),
        summary=_summarize(text), variables=_variables(text),
    )


@router.get("", response_model=List[PromptSummary])
async def list_prompts(kind: Optional[PromptKind] = None) -> List[PromptSummary]:
    """List roles ∪ templates (or one kind)."""
    out: List[PromptSummary] = []
    for k, base in _DIRS.items():
        if kind and k != kind:
            continue
        if not base.exists():
            continue
        for p in sorted(base.glob(f"*{_EXT[k]}")):
            try:
                out.append(_summary(k, p))
            except OSError:
                continue
    return out


@router.get("/{kind}/{pid}", response_model=Prompt)
async def get_prompt(kind: PromptKind, pid: str) -> Prompt:
    p = _path(kind, pid)
    text = p.read_text(encoding="utf-8")
    return Prompt(
        id=pid, kind=kind, name=_name_from_id(pid), summary=_summarize(text),
        variables=_variables(text), body=text,
    )


@router.post("", response_model=Prompt, status_code=201)
async def create_prompt(body: PromptWrite) -> Prompt:
    p = _path(body.kind, body.id, must_exist=False)
    if p.is_file():
        raise HTTPException(status_code=409, detail=f"{body.kind} '{body.id}' already exists")
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(body.body, encoding="utf-8")
    tmp.replace(p)  # atomic
    logger.info("prompt created: %s/%s", body.kind, body.id)
    return await get_prompt(body.kind, body.id)


@router.patch("/{kind}/{pid}", response_model=Prompt)
async def update_prompt(kind: PromptKind, pid: str, patch: PromptPatch) -> Prompt:
    p = _path(kind, pid)  # must exist
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(patch.body, encoding="utf-8")
    tmp.replace(p)
    return await get_prompt(kind, pid)


@router.delete("/{kind}/{pid}")
async def delete_prompt(kind: PromptKind, pid: str):
    p = _path(kind, pid)
    p.unlink()
    return {"deleted": f"{kind}/{pid}"}


@router.post("/{kind}/{pid}/render")
async def render_prompt(kind: PromptKind, pid: str, req: RenderRequest):
    """Live preview — reuse PromptComposer as a pure library (engine untouched)."""
    p = _path(kind, pid)
    body = p.read_text(encoding="utf-8")
    from ..services.prompt_composer import PromptComposer

    composer = PromptComposer(str(_DIRS["role"]), str(_DIRS["template"]))
    try:
        if kind == "role":
            composed = composer.compose(
                role_ref=None, role_inline=body, context=req.context, task=req.task,
                constraints=req.constraints, output_schema={},
                template_name=req.template_ref or "five_part.jinja",
            )
        else:  # template: render a sample persona through this template
            composed = composer.compose(
                role_ref=None, role_inline="You are a helpful assistant.",
                context=req.context, task=req.task, constraints=req.constraints,
                output_schema={}, template_name=f"{pid}.jinja",
            )
    except Exception as e:  # bad template / missing var -> 400, not 500
        raise HTTPException(status_code=400, detail=f"render failed: {e}")
    return {"system": composed.system, "user": composed.user, "params": composed.params}
