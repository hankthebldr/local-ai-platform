"""Task Menu library — agentic task schemas as a first-class Library kind (LB6).

A **TaskSchema** is a persisted superset of a Composer ``dfStepTemplates``
record: a named, taggable, ref-carrying blueprint for one agentic step
(persona + role + instructions + outputs + format + prompt/hook references).
The Tasks library manages, discovers, creates, and edits these schemas and
feeds the Composer Task bench — WITHOUT ever mutating the frozen 13-entry
``dfStepTemplates`` array in main.js (see the bench-feed mechanism in
js/library/tasks.js + main.js: library tasks ride their own Map + drag MIME).

Storage (persistence seam 2 — runtime-mutable state under ``data/`` ==
``user_storage_root`` in containers, so it survives image rebuilds):

    user_storage_root/tasks/<id>.json      writable operator layer (JSON-per-schema)

There is **no repo ``tasks/`` fallback** — the oob layer IS the curated
catalog shipped in the COPY'd tree at ``api/config/tasks_catalog.json``
(the 13 dfStepTemplates as ``source: builtin`` seeds). CRUD writes are
master-key gated (``require_master_key``); reads stay open.

Path traversal is rejected by an id-charset allowlist AND resolved-path
containment (the same discipline as ``prompts.py`` ``_path`` — this repo had
a real glob-traversal incident). Writes are atomic (tmp+replace).

Discovery is **refresh-only egress** (privacy-first appliance): ``GET
/api/tasks/discover`` NEVER touches the network — it merges the curated
catalog with the last persisted remote digest plus a ``fetched_at`` staleness
stamp. The sole egress is ``POST /api/tasks/discover/refresh`` (master-key,
wired to a visible operator button), which fetches the remote catalog URL
governed by ``discovery_sources.json`` and fail-softs to the persisted digest.

``POST /{id}/render`` materializes a schema's prompt refs through
PromptComposer as a pure library, so the frozen workflow engine is untouched.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..logging_config import logger
from ..middleware import require_master_key

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

_REPO_ROOT = Path(__file__).resolve().parents[2]
# Curated oob layer — the COPY'd repo tree (persistence seam 1). Ships with
# the image, never written to; the 13 dfStepTemplates as source:builtin seeds.
_CATALOG_FILE = _REPO_ROOT / "api" / "config" / "tasks_catalog.json"
# user layer fallback when no deployment is detected (bare unit tests / dev).
_USER_FALLBACK = _REPO_ROOT / "data" / "tasks"

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")
# The closed engine 8-kind vocabulary (workflow_models.py:405) — pattern
# affinity is badge/filter only in v1, so unknown entries are dropped, never
# a hard error (read-only reference to the engine surface).
PATTERN_KINDS = frozenset(
    {"llm", "parallel", "loop", "a2a", "orchestrator", "consolidate", "ralph", "code"}
)
# 'discover' is reserved so the single-segment GET /discover route can never
# be shadowed by a task literally named 'discover'.
_RESERVED_IDS = frozenset({"discover"})

DIGEST_KIND = "tasks"


def _tasks_root() -> Path:
    """user_storage_root/tasks — deployment-resolved, test-patchable."""
    try:
        from ..services.deployment import _get_current

        return _get_current().user_storage_root / "tasks"
    except Exception:  # noqa: BLE001 — no deployment detected (unit tests)
        return _USER_FALLBACK


def _task_path(task_id: str, must_exist: bool = True) -> Path:
    """Resolve one task id to its user-layer JSON file with full containment."""
    if not _ID_RE.match(task_id or ""):
        raise HTTPException(
            status_code=400, detail="invalid task id (alnum start, alnum/_/-, <=80)"
        )
    base = _tasks_root().resolve()
    candidate = (base / f"{task_id}.json").resolve()
    try:
        candidate.relative_to(base)
    except ValueError:
        raise HTTPException(status_code=400, detail="path escapes task library")
    if must_exist and not candidate.is_file():
        raise HTTPException(status_code=404, detail=f"task '{task_id}' not found")
    return candidate


def _write_atomic(p: Path, data: Dict[str, Any]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(p)  # atomic


# ── Schema models ───────────────────────────────────────────────────────────


class TaskInstructions(BaseModel):
    system_prompt: str = ""
    blocks: List[str] = Field(default_factory=list)


class TaskModelFit(BaseModel):
    preferred_role: Optional[str] = None
    models: List[str] = Field(default_factory=list)


class TaskRefs(BaseModel):
    role_ref: Optional[str] = None
    template_ref: Optional[str] = None
    # HookSpec-shaped, display-only badges in v1 (attach rides follow-up #4).
    hooks: List[Dict[str, Any]] = Field(default_factory=list)


class TaskSchema(BaseModel):
    id: str
    name: str
    persona: Optional[str] = None
    role: str = "general"
    instructions: TaskInstructions = Field(default_factory=TaskInstructions)
    outputs: List[str] = Field(default_factory=lambda: ["result"])
    format: str = "raw"
    intended_output: Optional[str] = None
    pattern_affinity: List[str] = Field(default_factory=list)
    model_fit: TaskModelFit = Field(default_factory=TaskModelFit)
    refs: TaskRefs = Field(default_factory=TaskRefs)
    tags: List[str] = Field(default_factory=list)
    num_outputs: Optional[int] = None
    is_decision: bool = False
    source: Literal["builtin", "user"] = "user"


class RenderRequest(BaseModel):
    task: Optional[str] = None
    context: str = ""
    constraints: List[str] = Field(default_factory=list)


class InstallRequest(BaseModel):
    target_id: Optional[str] = None


def _clean_schema(body: TaskSchema, *, task_id: str, source: str) -> Dict[str, Any]:
    """Normalize a schema for persistence: force id/source, guarantee ≥1
    output (the AgentStep contract), drop unknown pattern-affinity kinds."""
    data = body.model_dump()
    data["id"] = task_id
    data["source"] = source
    outputs = [str(o) for o in (data.get("outputs") or []) if str(o).strip()]
    if not outputs:
        raise HTTPException(
            status_code=400,
            detail="a task must declare at least one output (AgentStep contract)",
        )
    data["outputs"] = outputs
    data["pattern_affinity"] = [
        k for k in (data.get("pattern_affinity") or []) if k in PATTERN_KINDS
    ]
    return data


# ── Curated catalog + persisted remote digest (read side) ───────────────────


def _load_catalog() -> List[Dict[str, Any]]:
    """The 13 curated builtin seeds from the COPY'd tree. Never raises."""
    try:
        doc = json.loads(_CATALOG_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("tasks_catalog.json unreadable — no builtin seeds")
        return []
    tasks = doc.get("tasks") if isinstance(doc, dict) else doc
    out: List[Dict[str, Any]] = []
    for rec in tasks if isinstance(tasks, list) else []:
        if isinstance(rec, dict) and rec.get("id"):
            rec = dict(rec)
            rec["source"] = "builtin"
            out.append(rec)
    return out


def _read_task_file(p: Path) -> Optional[Dict[str, Any]]:
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    data.setdefault("id", p.stem)
    data["source"] = "user"
    return data


def _list_user_tasks() -> List[Dict[str, Any]]:
    base = _tasks_root()
    if not base.exists():
        return []
    out: List[Dict[str, Any]] = []
    for p in sorted(base.glob("*.json")):
        if p.name.endswith(".tmp"):
            continue
        rec = _read_task_file(p)
        if rec:
            out.append(rec)
    return out


# ── CRUD (list first; /discover* BEFORE the /{id} catch-alls) ───────────────


@router.get("", response_model=List[TaskSchema])
async def list_tasks(
    tag: Optional[str] = None, pattern: Optional[str] = None
) -> List[TaskSchema]:
    """List operator task schemas (user layer). Optional ?tag= (exact tag
    membership) and ?pattern= (pattern_affinity membership) filters. Never
    500s — a corrupt schema file is skipped, not fatal."""
    rows = _list_user_tasks()
    if tag:
        rows = [r for r in rows if tag in (r.get("tags") or [])]
    if pattern:
        rows = [r for r in rows if pattern in (r.get("pattern_affinity") or [])]
    return [TaskSchema(**r) for r in rows]


@router.get("/discover")
async def discover_tasks():
    """Read-open: the curated catalog + the PERSISTED remote task digest +
    a ``fetched_at`` staleness stamp. NEVER touches the network — refresh is
    a separate operator-triggered POST (privacy-first: no egress on read /
    tab-activation)."""
    from ..services import discovery_fetch

    dig = discovery_fetch.read_digest(DIGEST_KIND)
    installed = {t["id"] for t in _list_user_tasks() if t.get("id")}
    return {
        "fetched_at": dig.get("fetched_at"),
        "sources": dig.get("sources", []),
        "builtins": _load_catalog(),
        "records": dig.get("records", []),
        "installed": sorted(installed),
    }


def _tasks_catalog_url() -> str:
    """Remote task-catalog URL governed by discovery_sources.json (Admin ▸
    Sources) with an env fallback. Empty when unconfigured — refresh then
    fail-softs to the persisted digest (there is no default remote source)."""
    try:
        from ..services import agentic_discovery

        raw = agentic_discovery._read_sources_file()
        u = (raw.get("catalog_urls") or {}).get("tasks")
        if isinstance(u, str) and u.strip():
            return u.strip()
    except Exception:  # noqa: BLE001 — degrade to env
        pass
    return os.getenv("ENCLAVE_TASKS_CATALOG_URL", "").strip()


def _normalize_remote(payload: Any) -> List[Dict[str, Any]]:
    """Map a remote catalog document into digest task records. Tolerant of a
    top-level list or a ``{"tasks": [...]}`` mapping; each record gets a
    content_sha so the Discovered-tab diff badges work."""
    from ..services import discovery_fetch

    items = payload.get("tasks") if isinstance(payload, dict) else payload
    out: List[Dict[str, Any]] = []
    for rec in items if isinstance(items, list) else []:
        if not isinstance(rec, dict) or not rec.get("id"):
            continue
        rid = str(rec["id"])
        if not _ID_RE.match(rid):
            continue  # hostile/odd id — skip, never abort the refresh
        rec = dict(rec)
        rec["source"] = "remote"
        rec["content_sha"] = discovery_fetch.sha256_text(
            json.dumps(rec, sort_keys=True, ensure_ascii=False)
        )
        out.append(rec)
    return out


@router.post("/discover/refresh", dependencies=[Depends(require_master_key)])
async def refresh_task_discovery():
    """Operator-triggered digest refresh — the ONLY call site that reaches
    the network. Fetches the remote task-catalog URL (governed by
    discovery_sources.json) and atomically replaces the persisted digest.
    Fail-soft: an unconfigured / dead / malformed source degrades to the
    prior digest with the error surfaced on the sources[] entry."""
    from ..services import discovery_fetch

    url = _tasks_catalog_url()
    if not url:
        dig = discovery_fetch.read_digest(DIGEST_KIND)
        return {
            "fetched_at": dig.get("fetched_at"),
            "sources": [
                {"url": "", "ok": False, "error": "no tasks catalog url configured"}
            ],
            "builtins": _load_catalog(),
            "records": dig.get("records", []),
        }
    try:
        import requests

        timeout = float(os.getenv("ENCLAVE_DISCOVERY_TIMEOUT", "12"))
        r = requests.get(url, timeout=timeout)
        r.raise_for_status()
        records = _normalize_remote(r.json())
        doc = discovery_fetch.write_digest(
            DIGEST_KIND,
            records,
            sources=[{"url": url, "ok": True, "count": len(records)}],
        )
        logger.info("task digest refreshed: %d records from %s", len(records), url)
        return {**doc, "builtins": _load_catalog()}
    except Exception as exc:  # noqa: BLE001 — fail-soft, keep prior records
        logger.warning("task digest refresh failed for %s: %s", url, exc)
        dig = discovery_fetch.read_digest(DIGEST_KIND)
        return {
            "fetched_at": dig.get("fetched_at"),
            "sources": [{"url": url, "ok": False, "error": str(exc)}],
            "builtins": _load_catalog(),
            "records": dig.get("records", []),
        }


def _find_discover_record(digest_id: str) -> Optional[Dict[str, Any]]:
    """A discoverable record by id — curated builtin first, then the
    persisted remote digest. Read-only (no network)."""
    for rec in _load_catalog():
        if rec.get("id") == digest_id:
            return rec
    from ..services import discovery_fetch

    for rec in discovery_fetch.read_digest(DIGEST_KIND).get("records", []):
        if isinstance(rec, dict) and rec.get("id") == digest_id:
            return rec
    return None


@router.post(
    "/discover/{digest_id}/install",
    response_model=TaskSchema,
    status_code=201,
    dependencies=[Depends(require_master_key)],
)
async def install_discovered_task(digest_id: str, req: InstallRequest):
    """Copy a discoverable record (builtin seed or remote digest entry) into
    the writable user layer as an operator task. 409 when the target id
    already exists user-side; atomic; master-key gated."""
    if not _ID_RE.match(digest_id or ""):
        raise HTTPException(status_code=400, detail="invalid digest id")
    rec = _find_discover_record(digest_id)
    if rec is None:
        raise HTTPException(
            status_code=404,
            detail=f"discoverable task '{digest_id}' not found — refresh the digest",
        )
    task_id = (req.target_id or "").strip() or rec.get("id") or digest_id
    try:
        body = TaskSchema(**{**rec, "id": task_id, "source": "user"})
    except Exception as exc:  # noqa: BLE001 — malformed record → 400, never 500
        raise HTTPException(
            status_code=400, detail=f"discoverable record is not a valid task: {exc}"
        )
    if task_id in _RESERVED_IDS:
        raise HTTPException(status_code=400, detail=f"'{task_id}' is a reserved id")
    p = _task_path(task_id, must_exist=False)
    if p.is_file():
        raise HTTPException(
            status_code=409, detail=f"task '{task_id}' already exists in the user layer"
        )
    data = _clean_schema(body, task_id=task_id, source="user")
    data.setdefault("provenance", {})["installed_from"] = digest_id
    _write_atomic(p, data)
    logger.info("discovered task installed: %s -> %s", digest_id, task_id)
    return TaskSchema(**data)


@router.get("/{task_id}", response_model=TaskSchema)
async def get_task(task_id: str) -> TaskSchema:
    p = _task_path(task_id)
    rec = _read_task_file(p)
    if rec is None:
        raise HTTPException(status_code=400, detail=f"task '{task_id}' is corrupt")
    return TaskSchema(**rec)


@router.post(
    "", response_model=TaskSchema, status_code=201,
    dependencies=[Depends(require_master_key)],
)
async def create_task(body: TaskSchema) -> TaskSchema:
    """Create an operator task schema — always source='user', user layer."""
    if body.id in _RESERVED_IDS:
        raise HTTPException(status_code=400, detail=f"'{body.id}' is a reserved id")
    p = _task_path(body.id, must_exist=False)
    if p.is_file():
        raise HTTPException(status_code=409, detail=f"task '{body.id}' already exists")
    data = _clean_schema(body, task_id=body.id, source="user")
    _write_atomic(p, data)
    logger.info("task created: %s", body.id)
    return TaskSchema(**data)


@router.put(
    "/{task_id}", response_model=TaskSchema,
    dependencies=[Depends(require_master_key)],
)
async def update_task(task_id: str, body: TaskSchema) -> TaskSchema:
    """In-place edit of an operator task schema (full replace). 404 when the
    task doesn't exist — creates go through POST."""
    p = _task_path(task_id)  # 404 if missing
    data = _clean_schema(body, task_id=task_id, source="user")
    _write_atomic(p, data)
    logger.info("task updated: %s", task_id)
    return TaskSchema(**data)


@router.delete("/{task_id}", dependencies=[Depends(require_master_key)])
async def delete_task(task_id: str):
    p = _task_path(task_id)  # 404 if missing
    p.unlink()
    logger.info("task deleted: %s", task_id)
    return {"deleted": task_id}


# ── Render (pure PromptComposer preview; refs resolved) ──────────────────────


def _prompt_exists(kind: str, pid: str) -> bool:
    """True when a role/template prompt id resolves in either layer."""
    from . import prompts as prompts_router

    for layer in ("user", "oob"):
        try:
            p = prompts_router._path(kind, pid, layer, must_exist=False)
        except HTTPException:
            return False
        if p.is_file():
            return True
    return False


@router.post("/{task_id}/render")
async def render_task(task_id: str, req: RenderRequest):
    """Live preview — materialize the schema's refs through PromptComposer as
    a pure library (frozen engine untouched). Missing prompt refs → 400; hook
    names not matching the 10-builtin factory are a non-fatal ``warnings``
    field (custom hooks are legal; config shapes only fail at run time)."""
    from . import prompts as prompts_router
    from ..services.prompt_composer import PromptComposer

    p = _task_path(task_id)
    rec = _read_task_file(p)
    if rec is None:
        raise HTTPException(status_code=400, detail=f"task '{task_id}' is corrupt")
    schema = TaskSchema(**rec)
    refs = schema.refs

    # Role: an explicit role_ref must exist; otherwise the schema's own
    # system_prompt is the inline persona.
    role_inline = schema.instructions.system_prompt or "You are a helpful assistant."
    if refs.role_ref:
        if not _prompt_exists("role", refs.role_ref):
            raise HTTPException(
                status_code=400, detail=f"role ref '{refs.role_ref}' not found"
            )
        rp, _layer = prompts_router._resolve("role", refs.role_ref)
        role_inline = rp.read_text(encoding="utf-8")

    # Template: an explicit template_ref must exist; else the shared 5-part.
    if refs.template_ref:
        if not _prompt_exists("template", refs.template_ref):
            raise HTTPException(
                status_code=400, detail=f"template ref '{refs.template_ref}' not found"
            )
        template_name = f"{refs.template_ref}.jinja"
        templates_dir = prompts_router._template_search_dir(template_name)
    else:
        template_name = "five_part.jinja"
        templates_dir = prompts_router._base("oob", "template")

    # Hook refs: non-fatal validation vs the 10-builtin factory.
    warnings: List[str] = []
    factories = prompts_router._hook_factories()
    for h in refs.hooks:
        name = h.get("target") or h.get("name") if isinstance(h, dict) else None
        if name and name not in factories:
            warnings.append(
                f"hook '{name}' is not a built-in engine hook "
                "(custom hook — cannot be validated here)"
            )

    composer = PromptComposer(
        str(prompts_router._base("oob", "role")), str(templates_dir)
    )
    task_text = req.task or f"Execute the {schema.name} task."
    try:
        composed = composer.compose(
            role_ref=None,
            role_inline=role_inline,
            context=req.context,
            task=task_text,
            constraints=req.constraints,
            output_schema={},
            template_name=template_name,
        )
    except Exception as e:  # bad template / missing var -> 400, not 500
        raise HTTPException(status_code=400, detail=f"render failed: {e}")
    return {
        "system": composed.system,
        "user": composed.user,
        "params": composed.params,
        "warnings": warnings,
    }
