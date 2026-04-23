"""Read-only router exposing the role library at prompts/roles/.

Each role is a Markdown file whose filename (minus extension) is the ID
and whose first non-empty line is the summary. Path traversal is rejected
both by character allowlist and resolved-path containment.
"""
from __future__ import annotations

from pathlib import Path
from typing import List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/roles", tags=["roles"])

ROLES_DIR = (Path(__file__).resolve().parents[2] / "prompts" / "roles").resolve()


class RoleSummary(BaseModel):
    id: str
    name: str
    summary: str
    path: str


class Role(RoleSummary):
    content: str


def _id_to_path(role_id: str) -> Path:
    if not role_id or not all(c.isalnum() or c in "_-" for c in role_id):
        raise HTTPException(status_code=400, detail="invalid role id")
    candidate = (ROLES_DIR / f"{role_id}.md").resolve()
    try:
        candidate.relative_to(ROLES_DIR)
    except ValueError:
        raise HTTPException(status_code=400, detail="path outside role library")
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail=f"role '{role_id}' not found")
    return candidate


def _summarize(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:140]
    return ""


@router.get("", response_model=List[RoleSummary])
async def list_roles() -> List[RoleSummary]:
    if not ROLES_DIR.exists():
        return []
    out: List[RoleSummary] = []
    for p in sorted(ROLES_DIR.glob("*.md")):
        text = p.read_text(encoding="utf-8")
        out.append(
            RoleSummary(
                id=p.stem,
                name=p.stem.replace("_", " ").title(),
                summary=_summarize(text),
                path=str(p.relative_to(ROLES_DIR.parent.parent)),
            )
        )
    return out


@router.get("/{role_id}", response_model=Role)
async def get_role(role_id: str) -> Role:
    path = _id_to_path(role_id)
    text = path.read_text(encoding="utf-8")
    return Role(
        id=path.stem,
        name=path.stem.replace("_", " ").title(),
        summary=_summarize(text),
        path=str(path.relative_to(ROLES_DIR.parent.parent)),
        content=text,
    )
