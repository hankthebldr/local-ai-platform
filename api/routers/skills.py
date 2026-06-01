#!/usr/bin/env python3
"""
Skills Router — Discovery + install for skill-pack content.

The Skills Lab needs a "Discover" surface analogous to the Models tab's
HuggingFace pull. Skills here come from a curated catalog shipped in
data/discovery/skills_catalog.json rather than a remote registry — that
keeps the system local-first while still letting an operator browse +
install pre-authored skill bodies into a chosen plugin.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..logging_config import logger
from ..middleware import require_master_key

router = APIRouter(prefix="/api/skills", tags=["skills"])

# Catalog ships under data/discovery so it can be versioned + swapped
# for a remote-pulled copy in future without changing the API.
_CATALOG_PATH = (
    Path(__file__).parent.parent.parent / "data" / "discovery" / "skills_catalog.json"
)
_PLUGINS_DIR = Path(__file__).parent.parent.parent / "plugins"

# Identifier safety — same convention used by workflow_index. Prevents
# path-escape via plugin_id/skill_id input.
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _load_catalog() -> Dict[str, Any]:
    if not _CATALOG_PATH.exists():
        return {"schema": "enclave.skills-catalog/v1", "skills": [], "updated": None}
    try:
        return json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to parse skills catalog %s: %s", _CATALOG_PATH, exc)
        return {"schema": "enclave.skills-catalog/v1", "skills": [], "updated": None}


def _installed_index() -> Dict[str, List[str]]:
    """Map skill_id → [plugin_ids] for every skill registered on disk."""
    out: Dict[str, List[str]] = {}
    if not _PLUGINS_DIR.exists():
        return out
    for manifest in sorted(_PLUGINS_DIR.glob("*/plugin.yaml")):
        try:
            data = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
        except Exception as exc:  # noqa: BLE001
            logger.warning("Skipping bad plugin manifest %s: %s", manifest, exc)
            continue
        plugin_id = data.get("id") or manifest.parent.name
        for skill in data.get("skills") or []:
            sid = (skill or {}).get("id")
            if not sid:
                continue
            out.setdefault(sid, []).append(plugin_id)
    return out


def _installed_skills_detail() -> Dict[str, Dict[str, Any]]:
    """skill_id → minimal record, read from plugin manifests, for every skill
    installed on disk. Lets discover() surface bundled/installed skills that
    aren't in the curated catalog so the view reflects what's actually here."""
    out: Dict[str, Dict[str, Any]] = {}
    if not _PLUGINS_DIR.exists():
        return out
    for manifest in sorted(_PLUGINS_DIR.glob("*/plugin.yaml")):
        try:
            data = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
        except Exception:  # noqa: BLE001
            continue
        plugin_id = data.get("id") or manifest.parent.name
        for skill in data.get("skills") or []:
            sid = (skill or {}).get("id")
            if not sid or sid in out:
                continue
            out[sid] = {
                "id": sid,
                "name": skill.get("name") or sid,
                "description": skill.get("description") or "",
                "category": skill.get("category") or "installed",
                "triggers": skill.get("triggers")
                or skill.get("trigger_keywords")
                or [],
                "persona": skill.get("persona"),
                "source_plugin": plugin_id,
            }
    return out


def _annotate(skills: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Mark each catalog entry with where it's currently installed."""
    installed = _installed_index()
    result = []
    for skill in skills:
        sid = skill.get("id")
        already = installed.get(sid, [])
        out = dict(skill)
        out["installed_in"] = list(set(already + (skill.get("installed_in") or [])))
        out["installed"] = bool(out["installed_in"])
        # Strip the full skill_md from the list payload — it can be
        # large and is only needed on install. Indicator only.
        out["has_body"] = "skill_md" in skill and bool(skill.get("skill_md"))
        out.pop("skill_md", None)
        result.append(out)
    return result


@router.get("/discover", dependencies=[Depends(require_master_key)])
async def discover() -> Dict[str, Any]:
    """List every skill in the curated discovery catalog with install state."""
    cat = _load_catalog()
    catalog_skills = _annotate(cat.get("skills") or [])
    catalog_ids = {s.get("id") for s in catalog_skills}
    # Fold in installed plugin skills that aren't in the curated catalog so the
    # discovery view reflects everything actually on the box (not just the
    # curated set). Marked installed + bundled.
    installed_idx = _installed_index()
    extras: List[Dict[str, Any]] = []
    for sid, detail in _installed_skills_detail().items():
        if sid in catalog_ids:
            continue
        entry = dict(detail)
        entry["installed_in"] = installed_idx.get(sid, [])
        entry["installed"] = bool(entry["installed_in"])
        entry["has_body"] = False  # bundled — body lives in the plugin
        entry["bundled"] = True
        extras.append(entry)
    skills = catalog_skills + extras
    return {
        "schema": cat.get("schema"),
        "version": cat.get("version"),
        "updated": cat.get("updated"),
        "count": len(skills),
        "skills": skills,
    }


@router.get("/discover/{skill_id}", dependencies=[Depends(require_master_key)])
async def discover_one(skill_id: str) -> Dict[str, Any]:
    """Return the full record (including skill_md body) for a single skill."""
    cat = _load_catalog()
    for skill in cat.get("skills") or []:
        if skill.get("id") == skill_id:
            annotated = _annotate([skill])[0]
            annotated["skill_md"] = skill.get("skill_md")
            return annotated
    raise HTTPException(status_code=404, detail="skill not in catalog")


class InstallReq(BaseModel):
    plugin_id: str
    triggers: Optional[List[str]] = None  # optional trigger override


@router.post("/discover/{skill_id}/install", dependencies=[Depends(require_master_key)])
async def install(skill_id: str, req: InstallReq) -> Dict[str, Any]:
    """Install a catalog skill into a target plugin.

    Writes the skill's markdown body to ``plugins/<plugin>/skills/<id>.md``
    and registers it in the plugin's manifest. Refuses to overwrite an
    existing registration silently — surface a 409 instead.
    """
    if not _ID_RE.match(skill_id):
        raise HTTPException(status_code=400, detail="invalid skill id")
    if not _ID_RE.match(req.plugin_id):
        raise HTTPException(status_code=400, detail="invalid plugin id")

    cat = _load_catalog()
    skill = next(
        (s for s in (cat.get("skills") or []) if s.get("id") == skill_id), None
    )
    if not skill:
        raise HTTPException(status_code=404, detail="skill not in catalog")
    body = skill.get("skill_md")
    if not body or not isinstance(body, str):
        raise HTTPException(
            status_code=400,
            detail=(
                "this catalog entry has no skill_md body to install — "
                "it's already bundled with the install (see installed_in)"
            ),
        )

    plugin_dir = _PLUGINS_DIR / req.plugin_id
    manifest_path = plugin_dir / "plugin.yaml"
    if not manifest_path.exists():
        raise HTTPException(
            status_code=404, detail=f"plugin '{req.plugin_id}' not found"
        )

    try:
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500, detail=f"failed to read plugin manifest: {exc}"
        )

    skills_block = manifest.setdefault("skills", [])
    for existing in skills_block:
        if (existing or {}).get("id") == skill_id:
            raise HTTPException(
                status_code=409,
                detail=f"skill '{skill_id}' is already registered in plugin '{req.plugin_id}'",
            )

    # Write the markdown body.
    skills_dir = plugin_dir / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    md_path = skills_dir / f"{skill_id}.md"
    if md_path.exists():
        # Path collision with an unregistered file — refuse rather than
        # clobber operator content.
        raise HTTPException(
            status_code=409,
            detail=f"file {md_path.name} already exists in plugin '{req.plugin_id}/skills' "
            "but isn't registered in the manifest — investigate before installing.",
        )
    md_path.write_text(body, encoding="utf-8")

    # Register in manifest.
    triggers_in = req.triggers or skill.get("triggers") or []
    trigger_blocks: List[Dict[str, Any]] = []
    for t in triggers_in:
        if isinstance(t, str) and t.strip():
            trigger_blocks.append({"keyword": t.strip()})
    trigger_blocks.append({"manual": True})

    skills_block.append(
        {
            "id": skill_id,
            "file": f"skills/{skill_id}.md",
            "triggers": trigger_blocks,
        }
    )
    manifest_path.write_text(
        yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    logger.info("Installed skill '%s' into plugin '%s'", skill_id, req.plugin_id)
    return {
        "installed": True,
        "skill_id": skill_id,
        "plugin_id": req.plugin_id,
        "file": f"plugins/{req.plugin_id}/skills/{skill_id}.md",
    }


class CreateReq(BaseModel):
    """Author a brand-new skill from scratch (not from the catalog)."""

    id: str
    plugin_id: str
    name: Optional[str] = None
    description: Optional[str] = None
    triggers: Optional[List[str]] = None
    body: str  # markdown body — front-matter optional, written verbatim


@router.post("/create", dependencies=[Depends(require_master_key)])
async def create(req: CreateReq) -> Dict[str, Any]:
    """Author a brand-new skill from an operator-supplied body.

    Mirrors ``install`` but the body comes from the request payload
    instead of the curated catalog. Used by the Catalog page's
    Skill Builder modal.

    Writes:
      - plugins/<plugin>/skills/<id>.md  with optional front-matter
        synthesized from name + description when the body doesn't
        already include a frontmatter block.
      - plugin.yaml gains a skills[] entry with the trigger list +
        ``manual: true`` so the skill can also be attached manually.
    """
    if not _ID_RE.match(req.id):
        raise HTTPException(status_code=400, detail="invalid skill id")
    if not _ID_RE.match(req.plugin_id):
        raise HTTPException(status_code=400, detail="invalid plugin id")
    if not req.body or not req.body.strip():
        raise HTTPException(status_code=400, detail="skill body is required")

    plugin_dir = _PLUGINS_DIR / req.plugin_id
    manifest_path = plugin_dir / "plugin.yaml"
    if not manifest_path.exists():
        raise HTTPException(
            status_code=404, detail=f"plugin '{req.plugin_id}' not found"
        )

    try:
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500, detail=f"failed to read plugin manifest: {exc}"
        )

    skills_block = manifest.setdefault("skills", [])
    for existing in skills_block:
        if (existing or {}).get("id") == req.id:
            raise HTTPException(
                status_code=409,
                detail=f"skill '{req.id}' is already registered in plugin '{req.plugin_id}'",
            )

    # Write the markdown body. Auto-prepend a front-matter block when
    # the operator didn't include one, so the file shape stays
    # consistent with the rest of the catalog.
    skills_dir = plugin_dir / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    md_path = skills_dir / f"{req.id}.md"
    if md_path.exists():
        raise HTTPException(
            status_code=409,
            detail=(
                f"file {md_path.name} already exists in plugin "
                f"'{req.plugin_id}/skills' — investigate before creating."
            ),
        )
    body = req.body
    if not body.lstrip().startswith("---"):
        fm_lines = [
            "---",
            f'name: "{(req.name or req.id).replace(chr(34), chr(39))}"',
        ]
        if req.description:
            desc_escaped = req.description.replace('"', "'")
            fm_lines.append(f'description: "{desc_escaped}"')
        fm_lines += ['inject: "system"', "---", ""]
        body = "\n".join(fm_lines) + body.lstrip()
    md_path.write_text(body, encoding="utf-8")

    # Register in manifest with the supplied triggers (+ manual fallback).
    trigger_blocks: List[Dict[str, Any]] = []
    for t in req.triggers or []:
        if isinstance(t, str) and t.strip():
            trigger_blocks.append({"keyword": t.strip()})
    trigger_blocks.append({"manual": True})

    skills_block.append(
        {
            "id": req.id,
            "file": f"skills/{req.id}.md",
            "triggers": trigger_blocks,
        }
    )
    manifest_path.write_text(
        yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    logger.info("Authored new skill '%s' into plugin '%s'", req.id, req.plugin_id)
    return {
        "created": True,
        "skill_id": req.id,
        "plugin_id": req.plugin_id,
        "file": f"plugins/{req.plugin_id}/skills/{req.id}.md",
    }


@router.delete(
    "/discover/{skill_id}/uninstall", dependencies=[Depends(require_master_key)]
)
async def uninstall(skill_id: str, plugin_id: str) -> Dict[str, Any]:
    """Inverse of install — remove the registration + the markdown file."""
    if not _ID_RE.match(skill_id) or not _ID_RE.match(plugin_id):
        raise HTTPException(status_code=400, detail="invalid id")
    plugin_dir = _PLUGINS_DIR / plugin_id
    manifest_path = plugin_dir / "plugin.yaml"
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="plugin not found")

    try:
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"manifest read failed: {exc}")

    before = manifest.get("skills") or []
    after = [s for s in before if (s or {}).get("id") != skill_id]
    if len(after) == len(before):
        raise HTTPException(
            status_code=404, detail="skill not registered in this plugin"
        )
    manifest["skills"] = after
    manifest_path.write_text(
        yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )

    md_path = plugin_dir / "skills" / f"{skill_id}.md"
    if md_path.exists():
        md_path.unlink()

    logger.info("Uninstalled skill '%s' from plugin '%s'", skill_id, plugin_id)
    return {"uninstalled": True, "skill_id": skill_id, "plugin_id": plugin_id}
