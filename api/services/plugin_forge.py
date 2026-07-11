"""
Plugin forge — build an Enclave plugin from scratch with the LOCAL AI system.

LB5-U3 creation pipeline (spec_capture/scaffold_planner pattern):

  1. DRAFT   — an operator description is distilled into a PluginSpecDraft by
               a local model via OllamaService + ModelResolver (JSON-only
               system prompt, tolerant parse). When the model is down or
               returns junk, a deterministic fallback fills in: exactly one
               skill, zero tools — the wizard always has something editable.
  2. GENERATE — the (edited) spec is materialized into a PluginFileSet by a
               constrained template: plugin.yaml, skills/*.md, and optional
               tools/*.py stubs. Tool code runs IN-PROCESS, so tools are an
               explicit opt-in and the model never writes tool bodies — only
               the fixed stub template is emitted.
  3. INSTALL — after the wizard's mandatory per-file review, the file set is
               written under user_dir/<plugin_id> (charset-allowlisted ids,
               resolved-path containment on every file, atomic tmp+replace),
               every *.py passes the denylisted-imports lint, and
               scan_plugins() registers the result.

Never imports the workflow engine. Nothing leaves the box.
"""

from __future__ import annotations

import ast
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from ..logging_config import logger
from ..models.plugin_models import (
    PluginFile,
    PluginFileSet,
    PluginSkillDraft,
    PluginSpecDraft,
    PluginToolDraft,
)
from ..services.model_resolver import ModelResolver
from ..services.ollama_service import OllamaService

# Same discipline as the router's management plane (plugins.py): ids are
# charset-allowlisted, path segments too, and "."/".." are rejected outright.
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")
_SEGMENT_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")

# Imports that must never appear in in-process tool code. This is a lint for
# operator-reviewed generated stubs, not a sandbox — the chat path may still
# run tools under the profile's sandbox (tool_executor.py).
DENYLISTED_IMPORTS = frozenset(
    {
        "subprocess",
        "ctypes",
        "pty",
        "pickle",
        "marshal",
        "shelve",
        "importlib",
        "multiprocessing",
        "socket",
        "socketserver",
        "ftplib",
        "telnetlib",
    }
)
# Dynamic-execution builtins get the same treatment (they defeat the lint).
_DENYLISTED_CALLS = frozenset({"eval", "exec", "compile", "__import__"})

_SYSTEM_PROMPT = """You are the plugin forge of a LOCAL, self-hosted AI platform.
The operator describes a plugin they want. Draft a compact plugin spec.

A plugin bundles SKILLS (markdown guidance injected into chats when trigger
keywords match) and optionally TOOLS (local Python functions). Prefer skills;
propose tools only when the description clearly needs executable behavior.

Return ONLY a JSON object, no prose, with exactly this shape:
{
  "id": "<kebab-case-plugin-id>",
  "name": "<short human name>",
  "description": "<one sentence>",
  "skills": [
    {"id": "<kebab-case>", "name": "<short name>", "description": "<one line>",
     "triggers": ["<lowercase keyword>"], "inject": "system",
     "body": "<the markdown guidance the skill injects>"}
  ],
  "tools": [
    {"id": "<kebab-case>", "description": "<one line>",
     "parameters": {"<snake_case>": {"type": "string", "description": "<...>", "required": true}}}
  ]
}

Rules:
- 1-3 skills, each with 1-4 concrete trigger keywords and a useful body.
- "inject" is one of: system, user, none.
- 0-2 tools, ONLY if clearly needed. Tools are declared, never implemented —
  do not write any Python code.
- Ids are kebab-case, start with a letter or digit.
"""


def lint_tool_code(code: str, path: str = "tool") -> List[str]:
    """Denylisted-imports lint for in-process tool code.

    Returns a list of human-readable violations (empty = clean). A file that
    does not parse is a violation too — unparseable code can hide anything.
    """
    violations: List[str] = []
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return [f"{path}: not valid Python ({exc.msg} at line {exc.lineno})"]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in DENYLISTED_IMPORTS:
                    violations.append(f"{path}: denylisted import '{alias.name}'")
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root in DENYLISTED_IMPORTS:
                violations.append(f"{path}: denylisted import '{node.module}'")
        elif isinstance(node, ast.Name) and node.id in _DENYLISTED_CALLS:
            violations.append(f"{path}: denylisted builtin '{node.id}'")
    return violations


class PluginForgeService:
    """NL description → spec draft → file set, on a LOCAL model."""

    def __init__(self, ollama: OllamaService, resolver: Optional[ModelResolver] = None):
        self.ollama = ollama
        self.resolver = resolver or ModelResolver(ollama)

    # ── 1. DRAFT ──────────────────────────────────────────────────────
    def draft_spec(
        self,
        description: str,
        name: str = "",
        allow_tools: bool = False,
        model: Optional[str] = None,
        role: Optional[str] = "reasoning",
    ) -> PluginSpecDraft:
        """Draft an editable spec from an operator description.

        Tolerant by design: model down / prose / malformed JSON degrades to
        the deterministic fallback (one skill, zero tools) so the wizard
        always gets something loadable — never a 5xx.
        """
        try:
            resolved = self.resolver.resolve(
                model=model, role=role, default_role="reasoning"
            )
        except Exception as exc:  # noqa: BLE001 — resolve failure = fallback path
            logger.info("Plugin forge model resolve failed: %s", exc)
            resolved = model or "local model"

        prompt = f"OPERATOR DESCRIPTION:\n{description.strip()}"
        if name.strip():
            prompt += f"\n\nPREFERRED NAME: {name.strip()}"
        if not allow_tools:
            prompt += "\n\nThe operator wants a SKILLS-ONLY plugin: propose zero tools."

        data: Dict[str, Any] = {}
        try:
            result = self.ollama.chat(
                model=resolved,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                max_tokens=2048,
            )
            data = _extract_json((result or {}).get("content", "") or "")
        except Exception as exc:  # noqa: BLE001 — never hard-fail the wizard
            logger.info("Plugin forge falling back to deterministic spec: %s", exc)

        skills = _coerce_skills(data.get("skills"))
        if not skills:
            # Deterministic fallback: one skill, zero tools.
            return _fallback_spec(description, name, model=resolved)

        tools = _coerce_tools(data.get("tools")) if allow_tools else []
        pid = _slug(str(data.get("id") or "") or name or description) or "forged-plugin"
        return PluginSpecDraft(
            id=pid,
            name=str(data.get("name") or "").strip() or name.strip() or _title(pid),
            description=str(data.get("description") or "").strip()
            or description.strip()[:200],
            skills=skills,
            tools=tools,
            model=resolved,
            source="model",
        )

    # ── 2. GENERATE ───────────────────────────────────────────────────
    def generate_files(
        self, spec: PluginSpecDraft, include_tools: bool = False
    ) -> PluginFileSet:
        """Materialize a spec into a reviewable file set (nothing written).

        Skills-only by default: tool stubs are emitted only when the operator
        explicitly opted in. The stub template is fixed — the model never
        writes tool code.
        """
        _validate_spec_ids(spec)
        warnings: List[str] = []
        tools = list(spec.tools)
        if tools and not include_tools:
            warnings.append(
                f"{len(tools)} tool(s) omitted — tool code runs in-process and "
                "generation is an explicit opt-in"
            )
            tools = []

        files: List[PluginFile] = []
        manifest: Dict[str, Any] = {
            "id": spec.id,
            "name": spec.name or _title(spec.id),
            "version": spec.version or "0.1.0",
            "description": spec.description,
            "author": "operator",
            "skills": [],
            "tools": [],
        }
        for sk in spec.skills:
            manifest["skills"].append(
                {
                    "id": sk.id,
                    "file": f"skills/{sk.id}.md",
                    "triggers": [{"keyword": t} for t in sk.triggers if t.strip()],
                }
            )
            files.append(
                PluginFile(path=f"skills/{sk.id}.md", content=_skill_md(sk))
            )
        for tool in tools:
            manifest["tools"].append(
                {
                    "id": tool.id,
                    "file": f"tools/{_py_ident(tool.id)}.py",
                    "function": "execute",
                    "description": tool.description,
                    "parameters": tool.parameters,
                }
            )
            files.append(
                PluginFile(
                    path=f"tools/{_py_ident(tool.id)}.py", content=_tool_stub(tool)
                )
            )

        manifest_text = yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True)
        files.insert(0, PluginFile(path="plugin.yaml", content=manifest_text))
        return PluginFileSet(
            plugin_id=spec.id,
            files=files,
            warnings=warnings,
            tools_included=bool(tools),
        )

    # ── 3. INSTALL ────────────────────────────────────────────────────
    def install(self, plugin_service, file_set: PluginFileSet) -> dict:
        """Write a reviewed file set into the user layer and register it.

        Raises:
            FileExistsError — plugin id already installed (router → 409)
            ValueError      — bad ids/paths/manifest or denylist hits (→ 400)
            RuntimeError    — no writable user layer / registration failure
        """
        plugin_id = file_set.plugin_id
        if not _ID_RE.match(plugin_id or ""):
            raise ValueError("invalid plugin id")
        user_dir = plugin_service.user_dir
        if user_dir is None:
            raise RuntimeError(
                "no writable user plugin layer; deployment not initialised"
            )
        if plugin_service.has_plugin(plugin_id) or (Path(user_dir) / plugin_id).exists():
            raise FileExistsError(f"plugin already exists: {plugin_id}")
        if not file_set.files:
            raise ValueError("file set is empty")

        # Validate the (possibly wizard-edited) manifest before anything is
        # written — a bad plugin.yaml must never reach scan_plugins.
        by_path = {f.path: f for f in file_set.files}
        manifest_file = by_path.get("plugin.yaml")
        if manifest_file is None:
            raise ValueError("file set must include plugin.yaml")
        try:
            manifest = yaml.safe_load(manifest_file.content)
        except yaml.YAMLError as exc:
            raise ValueError(f"invalid plugin.yaml: {exc}") from exc
        if not isinstance(manifest, dict):
            raise ValueError("plugin.yaml must be a YAML mapping")
        if str(manifest.get("id") or "") != plugin_id:
            raise ValueError("plugin.yaml id must match the install plugin id")
        for entry in list(manifest.get("skills") or []) + list(
            manifest.get("tools") or []
        ):
            if not isinstance(entry, dict) or not _ID_RE.match(
                str(entry.get("id") or "")
            ):
                raise ValueError(f"invalid skill/tool id: {entry!r}")
            _checked_rel_path(str(entry.get("file") or ""))

        # Charset + containment on EVERY file path (this repo had a real
        # glob-traversal incident — belt AND suspenders), then the denylist
        # lint on every *.py (the wizard lets the operator edit files, so
        # the lint runs at install time, not just at generation).
        root = (Path(user_dir) / plugin_id).resolve()
        violations: List[str] = []
        resolved: List[tuple] = []
        for f in file_set.files:
            rel = _checked_rel_path(f.path)
            target = (root / rel).resolve()
            if target != root and not str(target).startswith(str(root) + os.sep):
                raise ValueError(f"path escapes plugin dir: {f.path}")
            if rel.endswith(".py"):
                violations.extend(lint_tool_code(f.content, path=rel))
            resolved.append((target, f.content))
        if violations:
            raise ValueError("denylist lint failed: " + "; ".join(violations))

        for target, content in resolved:
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(target.suffix + ".tmp")
            tmp.write_text(content, encoding="utf-8")
            tmp.replace(target)  # atomic

        plugin_service.scan_plugins()
        installed = plugin_service.get_plugin(plugin_id)
        if installed is None:
            raise RuntimeError(f"plugin {plugin_id} installed but not discoverable")
        logger.info(
            "Forged plugin installed: %s (%d files)", plugin_id, len(resolved)
        )
        return installed


# ── helpers ───────────────────────────────────────────────────────────


def _checked_rel_path(path: str) -> str:
    """Charset allowlist per segment; '.'/'..'/absolute/backslash rejected."""
    path = (path or "").strip()
    if not path or len(path) > 512 or "\\" in path or path.startswith("/"):
        raise ValueError(f"invalid path: {path!r}")
    for segment in path.split("/"):
        if segment in ("", ".", "..") or not _SEGMENT_RE.match(segment):
            raise ValueError(f"invalid path segment: {segment!r}")
    return path


def _validate_spec_ids(spec: PluginSpecDraft) -> None:
    if not _ID_RE.match(spec.id or ""):
        raise ValueError("invalid plugin id")
    for sk in spec.skills:
        if not _ID_RE.match(sk.id or ""):
            raise ValueError(f"invalid skill id: {sk.id!r}")
    for tool in spec.tools:
        if not _ID_RE.match(tool.id or ""):
            raise ValueError(f"invalid tool id: {tool.id!r}")


def _skill_md(sk: PluginSkillDraft) -> str:
    meta = {
        "name": sk.name or _title(sk.id),
        "description": sk.description,
        "inject": sk.inject if sk.inject in ("system", "user", "none") else "system",
    }
    front = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).strip()
    body = (sk.body or "").strip() or f"Guidance for {sk.name or sk.id}."
    return f"---\n{front}\n---\n\n{body}\n"


def _tool_stub(tool: PluginToolDraft) -> str:
    """The ONLY tool code the forge emits — a fixed, lint-clean stub."""
    required, optional = [], []
    for pname, pdef in (tool.parameters or {}).items():
        ident = _py_ident(pname)
        if isinstance(pdef, dict) and pdef.get("required"):
            required.append(ident)
        else:
            default = (pdef or {}).get("default") if isinstance(pdef, dict) else None
            optional.append(f"{ident}={default!r}")
    signature = ", ".join(required + optional + ["**kwargs"])
    desc = (tool.description or tool.id).strip().replace('"""', "'''")
    return (
        f'"""{desc}\n\n'
        "Generated by the Enclave plugin forge — a constrained stub, not model-\n"
        "written code. Fill in the logic below; denylisted imports (subprocess,\n"
        'socket, ctypes, pickle, importlib, ...) are rejected at install.\n"""\n'
        "\n\n"
        f"def execute({signature}):\n"
        f'    """Run the {tool.id} tool. Tools run IN-PROCESS — keep it local."""\n'
        "    return {\n"
        '        "status": "not_implemented",\n'
        f'        "tool": "{tool.id}",\n'
        '        "params": {k: v for k, v in locals().items() if k != "kwargs"},\n'
        "    }\n"
    )


def _fallback_spec(description: str, name: str, model: str) -> PluginSpecDraft:
    """Deterministic one-skill / zero-tools spec (model unavailable path)."""
    pid = _slug(name or description) or "forged-plugin"
    triggers = _keywords(description, limit=3) or [pid.split("-")[0]]
    body = (
        f"When this skill triggers, follow the operator's intent:\n\n"
        f"{description.strip() or 'Assist the operator.'}\n"
    )
    return PluginSpecDraft(
        id=pid,
        name=name.strip() or _title(pid),
        description=description.strip()[:200] or "Operator-forged plugin.",
        skills=[
            PluginSkillDraft(
                id="guide",
                name=f"{name.strip() or _title(pid)} guide",
                description=description.strip()[:120] or "Operator guidance.",
                triggers=triggers,
                inject="system",
                body=body,
            )
        ],
        tools=[],
        model=model,
        source="fallback",
    )


def _extract_json(content: str) -> Dict[str, Any]:
    """Pull the first JSON object out of a possibly-chatty model response."""
    match = re.search(r"\{[\s\S]*\}", content)
    if not match:
        return {}
    try:
        parsed = json.loads(match.group(0))
    except (ValueError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _coerce_skills(raw: Any) -> List[PluginSkillDraft]:
    out: List[PluginSkillDraft] = []
    if not isinstance(raw, list):
        return out
    for item in raw[:5]:
        if not isinstance(item, dict):
            continue
        sid = _slug(str(item.get("id") or item.get("name") or ""))
        if not sid:
            continue
        triggers = [
            str(t).strip().lower()
            for t in (item.get("triggers") or [])
            if isinstance(t, (str, int)) and str(t).strip()
        ][:6]
        inject = str(item.get("inject") or "system").strip().lower()
        out.append(
            PluginSkillDraft(
                id=sid,
                name=str(item.get("name") or "").strip() or _title(sid),
                description=str(item.get("description") or "").strip(),
                triggers=triggers,
                inject=inject if inject in ("system", "user", "none") else "system",
                body=str(item.get("body") or "").strip(),
            )
        )
    return out


def _coerce_tools(raw: Any) -> List[PluginToolDraft]:
    out: List[PluginToolDraft] = []
    if not isinstance(raw, list):
        return out
    for item in raw[:3]:
        if not isinstance(item, dict):
            continue
        tid = _slug(str(item.get("id") or item.get("name") or ""))
        if not tid:
            continue
        params: Dict[str, Any] = {}
        raw_params = item.get("parameters")
        if isinstance(raw_params, dict):
            for pname, pdef in list(raw_params.items())[:8]:
                key = _py_ident(str(pname))
                if not key:
                    continue
                pdef = pdef if isinstance(pdef, dict) else {}
                params[key] = {
                    "type": str(pdef.get("type") or "string"),
                    "description": str(pdef.get("description") or "").strip(),
                    "required": bool(pdef.get("required", False)),
                }
        out.append(
            PluginToolDraft(
                id=tid,
                description=str(item.get("description") or "").strip(),
                parameters=params,
            )
        )
    return out


_WORD_RE = re.compile(r"[a-z0-9]{3,}")
_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "plugin", "skill", "tool",
    "when", "into", "from", "your", "make", "create", "build", "want", "need",
    "should", "helps", "help", "user", "operator",
}


def _keywords(text: str, limit: int = 3) -> List[str]:
    seen: List[str] = []
    for w in _WORD_RE.findall((text or "").lower()):
        if w in _STOPWORDS or w in seen:
            continue
        seen.append(w)
        if len(seen) >= limit:
            break
    return seen


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", str(text or "").strip().lower()).strip("-")
    s = s[:80].strip("-")
    return s if _ID_RE.match(s or "") else ""


def _py_ident(text: str) -> str:
    s = re.sub(r"[^a-z0-9_]+", "_", str(text or "").strip().lower()).strip("_")
    return s or "param"


def _title(pid: str) -> str:
    return pid.replace("-", " ").replace("_", " ").title()
