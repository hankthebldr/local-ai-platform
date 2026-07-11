"""Prompts library — a first-class object over two prompt layers.

The role library (prompts/roles/*.md) already shipped read-only via
api/routers/roles.py; this promotes Prompts to a full library kind with write
CRUD + a live render preview, mirroring the mcp.py CRUD surface. Two kinds:

  role     -> roles/<id>.md      (persona text; the StepPrompt.role_ref target)
  template -> templates/<id>.jinja (5-part Jinja skeleton)
  hook     -> hooks/<id>.md      (LB2-U1: configured preset of one of the 10
                                  built-in engine hooks — YAML frontmatter
                                  {stage, target, config, tags, intended_output}
                                  + markdown rationale)

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

Roles/templates carry classification in a ``<id>.meta.json`` sidecar
(services/prompt_meta.py — frontmatter would leak into PromptComposer
output); hooks carry meta in their frontmatter. All prompt WRITE routes are
master-key gated (LB2-U1); reads stay open. Hook save-time validation reads
the builtin hook modules and StepHooks stages via READ-ONLY imports — the
frozen engine files are never edited.

Path traversal is rejected by id-charset allowlist AND resolved-path
containment per layer (same discipline as roles.py — see the workspace
glob-traversal incident). Writes are atomic (tmp+replace). Render reuses
PromptComposer as a pure library, so the frozen workflow engine is untouched.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple

import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..logging_config import logger
from ..middleware import require_master_key
from ..services import prompt_meta

router = APIRouter(prefix="/api/prompts", tags=["prompts"])

_REPO_ROOT = Path(__file__).resolve().parents[2]
# oob layer: the COPY'd repo tree — shipped with the image, never written to.
_OOB_ROOT = _REPO_ROOT / "prompts"
# user layer fallback when no deployment is detected (bare unit tests / dev):
# repo data/ == user_storage_root in containers (deployment.py:120-122).
_USER_FALLBACK = _REPO_ROOT / "data" / "prompts"

_SUBDIR = {"role": "roles", "template": "templates", "hook": "hooks"}
_EXT = {"role": ".md", "template": ".jinja", "hook": ".md"}
PromptKind = Literal["role", "template", "hook"]
PromptLayer = Literal["oob", "user"]
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")
_VAR_RE = re.compile(r"{{\s*([a-zA-Z_][a-zA-Z0-9_]*)")

# Custom always-on hooks (api/hooks/custom/*.py) surface as READ-ONLY library
# entries for transparency — they attach to every bus, not per-step. Listed
# by filename only; the modules are NEVER imported/executed on a read GET.
_CUSTOM_HOOKS_DIR = _REPO_ROOT / "api" / "hooks" / "custom"
_CUSTOM_PREFIX = "custom-"


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
    # Classification (sidecar for roles/templates, frontmatter for hooks).
    tags: List[str] = Field(default_factory=list)
    intended_output: Optional[str] = None
    token_estimate: Optional[int] = None  # approximate — never a gate
    # Hook-only fields.
    stage: Optional[str] = None
    target: Optional[str] = None
    always_on: bool = False  # custom api/hooks/custom entry


class Prompt(PromptSummary):
    body: str
    meta: Optional[Dict[str, Any]] = None  # full sidecar / frontmatter meta


class PromptWrite(BaseModel):
    id: str
    kind: PromptKind = "role"
    body: str


class PromptPatch(BaseModel):
    body: str


class MetaPatch(BaseModel):
    """PATCH /{kind}/{pid}/meta — the shared LB2/LB4/LB6 taxonomy fields.
    token_estimate is computed server-side and cannot be set by the client."""

    tags: Optional[List[str]] = None
    category: Optional[str] = None
    technique: Optional[List[str]] = None
    intended_output: Optional[str] = None
    model_fit: Optional[List[str]] = None
    input_scope: Optional[str] = None
    output_scope: Optional[str] = None


class HookTestRequest(BaseModel):
    """POST /hook/{pid}/test — factory instantiation, plus an optional
    validate_output dry-run of sample text through a synthetic HookContext."""

    sample_output: Optional[str] = None


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
        raise HTTPException(
            status_code=400, detail="invalid prompt id (alnum/_/-, <=80)"
        )
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


# ── Hook kind: validation against the frozen engine surface ────────────────
# A library hook is a configured preset of one of the 10 built-in engine
# hooks (the closed _instantiate_hook factory in workflow_engine.py). The
# factory map is mirrored here with READ-ONLY imports — the engine files are
# never edited (frozen), and the engine keeps its own copy authoritative.


def _hook_stages() -> Tuple[str, ...]:
    """The five step-scoped StepHooks stages — read-only model import."""
    from ..models.workflow_models import StepHooks

    return tuple(StepHooks.model_fields.keys())


def _hook_factories() -> Dict[str, type]:
    """name -> builtin hook class. Mirror of workflow_engine._instantiate_hook
    (read-only imports from api/hooks/builtins — exactly 10 modules)."""
    from api.hooks.builtins.analyse_xql_gate import AnalyseXqlGateHook
    from api.hooks.builtins.few_shot_injector import FewShotInjectorHook
    from api.hooks.builtins.json_schema import JsonSchemaHook
    from api.hooks.builtins.mcp_tool_invoker import MCPToolInvokerHook
    from api.hooks.builtins.output_logger import OutputLoggerHook
    from api.hooks.builtins.plugin_tool_invoker import PluginToolInvokerHook
    from api.hooks.builtins.refusal_detector import RefusalDetectorHook
    from api.hooks.builtins.retry_with_feedback import RetryWithFeedbackHook
    from api.hooks.builtins.skill_injector import SkillInjectorHook
    from api.hooks.builtins.token_budget import TokenBudgetHook

    return {
        "json_schema": JsonSchemaHook,
        "refusal_detector": RefusalDetectorHook,
        "retry_with_feedback": RetryWithFeedbackHook,
        "token_budget": TokenBudgetHook,
        "output_logger": OutputLoggerHook,
        "few_shot_injector": FewShotInjectorHook,
        "plugin_tool_invoker": PluginToolInvokerHook,
        "mcp_tool_invoker": MCPToolInvokerHook,
        "skill_injector": SkillInjectorHook,
        "analyse_xql_gate": AnalyseXqlGateHook,
    }


def _split_frontmatter(text: str) -> Tuple[Optional[Dict[str, Any]], str]:
    """(frontmatter dict | None, markdown rest). None when the document has
    no leading '---' block or the YAML is not a mapping."""
    if not text.startswith("---"):
        return None, text
    parts = text.split("\n---", 2)
    if len(parts) < 2:
        return None, text
    try:
        meta = yaml.safe_load(parts[0][3:])
    except yaml.YAMLError:
        return None, text
    if not isinstance(meta, dict):
        return None, text
    rest = parts[1]
    if len(parts) == 3:
        rest = parts[1] + "\n---" + parts[2]
    return meta, rest.lstrip("\n")


def _validate_hook_document(text: str) -> Dict[str, Any]:
    """Save-time validation for kind=hook. Returns the frontmatter meta.

    Enforces: frontmatter present; `target` names one of the 10 builtins;
    `stage` is one of the five step-scoped StepHooks stages AND matches the
    builtin's declared stage; `config` keys (and required params) checked
    against inspect.signature(cls.__init__) — HookSpec.config is splatted
    as kwargs by the engine, so this is exactly what would fail at run time.
    """
    meta, _rest = _split_frontmatter(text)
    if meta is None:
        raise HTTPException(
            status_code=400,
            detail="hook body must start with YAML frontmatter "
            "(--- stage/target/config … ---)",
        )
    target = meta.get("target")
    factories = _hook_factories()
    if not isinstance(target, str) or target not in factories:
        raise HTTPException(
            status_code=400,
            detail=f"hook target {target!r} is not one of the built-in engine "
            f"hooks: {sorted(factories)}",
        )
    stages = _hook_stages()
    stage = meta.get("stage")
    if stage not in stages:
        raise HTTPException(
            status_code=400,
            detail=f"hook stage {stage!r} must be one of the step-scoped "
            f"StepHooks stages: {list(stages)}",
        )
    cls = factories[target]
    params = inspect.signature(cls.__init__).parameters
    declared = params.get("stage").default if "stage" in params else None
    if (
        declared is not inspect.Parameter.empty
        and declared is not None
        and stage != declared
    ):
        raise HTTPException(
            status_code=400,
            detail=f"builtin '{target}' declares stage '{declared}' — "
            f"got '{stage}'",
        )
    config = meta.get("config") or {}
    if not isinstance(config, dict):
        raise HTTPException(status_code=400, detail="hook config must be a mapping")
    allowed = {p for p in params if p != "self"}
    unknown = sorted(set(config) - allowed)
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"unknown config key(s) {unknown} for builtin '{target}' "
            f"(allowed: {sorted(allowed)})",
        )
    missing = sorted(
        name
        for name, p in params.items()
        if name not in ("self", "name", "stage")
        and p.default is inspect.Parameter.empty
        and p.kind
        in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
        and name not in config
    )
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"missing required config key(s) {missing} for builtin '{target}'",
        )
    return meta


def _custom_hook_summaries() -> List["PromptSummary"]:
    """READ-ONLY always-on entries for api/hooks/custom/*.py. Filesystem scan
    only — the modules are never imported here (no code execution on GET)."""
    out: List[PromptSummary] = []
    if not _CUSTOM_HOOKS_DIR.is_dir():
        return out
    for py in sorted(_CUSTOM_HOOKS_DIR.glob("*.py")):
        if py.name.startswith("__") or not py.is_file():
            continue
        try:
            text = py.read_text(encoding="utf-8")
        except OSError:
            continue
        out.append(
            PromptSummary(
                id=f"{_CUSTOM_PREFIX}{py.stem}",
                kind="hook",
                name=_name_from_id(py.stem),
                summary=_summarize(text) or "custom hook module",
                provenance="user",
                always_on=True,
                token_estimate=prompt_meta.estimate_tokens(text),
            )
        )
    return out


def _custom_hook_path(pid: str) -> Optional[Path]:
    """Contained path for a custom-<stem> id, or None. Charset + containment
    discipline (the glob-traversal incident lesson)."""
    stem = pid[len(_CUSTOM_PREFIX) :]
    if not _ID_RE.match(stem or ""):
        return None
    base = _CUSTOM_HOOKS_DIR.resolve()
    candidate = (base / f"{stem}.py").resolve()
    try:
        candidate.relative_to(base)
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def _summary(kind: str, p: Path, layer: str) -> PromptSummary:
    text = p.read_text(encoding="utf-8")
    rec = PromptSummary(
        id=p.stem,
        kind=kind,
        name=_name_from_id(p.stem),
        summary=_summarize(text),
        variables=_variables(text),
        provenance=layer,
        token_estimate=prompt_meta.estimate_tokens(text),
    )
    if kind == "hook":
        fm, rest = _split_frontmatter(text)
        if fm:
            rec.stage = fm.get("stage") if isinstance(fm.get("stage"), str) else None
            rec.target = fm.get("target") if isinstance(fm.get("target"), str) else None
            rec.tags = [t for t in (fm.get("tags") or []) if isinstance(t, str)]
            io = fm.get("intended_output")
            rec.intended_output = io if isinstance(io, str) else None
            rec.summary = _summarize(rest) or rec.summary
    else:
        meta = prompt_meta.read_meta(p)
        if meta:
            rec.tags = [t for t in (meta.get("tags") or []) if isinstance(t, str)]
            io = meta.get("intended_output")
            rec.intended_output = io if isinstance(io, str) else None
            if isinstance(meta.get("token_estimate"), int):
                rec.token_estimate = meta["token_estimate"]
    return rec


@router.get("", response_model=List[PromptSummary])
async def list_prompts(kind: Optional[PromptKind] = None) -> List[PromptSummary]:
    """List roles ∪ templates ∪ hooks (or one kind), merged across layers.

    oob scans first, then user — later wins, so a user copy shadows the
    shipped one by id and the row's provenance flips to 'user'. Globs are
    extension-scoped so `*.meta.json` sidecars never surface as prompts.
    Custom api/hooks/custom hooks append as read-only always-on entries."""
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
                if p.name.endswith(".meta.json"):  # belt over the ext braces
                    continue
                try:
                    merged[p.stem] = _summary(k, p, layer)
                except OSError:
                    continue
        out.extend(merged[pid] for pid in sorted(merged))
        if k == "hook":
            out.extend(_custom_hook_summaries())
    return out


@router.get("/{kind}/{pid}", response_model=Prompt)
async def get_prompt(kind: PromptKind, pid: str) -> Prompt:
    # Custom always-on hooks: read-only transparency entries (source text as
    # body, never imported/executed). All write routes 404/403 on these ids.
    if kind == "hook" and pid.startswith(_CUSTOM_PREFIX):
        cp = _custom_hook_path(pid)
        if cp is None:
            raise HTTPException(status_code=404, detail=f"hook '{pid}' not found")
        text = cp.read_text(encoding="utf-8")
        return Prompt(
            id=pid,
            kind="hook",
            name=_name_from_id(pid[len(_CUSTOM_PREFIX) :]),
            summary=_summarize(text) or "custom hook module",
            body=text,
            provenance="user",
            always_on=True,
            token_estimate=prompt_meta.estimate_tokens(text),
        )
    p, layer = _resolve(kind, pid)
    text = p.read_text(encoding="utf-8")
    rec = _summary(kind, p, layer)
    meta: Optional[Dict[str, Any]] = None
    if kind == "hook":
        meta, _rest = _split_frontmatter(text)
    else:
        meta = prompt_meta.read_meta(p)
    return Prompt(body=text, meta=meta, **rec.model_dump())


@router.post(
    "",
    response_model=Prompt,
    status_code=201,
    dependencies=[Depends(require_master_key)],
)
async def create_prompt(body: PromptWrite) -> Prompt:
    """Create a prompt — writes ALWAYS land in the user layer. Hook bodies
    are validated against the builtin factory surface at save time."""
    if body.kind == "hook":
        if body.id.startswith(_CUSTOM_PREFIX):
            raise HTTPException(
                status_code=400,
                detail=f"the '{_CUSTOM_PREFIX}' id prefix is reserved for "
                "read-only api/hooks/custom entries",
            )
        _validate_hook_document(body.body)
    user_p = _path(body.kind, body.id, "user", must_exist=False)
    if user_p.is_file():
        raise HTTPException(
            status_code=409, detail=f"{body.kind} '{body.id}' already exists"
        )
    if _path(body.kind, body.id, "oob", must_exist=False).is_file():
        raise HTTPException(
            status_code=409,
            detail=(
                f"{body.kind} '{body.id}' already exists in the shipped (oob) "
                "layer — edit it (copy-on-write) or promote it instead"
            ),
        )
    _write_atomic(user_p, body.body)
    logger.info("prompt created (user layer): %s/%s", body.kind, body.id)
    return await get_prompt(body.kind, body.id)


@router.patch(
    "/{kind}/{pid}",
    response_model=Prompt,
    dependencies=[Depends(require_master_key)],
)
async def update_prompt(kind: PromptKind, pid: str, patch: PromptPatch) -> Prompt:
    """Edit a prompt. An oob id is copied-on-write into the user layer
    (auto-promote) — the shipped file is never touched."""
    if kind == "hook":
        _validate_hook_document(patch.body)
    _src, layer = _resolve(kind, pid)  # 404 when in neither layer
    dst = _path(kind, pid, "user", must_exist=False)
    _write_atomic(dst, patch.body)
    if layer == "oob":
        logger.info("prompt %s/%s copy-on-write promoted to user layer", kind, pid)
    return await get_prompt(kind, pid)


@router.patch(
    "/{kind}/{pid}/meta",
    dependencies=[Depends(require_master_key)],
)
async def update_prompt_meta(kind: PromptKind, pid: str, patch: MetaPatch):
    """Classification meta (LB2-U1). Roles/templates → `<id>.meta.json`
    sidecar in the owning layer; hooks → merged into their frontmatter.
    Writes always land user-side (copy-on-write auto-promote for oob ids);
    token_estimate is recomputed server-side. Atomic tmp+replace."""
    fields = patch.model_dump(exclude_none=True)
    errors = prompt_meta.validate_meta_fields(fields)
    if errors:
        raise HTTPException(status_code=400, detail="; ".join(errors))
    src, layer = _resolve(kind, pid)  # 404 (custom-* ids never resolve here)
    body_text = src.read_text(encoding="utf-8")
    dst = _path(kind, pid, "user", must_exist=False)

    if kind == "hook":
        fm, rest = _split_frontmatter(body_text)
        if fm is None:
            raise HTTPException(status_code=400, detail="hook has no frontmatter")
        fm.update(fields)
        fm["token_estimate"] = prompt_meta.estimate_tokens(body_text)
        doc = (
            "---\n" + yaml.safe_dump(fm, sort_keys=False).rstrip() + "\n---\n\n" + rest
        )
        _validate_hook_document(doc)  # meta merge must not break the preset
        _write_atomic(dst, doc)
        merged = fm
    else:
        if layer == "oob":
            # copy-on-write auto-promote: meta travels with a user-layer copy
            _write_atomic(dst, body_text)
            logger.info("prompt %s/%s copy-on-write promoted (meta edit)", kind, pid)
        merged = prompt_meta.merge_meta(prompt_meta.read_meta(dst), fields, body_text)
        prompt_meta.write_meta(dst, merged)
    logger.info("prompt meta updated: %s/%s", kind, pid)
    return {"id": pid, "kind": kind, "meta": merged}


@router.delete("/{kind}/{pid}", dependencies=[Depends(require_master_key)])
async def delete_prompt(kind: PromptKind, pid: str):
    """Delete the USER copy (reverting to oob when shipped). Pure-oob ids are
    protected — a container rebuild would silently restore them anyway.
    Sidecar meta is unlinked with the file."""
    user_p = _path(kind, pid, "user", must_exist=False)
    oob_p = _path(kind, pid, "oob", must_exist=False)
    if user_p.is_file():
        user_p.unlink()
        prompt_meta.delete_meta(user_p)  # sidecar never outlives its prompt
        reverted = oob_p.is_file()
        logger.info(
            "prompt user copy deleted: %s/%s%s",
            kind,
            pid,
            " (reverted to oob)" if reverted else "",
        )
        return {"deleted": f"{kind}/{pid}", "reverted_to_oob": reverted}
    if oob_p.is_file():
        raise HTTPException(
            status_code=403,
            detail=(
                f"{kind} '{pid}' is a shipped (oob) prompt and cannot be "
                "deleted — editing it creates a user-layer copy you can "
                "delete to revert"
            ),
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
        raise HTTPException(
            status_code=404, detail=f"no shipped (oob) {kind} '{pid}' to promote"
        )
    user_p = _path(kind, pid, "user", must_exist=False)
    if user_p.is_file():
        raise HTTPException(
            status_code=409, detail=f"{kind} '{pid}' already has a user-layer copy"
        )
    _write_atomic(user_p, oob_p.read_text(encoding="utf-8"))
    logger.info("prompt promoted to user layer: %s/%s", kind, pid)
    return await get_prompt(kind, pid)


@router.post("/hook/{pid}/test", dependencies=[Depends(require_master_key)])
async def test_hook(pid: str, req: HookTestRequest):
    """Hook Test pane backend (LB2-U1): validate + factory-instantiate the
    preset (exactly what the engine's _instantiate_hook would do with this
    HookSpec — engine untouched). validate_output hooks additionally dry-run
    the pasted sample through a synthetic HookContext, returning
    HookResult.action/feedback. Local-only; no model calls."""
    if pid.startswith(_CUSTOM_PREFIX):
        raise HTTPException(
            status_code=400,
            detail="custom always-on hooks register directly on the bus and "
            "have no per-step preset to test",
        )
    p, _layer = _resolve("hook", pid)
    text = p.read_text(encoding="utf-8")
    meta = _validate_hook_document(text)  # 400 with the precise reason
    cls = _hook_factories()[meta["target"]]
    config = meta.get("config") or {}
    try:
        hook = cls(**config)
    except Exception as e:  # noqa: BLE001 — surface as a 400, never a 500
        raise HTTPException(status_code=400, detail=f"hook instantiation failed: {e}")
    resp: Dict[str, Any] = {
        "ok": True,
        "id": pid,
        "target": meta["target"],
        "stage": meta["stage"],
        "config": config,
    }
    if meta["stage"] == "validate_output" and req.sample_output is not None:
        from ..services.hook_bus import HookContext

        ctx = HookContext(output=req.sample_output)
        try:
            result = hook(ctx)
            resp["dry_run"] = {
                "action": result.action,
                "feedback": result.feedback,
                "parsed": ctx.parsed is not None,
            }
        except Exception as e:  # noqa: BLE001 — dry-run failure is a result
            resp["dry_run"] = {"action": "error", "feedback": str(e), "parsed": False}
    return resp


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
            raise HTTPException(
                status_code=400, detail="template_ref escapes prompt library"
            )
        if candidate.is_file():
            return base
    return _base("oob", "template")


@router.post("/{kind}/{pid}/render")
async def render_prompt(kind: PromptKind, pid: str, req: RenderRequest):
    """Live preview — reuse PromptComposer as a pure library (engine untouched)."""
    if kind == "hook":
        raise HTTPException(
            status_code=400,
            detail="hooks are engine presets, not composable prompts — "
            "use POST /api/prompts/hook/{pid}/test",
        )
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
                role_ref=None,
                role_inline=body,
                context=req.context,
                task=req.task,
                constraints=req.constraints,
                output_schema={},
                template_name=template_name,
            )
        else:
            composed = composer.compose(
                role_ref=None,
                role_inline="You are a helpful assistant.",
                context=req.context,
                task=req.task,
                constraints=req.constraints,
                output_schema={},
                template_name=template_name,
            )
    except Exception as e:  # bad template / missing var -> 400, not 500
        raise HTTPException(status_code=400, detail=f"render failed: {e}")
    return {"system": composed.system, "user": composed.user, "params": composed.params}
