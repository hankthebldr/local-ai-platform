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
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
import yaml
from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel

from ..logging_config import logger
from ..middleware import require_master_key

router = APIRouter(prefix="/api/skills", tags=["skills"])

# ── Remote marketplace catalog (generic, operator-configurable) ─────────────
# Set ENCLAVE_SKILLS_CATALOG_URL to a JSON index ({"skills":[...]} or a bare
# [...] list) and discovery merges it in alongside the local curated catalog +
# bundled installs. Works with ANY marketplace that publishes JSON — no
# per-site scraping. Cached so discovery doesn't hit the network every call;
# fails soft (local-only) on any error.
_REMOTE_TTL_SECONDS = 600
_remote_cache: Dict[str, Any] = {"ts": 0.0, "url": None, "skills": []}


def _fetch_remote_catalog() -> List[Dict[str, Any]]:
    """Fetch + cache the remote skills catalog. Never raises — returns the last
    good cache (or []) on any error so discovery degrades to local-only."""
    url = os.getenv("ENCLAVE_SKILLS_CATALOG_URL", "").strip()
    if not url:
        return []
    now = time.monotonic()
    if (
        _remote_cache["url"] == url
        and (now - _remote_cache["ts"]) < _REMOTE_TTL_SECONDS
    ):
        return _remote_cache["skills"]
    skills: List[Dict[str, Any]] = []
    try:
        resp = requests.get(url, timeout=6)
        resp.raise_for_status()
        payload = resp.json()
        raw = payload.get("skills") if isinstance(payload, dict) else payload
        for s in raw or []:
            if isinstance(s, dict) and s.get("id"):
                rec = dict(s)
                rec["source"] = "remote"
                rec["marketplace"] = True
                skills.append(rec)
        logger.info("Remote skills catalog: %d skills from %s", len(skills), url)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Remote skills catalog fetch failed (%s); using local only: %s", url, exc
        )
        if _remote_cache["url"] == url and _remote_cache["skills"]:
            return _remote_cache["skills"]
        return []
    _remote_cache.update({"ts": now, "url": url, "skills": skills})
    return skills


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


# ── Trigger dry-run (LB1-U1) ────────────────────────────────────────────


class SkillTestRequest(BaseModel):
    """Dry-run skill matching for the Library Test pane.

    message-only → keyword matching over every installed skill (the chat
    path's plugin_service.get_skills). plugin_id + skill_id → explicit
    lookup, mirroring a step's ``skills:`` list. Nothing is injected
    anywhere — the response reports exactly WHAT WOULD BE injected.
    """

    message: str = ""
    plugin_id: Optional[str] = None
    skill_id: Optional[str] = None


def _dry_run_record(
    plugin_id: str, skill: Dict[str, Any], trigger: str, matched_keyword: Optional[str]
) -> Dict[str, Any]:
    """Shape one matched skill exactly as skill_injector would inject it:
    body stripped, site from frontmatter ``inject`` (system prepends
    ``body + "\\n\\n"``, messages appends ``"\\n\\n" + body``)."""
    body = (skill.get("content") or "").strip()
    inject_site = (skill.get("inject") or "system").lower()
    site = "system" if inject_site != "messages" else "messages"
    injected_text = (body + "\n\n") if site == "system" else ("\n\n" + body)
    keywords = [
        t.get("keyword")
        for t in (skill.get("triggers") or [])
        if isinstance(t, dict) and t.get("keyword")
    ]
    return {
        "plugin_id": plugin_id,
        "skill_id": skill.get("id"),
        "name": skill.get("name") or skill.get("id"),
        "trigger": trigger,
        "trigger_match": matched_keyword,
        "keywords": keywords,
        "injected_into": site,
        "injected_text": injected_text if body else "",
        "injected_chars": len(body),
        "would_inject": bool(body),
    }


@router.post("/test", dependencies=[Depends(require_master_key)])
async def test_skill_triggers(req: SkillTestRequest) -> Dict[str, Any]:
    """Dry-run over plugin_service.get_skills/get_skill: matched skills,
    matched keywords, and the exact text the injector would add."""
    from api.hooks.builtins.skill_injector import (
        _find_plugin_id_for_skill,
        _first_matching_keyword,
    )

    from .plugins import plugin_service

    matched: List[Dict[str, Any]] = []
    if req.plugin_id and req.skill_id:
        skill = plugin_service.get_skill(req.plugin_id, req.skill_id)
        if skill is None:
            raise HTTPException(
                status_code=404,
                detail=f"skill {req.plugin_id}.{req.skill_id} not found",
            )
        matched.append(
            _dry_run_record(
                req.plugin_id,
                skill,
                "explicit",
                _first_matching_keyword(skill, req.message),
            )
        )
    else:
        for skill in plugin_service.get_skills(req.message):
            pid = _find_plugin_id_for_skill(plugin_service, skill.get("id"))
            if pid is None:
                continue
            matched.append(
                _dry_run_record(
                    pid, skill, "keyword", _first_matching_keyword(skill, req.message)
                )
            )
    return {"message": req.message, "matched": matched, "count": len(matched)}


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

    # Merge the remote marketplace catalog (deduped by id — local catalog +
    # bundled win on conflict). Remote entries get install-state annotation too.
    seen = {s.get("id") for s in skills}
    remote_count = 0
    for r in _fetch_remote_catalog():
        rid = r.get("id")
        if not rid or rid in seen:
            continue
        rec = _annotate([r])[0]
        rec["source"] = "remote"
        rec["marketplace"] = True
        skills.append(rec)
        seen.add(rid)
        remote_count += 1

    return {
        "schema": cat.get("schema"),
        "version": cat.get("version"),
        "updated": cat.get("updated"),
        "count": len(skills),
        "remote_count": remote_count,
        "skills": skills,
    }


def _find_skill_full(skill_id: str) -> Optional[Dict[str, Any]]:
    """Full skill record (incl. skill_md body) from the local catalog first,
    then the remote marketplace catalog — so remote skills are installable too
    when the marketplace publishes bodies. None if in neither."""
    for s in _load_catalog().get("skills") or []:
        if s.get("id") == skill_id:
            return s
    for s in _fetch_remote_catalog():
        if s.get("id") == skill_id:
            return s
    return None


@router.get("/discover/{skill_id}", dependencies=[Depends(require_master_key)])
async def discover_one(skill_id: str) -> Dict[str, Any]:
    """Return the full record (including skill_md body) for a single skill."""
    skill = _find_skill_full(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="skill not in catalog")
    annotated = _annotate([skill])[0]
    annotated["skill_md"] = skill.get("skill_md")
    return annotated


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

    skill = _find_skill_full(skill_id)
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


def _slug(text: str) -> str:
    """Lowercase, hyphenated, id-safe slug from a skill name."""
    s = re.sub(r"[^A-Za-z0-9]+", "-", (text or "").strip().lower()).strip("-")
    return s[:64] or "imported-skill"


def _parse_skill_frontmatter(text: str) -> Dict[str, Any]:
    """Pull the YAML frontmatter (name/description/…) from a SKILL.md.
    Returns {} when there's no frontmatter block."""
    t = text.lstrip()
    if not t.startswith("---"):
        return {}
    end = t.find("\n---", 3)
    if end == -1:
        return {}
    try:
        meta = yaml.safe_load(t[3:end]) or {}
        return meta if isinstance(meta, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


@router.get("/github", dependencies=[Depends(require_master_key)])
async def discover_github(repo: str, ref: str = "main") -> Dict[str, Any]:
    """Bulk-browse a GitHub repo's skills — every SKILL.md, parsed. skills.sh
    indexes repos at skills.sh/<owner>/<repo>, so paste the owner/repo to see
    everything installable in it. Uses the unauthenticated GitHub trees API."""
    repo = (repo or "").strip()
    if not _REPO_RE.match(repo):
        raise HTTPException(status_code=400, detail="repo must be 'owner/repo'")
    try:
        tr = requests.get(
            f"https://api.github.com/repos/{repo}/git/trees/{ref}?recursive=1",
            timeout=12,
            headers={"Accept": "application/vnd.github+json"},
        )
        if tr.status_code == 404 and ref == "main":
            tr = requests.get(
                f"https://api.github.com/repos/{repo}/git/trees/master?recursive=1",
                timeout=12,
            )
            ref = "master"
        tr.raise_for_status()
        tree = tr.json().get("tree", [])
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"GitHub fetch failed: {exc}")

    paths = [
        t["path"]
        for t in tree
        if isinstance(t, dict) and t.get("path", "").lower().endswith("skill.md")
    ][
        :30
    ]  # cap — each needs a content fetch
    skills = []
    for path in paths:
        raw = f"https://raw.githubusercontent.com/{repo}/{ref}/{path}"
        meta = {}
        try:
            text = requests.get(raw, timeout=6).text
            meta = _parse_skill_frontmatter(text)
        except Exception:  # noqa: BLE001
            pass
        # name fallback: the skill's parent directory.
        parts = path.split("/")
        dirname = parts[-2] if len(parts) > 1 else parts[0]
        skills.append(
            {
                "id": _slug(meta.get("name") or dirname),
                "name": meta.get("name") or dirname,
                "description": meta.get("description") or "",
                "path": path,
                "raw_url": raw,
                "source": "github",
            }
        )
    return {"repo": repo, "ref": ref, "count": len(skills), "skills": skills}


class ImportReq(BaseModel):
    """Import a skill from a remote SKILL.md (e.g. skills.sh → GitHub)."""

    url: str
    plugin_id: str
    id: Optional[str] = None  # override the derived slug


@router.post("/import", dependencies=[Depends(require_master_key)])
async def import_skill(req: ImportReq) -> Dict[str, Any]:
    """Fetch a SKILL.md by URL, parse its frontmatter, and install it.

    Accepts a direct raw URL or a GitHub blob link (auto-converted to raw).
    skills.sh entries are GitHub-backed, so grab the SKILL.md's GitHub link.
    The fetched markdown (frontmatter + body) is written verbatim via the same
    path as /create.
    """
    url = (req.url or "").strip()
    # GitHub blob → raw.
    if "github.com" in url and "/blob/" in url:
        url = url.replace("github.com", "raw.githubusercontent.com").replace(
            "/blob/", "/"
        )
    if not (url.startswith("http://") or url.startswith("https://")):
        raise HTTPException(status_code=400, detail="url must be http(s)")
    if not (url.endswith(".md") or "raw.githubusercontent" in url):
        raise HTTPException(
            status_code=400,
            detail="provide a direct SKILL.md URL (GitHub raw or blob link)",
        )
    try:
        resp = requests.get(url, timeout=12, headers={"Accept": "text/plain"})
        resp.raise_for_status()
        text = resp.text
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"failed to fetch skill: {exc}")
    if not text.strip():
        raise HTTPException(status_code=422, detail="fetched skill body is empty")

    meta = _parse_skill_frontmatter(text)
    name = str(meta.get("name") or "imported skill")
    sid = req.id or _slug(name)
    create_req = CreateReq(
        id=sid,
        plugin_id=req.plugin_id,
        name=name,
        description=meta.get("description"),
        triggers=[],
        body=text,
    )
    out = await create(create_req)
    out["imported_from"] = url
    out["name"] = name
    return out


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


# ── Inline source view / edit for installed skills (Catalog deep-dive) ──────
class SkillSourceReq(BaseModel):
    """Overwrite an installed skill's SKILL.md body in place."""

    plugin_id: str
    body: str


def _resolve_installed_skill_path(skill_id: str, plugin_id: str) -> Path:
    """Resolve the on-disk markdown file for an installed skill via its plugin
    manifest. Honors the manifest's declared ``file`` rather than assuming the
    default ``skills/<id>.md`` layout, and guards against a manifest ``file``
    that escapes the plugin directory."""
    plugin_dir = _PLUGINS_DIR / plugin_id
    manifest_path = plugin_dir / "plugin.yaml"
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="plugin not found")
    try:
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"manifest read failed: {exc}")
    entry = next(
        (s for s in (manifest.get("skills") or []) if (s or {}).get("id") == skill_id),
        None,
    )
    if entry is None:
        raise HTTPException(
            status_code=404, detail="skill not registered in this plugin"
        )
    rel = entry.get("file") or f"skills/{skill_id}.md"
    md_path = (plugin_dir / rel).resolve()
    if not str(md_path).startswith(str(plugin_dir.resolve())):
        raise HTTPException(status_code=400, detail="skill file escapes plugin dir")
    return md_path


@router.get("/source/{skill_id}", dependencies=[Depends(require_master_key)])
async def read_source(skill_id: str, plugin_id: str) -> Dict[str, Any]:
    """Return the raw SKILL.md body for an installed skill so the Catalog
    deep-dive can review or edit it in place."""
    if not _ID_RE.match(skill_id) or not _ID_RE.match(plugin_id):
        raise HTTPException(status_code=400, detail="invalid id")
    md_path = _resolve_installed_skill_path(skill_id, plugin_id)
    if not md_path.exists():
        raise HTTPException(status_code=404, detail="skill file missing on disk")
    body = md_path.read_text(encoding="utf-8")
    parsed = _parse_skill_frontmatter(body)
    return {
        "skill_id": skill_id,
        "plugin_id": plugin_id,
        "file": str(md_path.relative_to(_PLUGINS_DIR.parent)),
        "body": body,
        "name": parsed.get("name") or skill_id,
        "description": parsed.get("description") or "",
        "editable": True,
    }


@router.put("/source/{skill_id}", dependencies=[Depends(require_master_key)])
async def write_source(skill_id: str, req: SkillSourceReq) -> Dict[str, Any]:
    """Overwrite an installed skill's SKILL.md body in place. Reload the
    plugin registry (POST /api/plugins/reload) afterward so the edit activates
    without an API restart — the chat path reads the live registry."""
    if not _ID_RE.match(skill_id) or not _ID_RE.match(req.plugin_id):
        raise HTTPException(status_code=400, detail="invalid id")
    if not req.body or not req.body.strip():
        raise HTTPException(status_code=400, detail="skill body is required")
    md_path = _resolve_installed_skill_path(skill_id, req.plugin_id)
    if not md_path.exists():
        raise HTTPException(status_code=404, detail="skill file missing on disk")
    md_path.write_text(req.body, encoding="utf-8")
    logger.info("Edited skill '%s' in plugin '%s'", skill_id, req.plugin_id)
    return {
        "saved": True,
        "skill_id": skill_id,
        "plugin_id": req.plugin_id,
        "bytes": len(req.body.encode("utf-8")),
    }


# ═══ LB3-U1 — tree / file / relations / promote ═════════════════════════════
#
# Drill-down data for the Skills library panel (LB3-U2). All routes are
# master-key gated and never 500 on scan errors — scans degrade to empty
# lists so a broken manifest or workflow file can't take the panel down.

_WORKFLOWS_DIR = Path(__file__).parent.parent.parent / "workflows"

# Per-segment charset allowlist for /file paths. NOTE: "." and ".." both
# match the charset, so they are rejected explicitly below.
_SEGMENT_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")

_FILE_BYTES_MAX = 1_000_000  # single-file read cap for the Files tab

# Workflow-reference scan cache (short TTL — workflows/*.yaml rarely churn,
# but edits should show up without an API restart).
_REL_TTL_SECONDS = 30.0
_rel_cache: Dict[str, Any] = {"ts": 0.0, "map": {}}


def _write_atomic(p: Path, text: str) -> None:
    """tmp+replace write — same discipline as prompts.py."""
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(p)  # atomic


def _get_plugin_service():
    """Live registry — read at call time so tests can swap the singleton."""
    from .plugins import plugin_service

    return plugin_service


def _plugin_record(plugin_id: str) -> Dict[str, Any]:
    """Registry record for a plugin id, 404 when unknown."""
    record = _get_plugin_service().get_plugin(plugin_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"plugin '{plugin_id}' not found")
    return record


def _host_plugin_ids(skill_id: str) -> List[str]:
    """Every registry plugin that ships this skill (registry order)."""
    service = _get_plugin_service()
    out: List[str] = []
    try:
        for plugin in service.list_plugins():
            if any(s.get("id") == skill_id for s in plugin.get("skills", [])):
                out.append(plugin["id"])
    except Exception as exc:  # noqa: BLE001 — never 500 on scan errors
        logger.warning("skill host scan failed: %s", exc)
    return out


def _resolve_host(skill_id: str, plugin_id: Optional[str]) -> Dict[str, Any]:
    """Resolve the host plugin record for a skill. plugin_id (when given)
    must be charset-safe and actually host the skill; otherwise the first
    registry host wins. 404 when the skill is installed nowhere."""
    if plugin_id:
        if not _ID_RE.match(plugin_id):
            raise HTTPException(status_code=400, detail="invalid plugin id")
        record = _plugin_record(plugin_id)
        if not any(s.get("id") == skill_id for s in record.get("skills", [])):
            raise HTTPException(
                status_code=404,
                detail=f"skill '{skill_id}' not registered in plugin '{plugin_id}'",
            )
        return record
    hosts = _host_plugin_ids(skill_id)
    if not hosts:
        raise HTTPException(
            status_code=404, detail=f"skill '{skill_id}' not installed in any plugin"
        )
    return _plugin_record(hosts[0])


def _manifest_entry(plugin_dir: Path, skill_id: str) -> Optional[Dict[str, Any]]:
    """The raw plugin.yaml skills[] entry (carries the declared ``file``,
    which the registry skill dicts don't). None on any read error."""
    try:
        manifest = (
            yaml.safe_load((plugin_dir / "plugin.yaml").read_text(encoding="utf-8"))
            or {}
        )
        for entry in manifest.get("skills") or []:
            if (entry or {}).get("id") == skill_id:
                return dict(entry)
    except Exception as exc:  # noqa: BLE001
        logger.warning("manifest read failed for %s: %s", plugin_dir, exc)
    return None


def _contained(plugin_dir: Path, rel: str) -> Path:
    """Resolve rel against the plugin dir; 400 when it escapes."""
    target = (plugin_dir / rel).resolve()
    root = plugin_dir.resolve()
    if target != root and not str(target).startswith(str(root) + os.sep):
        raise HTTPException(status_code=400, detail="path escapes plugin dir")
    return target


def _dir_node(base: Path, rel: Path, depth: int = 0) -> Dict[str, Any]:
    """One directory subtree, capped at depth 6. Listing errors degrade to
    an empty children list — never 500."""
    node: Dict[str, Any] = {
        "name": rel.name,
        "path": rel.as_posix(),
        "type": "dir",
        "children": [],
    }
    if depth > 6:
        return node
    try:
        entries = sorted(
            (base / rel).iterdir(), key=lambda p: (p.is_file(), p.name.lower())
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("skill dir listing failed at %s: %s", base / rel, exc)
        return node
    for child in entries:
        child_rel = rel / child.name
        if child.is_dir():
            node["children"].append(_dir_node(base, child_rel, depth + 1))
        else:
            try:
                size = child.stat().st_size
            except OSError:
                size = 0
            node["children"].append(
                {
                    "name": child.name,
                    "path": child_rel.as_posix(),
                    "type": "file",
                    "size": size,
                }
            )
    return node


@router.get("/tree/{skill_id}", dependencies=[Depends(require_master_key)])
async def skill_tree(skill_id: str, plugin_id: Optional[str] = None) -> Dict[str, Any]:
    """File tree for a skill: registration entry + declared file + optional
    ``skills/<skill_id>/`` directory contents. Single-file skills render an
    honest one-node tree — no synthetic scaffolding."""
    if not _ID_RE.match(skill_id):
        raise HTTPException(status_code=400, detail="invalid skill id")
    record = _resolve_host(skill_id, plugin_id)
    plugin_dir = Path(record["path"])
    entry = _manifest_entry(plugin_dir, skill_id)
    rel = (entry or {}).get("file") or f"skills/{skill_id}.md"
    declared = _contained(plugin_dir, rel)  # 400 on manifest traversal

    children: List[Dict[str, Any]] = []
    try:
        size = declared.stat().st_size if declared.is_file() else 0
    except OSError:
        size = 0
    children.append(
        {
            "name": declared.name,
            "path": Path(rel).as_posix(),
            "type": "file",
            "size": size,
            "declared": True,
            "exists": declared.is_file(),
        }
    )
    skill_dir_rel = Path("skills") / skill_id
    try:
        has_dir = _contained(plugin_dir, skill_dir_rel.as_posix()).is_dir()
    except HTTPException:
        has_dir = False
    if has_dir:
        children.append(_dir_node(plugin_dir, skill_dir_rel))

    def _count(nodes: List[Dict[str, Any]]) -> int:
        return sum(1 + _count(n.get("children") or []) for n in nodes)

    return {
        "skill_id": skill_id,
        "plugin_id": record["id"],
        "origin": record.get("origin"),
        "registration": entry,
        "root": {"name": skill_id, "type": "skill", "children": children},
        "node_count": _count(children),
    }


@router.get("/file", dependencies=[Depends(require_master_key)])
async def skill_file(plugin_id: str, path: str) -> Dict[str, Any]:
    """Single file body for the Files tab. Charset allowlist on every path
    segment plus resolved-path containment against the plugin dir — this
    repo has had a real glob-traversal incident; belt AND suspenders."""
    if not _ID_RE.match(plugin_id):
        raise HTTPException(status_code=400, detail="invalid plugin id")
    path = (path or "").strip()
    if not path or len(path) > 512 or "\\" in path or path.startswith("/"):
        raise HTTPException(status_code=400, detail="invalid path")
    for segment in path.split("/"):
        if segment in ("", ".", "..") or not _SEGMENT_RE.match(segment):
            raise HTTPException(status_code=400, detail="invalid path segment")
    record = _plugin_record(plugin_id)
    plugin_dir = Path(record["path"])
    target = _contained(plugin_dir, path)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    try:
        size = target.stat().st_size
    except OSError:
        size = 0
    if size > _FILE_BYTES_MAX:
        raise HTTPException(status_code=413, detail="file too large to view inline")
    body = target.read_text(encoding="utf-8", errors="replace")
    return {
        "plugin_id": plugin_id,
        "path": path,
        "name": target.name,
        "size": size,
        "body": body,
    }


def _hook_skill_refs(hooks: Any):
    """Yield ``<plugin>.<skill>`` refs declared on skill_injector hook
    configs inside a ``hooks:`` block (any stage). Tolerant of shape drift."""
    if not isinstance(hooks, dict):
        return
    for entries in hooks.values():
        if not isinstance(entries, list):
            continue
        for hook in entries:
            if not isinstance(hook, dict) or hook.get("name") != "skill_injector":
                continue
            config = hook.get("config")
            refs = config.get("skills") if isinstance(config, dict) else None
            for ref in refs or []:
                if isinstance(ref, str) and "." in ref:
                    yield ref


def _iter_workflow_skill_refs(doc: Dict[str, Any]):
    """Yield (ref, via, step_id) for every explicit skill reference in one
    workflow document: step.skills lists and skill_injector configs (both
    step-level and workflow-level defaults)."""
    for hooks_block in (doc.get("hooks"), (doc.get("defaults") or {}).get("hooks")):
        for ref in _hook_skill_refs(hooks_block):
            yield ref, "skill_injector", None
    for step in doc.get("steps") or []:
        if not isinstance(step, dict):
            continue
        step_id = step.get("id")
        for ref in step.get("skills") or []:
            if isinstance(ref, str) and "." in ref:
                yield ref, "step.skills", step_id
        for ref in _hook_skill_refs(step.get("hooks")):
            yield ref, "skill_injector", step_id


def _workflow_ref_map() -> Dict[str, List[Dict[str, Any]]]:
    """ref → [workflow records], rebuilt at most every _REL_TTL_SECONDS.
    Scan errors degrade per-file — one bad YAML never hides the rest."""
    now = time.monotonic()
    if (now - _rel_cache["ts"]) < _REL_TTL_SECONDS:
        return _rel_cache["map"]
    out: Dict[str, List[Dict[str, Any]]] = {}
    try:
        files = sorted(_WORKFLOWS_DIR.glob("*.yaml"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("workflow scan failed: %s", exc)
        files = []
    for wf_path in files:
        try:
            doc = yaml.safe_load(wf_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("skipping unparsable workflow %s: %s", wf_path.name, exc)
            continue
        if not isinstance(doc, dict):
            continue
        base = {
            "id": doc.get("id") or wf_path.stem,
            "name": doc.get("name") or wf_path.stem,
            "file": wf_path.name,
        }
        try:
            for ref, via, step_id in _iter_workflow_skill_refs(doc):
                out.setdefault(ref, []).append({**base, "via": via, "step": step_id})
        except Exception as exc:  # noqa: BLE001
            logger.warning("workflow ref scan failed for %s: %s", wf_path.name, exc)
    _rel_cache.update({"ts": now, "map": out})
    return out


@router.get("/relations/{skill_id}", dependencies=[Depends(require_master_key)])
async def skill_relations(
    skill_id: str, plugin_id: Optional[str] = None
) -> Dict[str, Any]:
    """"Works with XYZ" data: host plugin(s), workflows referencing
    ``<plugin>.<skill>`` (step.skills or skill_injector configs), chat
    trigger keywords. Agents honestly report none in v1 — agent YAMLs
    don't reference plugin skills yet, and we don't fake relations."""
    if not _ID_RE.match(skill_id):
        raise HTTPException(status_code=400, detail="invalid skill id")
    record = _resolve_host(skill_id, plugin_id)
    hosts = _host_plugin_ids(skill_id) or [record["id"]]

    triggers: List[str] = []
    skill = next(
        (s for s in record.get("skills", []) if s.get("id") == skill_id), {}
    )
    for trigger in skill.get("triggers") or []:
        if isinstance(trigger, dict) and trigger.get("keyword"):
            triggers.append(trigger["keyword"])

    ref_map = _workflow_ref_map()
    workflows: List[Dict[str, Any]] = []
    seen = set()
    for host in hosts:
        for rec in ref_map.get(f"{host}.{skill_id}", []):
            key = (rec["file"], rec["via"], rec.get("step"))
            if key in seen:
                continue
            seen.add(key)
            workflows.append(rec)

    return {
        "skill_id": skill_id,
        "plugin_id": record["id"],
        "host_plugins": hosts,
        "triggers": triggers,
        "workflows": workflows,
        "agents": [],
        "agents_note": "no agent definitions reference plugin skills in v1",
    }


class PromoteReq(BaseModel):
    """Promote an installed (typically system-layer) skill into a writable
    user-layer plugin so it survives image rebuilds and can be edited."""

    plugin_id: Optional[str] = None  # source host (first registry host wins)
    target_plugin_id: Optional[str] = None  # default: user-skills


@router.post(
    "/{skill_id}/promote",
    status_code=201,
    dependencies=[Depends(require_master_key)],
)
async def promote_skill(
    skill_id: str, req: PromoteReq = Body(default=PromoteReq())
) -> Dict[str, Any]:
    """Copy a skill's SKILL.md + registration entry into a user-layer plugin
    (default ``user-skills``, created on demand). 409 when the target already
    registers the skill or the file exists; atomic writes; rescans after."""
    if not _ID_RE.match(skill_id):
        raise HTTPException(status_code=400, detail="invalid skill id")
    target_id = req.target_plugin_id or "user-skills"
    if not _ID_RE.match(target_id):
        raise HTTPException(status_code=400, detail="invalid target plugin id")

    service = _get_plugin_service()
    source = _resolve_host(skill_id, req.plugin_id)  # 404 when not installed
    source_dir = Path(source["path"])
    entry = _manifest_entry(source_dir, skill_id) or {
        "id": skill_id,
        "file": f"skills/{skill_id}.md",
    }
    src_file = _contained(source_dir, entry.get("file") or f"skills/{skill_id}.md")
    if not src_file.is_file():
        raise HTTPException(status_code=404, detail="skill file missing on disk")
    body = src_file.read_text(encoding="utf-8")

    if service.user_dir is None:
        raise HTTPException(
            status_code=503, detail="no writable user plugin layer configured"
        )
    existing_target = service.get_plugin(target_id)
    target_dir = service.user_dir / target_id
    if existing_target and not (target_dir / "plugin.yaml").exists():
        # The id resolves to a system-layer plugin; creating a same-id user
        # plugin would shadow the WHOLE system plugin — refuse.
        raise HTTPException(
            status_code=409,
            detail=(
                f"'{target_id}' is a system-layer plugin — promoting into it "
                "would shadow the shipped plugin; pick a user-layer target"
            ),
        )
    service.ensure_user_plugin(target_id)

    manifest_path = target_dir / "plugin.yaml"
    try:
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500, detail=f"failed to read target manifest: {exc}"
        )
    skills_block = manifest.setdefault("skills", [])
    if any((s or {}).get("id") == skill_id for s in skills_block):
        raise HTTPException(
            status_code=409,
            detail=f"skill '{skill_id}' already registered in '{target_id}'",
        )
    dst_rel = f"skills/{skill_id}.md"
    dst_file = target_dir / "skills" / f"{skill_id}.md"
    if dst_file.exists():
        raise HTTPException(
            status_code=409,
            detail=f"file {dst_rel} already exists in '{target_id}' — "
            "investigate before promoting",
        )

    _write_atomic(dst_file, body)
    new_entry: Dict[str, Any] = {"id": skill_id, "file": dst_rel}
    if entry.get("triggers"):
        new_entry["triggers"] = entry["triggers"]
    else:
        new_entry["triggers"] = [{"manual": True}]
    skills_block.append(new_entry)
    _write_atomic(
        manifest_path,
        yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True),
    )
    service.scan_plugins()
    logger.info(
        "Promoted skill '%s' from plugin '%s' into user-layer '%s'",
        skill_id,
        source["id"],
        target_id,
    )
    return {
        "promoted": True,
        "skill_id": skill_id,
        "source_plugin_id": source["id"],
        "target_plugin_id": target_id,
        "origin": "user",
        "file": dst_rel,
    }
