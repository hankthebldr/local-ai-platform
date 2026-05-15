#!/usr/bin/env python3
"""
MCP Service — Registry and JSON-RPC client for local MCP servers.

The service keeps a persisted catalogue of MCP server registrations
(stdio or HTTP) and exposes a small synchronous JSON-RPC client used by
the routers, the workflow engine (for tool steps), and the agent chat
runtime.

Design notes
------------
* Persistence: data/config/mcp_servers.json (chmod 0600). Env / headers
  are stored in cleartext on disk because the host is already the trust
  boundary; the API serialises masked variants to clients.
* Stdio transport: each request spawns a short-lived process, performs
  the MCP initialize -> request -> shutdown handshake on stdin/stdout,
  and tears down. Long-lived sessions are out of scope for v1; the
  workflow engine treats every step's tool call as one-shot.
* HTTP transport: simple JSON-RPC POSTs against the configured URL.
  SSE is treated identically for non-streaming methods.
* Errors never crash the registry — every transport error becomes a
  structured ``error`` field on the response.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

try:  # urllib is stdlib; requests is optional but already used elsewhere.
    import requests  # type: ignore
except ImportError:  # pragma: no cover - requests is a hard dep in this repo
    requests = None  # type: ignore

from ..logging_config import logger
from ..models.mcp_models import (
    MCPServerConfig,
    MCPServerCreate,
    MCPServerUpdate,
    MCPServerStatus,
    MCPTool,
)

PROTOCOL_VERSION = "2024-11-05"
CLIENT_INFO = {"name": "enclave", "version": "1.0.0"}


def _mask(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 6:
        return "***"
    return value[:3] + "…" + value[-2:]


def _config_dir() -> Path:
    return Path(os.getenv("DATA_CONFIG_DIR", "data/config"))


def _storage_path() -> Path:
    return _config_dir() / "mcp_servers.json"


class MCPService:
    """In-memory registry of MCP server registrations, backed by JSON on disk."""

    def __init__(self, storage_path: Optional[Path] = None):
        self._path = storage_path or _storage_path()
        self._lock = threading.RLock()
        self._servers: Dict[str, MCPServerConfig] = {}
        self._tools_cache: Dict[str, List[MCPTool]] = {}
        self._load()

    # ── persistence ─────────────────────────────────────────────────

    def _load(self) -> None:
        try:
            if not self._path.exists():
                return
            raw = json.loads(self._path.read_text() or "{}")
            servers = raw.get("servers", [])
            for entry in servers:
                try:
                    cfg = MCPServerConfig(**entry)
                    self._servers[cfg.id] = cfg
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Skipping invalid MCP entry: %s", exc)
            logger.info("Loaded %d MCP server registration(s)", len(self._servers))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to load MCP registry: %s", exc)

    def _persist(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "servers": [s.model_dump(mode="json") for s in self._servers.values()]
        }
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2))
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        tmp.replace(self._path)

    # ── public registry API ────────────────────────────────────────

    def list_servers(self, mask_secrets: bool = True) -> List[Dict[str, Any]]:
        with self._lock:
            return [self._public_view(s, mask_secrets) for s in self._servers.values()]

    def get_server(
        self, server_id: str, mask_secrets: bool = True
    ) -> Optional[Dict[str, Any]]:
        with self._lock:
            s = self._servers.get(server_id)
            return self._public_view(s, mask_secrets) if s else None

    def register(self, create: MCPServerCreate) -> Dict[str, Any]:
        cfg = MCPServerConfig(**create.model_dump())
        self._validate_transport(cfg)
        with self._lock:
            if cfg.id in self._servers:
                raise ValueError(f"server '{cfg.id}' already registered")
            self._servers[cfg.id] = cfg
            self._persist()
        logger.info("Registered MCP server %s (%s)", cfg.id, cfg.transport)
        return self._public_view(cfg)

    def update(self, server_id: str, patch: MCPServerUpdate) -> Dict[str, Any]:
        with self._lock:
            cur = self._servers.get(server_id)
            if cur is None:
                raise KeyError(server_id)
            data = cur.model_dump()
            for k, v in patch.model_dump(exclude_unset=True).items():
                data[k] = v
            updated = MCPServerConfig(**data)
            self._validate_transport(updated)
            self._servers[server_id] = updated
            self._tools_cache.pop(server_id, None)
            self._persist()
        return self._public_view(updated)

    def remove(self, server_id: str) -> bool:
        with self._lock:
            existed = server_id in self._servers
            self._servers.pop(server_id, None)
            self._tools_cache.pop(server_id, None)
            if existed:
                self._persist()
            return existed

    # ── handshake / discovery ──────────────────────────────────────

    def test_server(self, server_id: str) -> MCPServerStatus:
        cfg = self._require(server_id)
        try:
            tools = self._list_tools(cfg)
            self._tools_cache[server_id] = tools
            return MCPServerStatus(
                server_id=server_id,
                reachable=True,
                transport=cfg.transport,
                tools_count=len(tools),
            )
        except Exception as exc:  # noqa: BLE001
            return MCPServerStatus(
                server_id=server_id,
                reachable=False,
                transport=cfg.transport,
                error=str(exc),
            )

    def list_tools(self, server_id: str, force_refresh: bool = False) -> List[MCPTool]:
        cfg = self._require(server_id)
        if not force_refresh and server_id in self._tools_cache:
            return self._tools_cache[server_id]
        tools = self._list_tools(cfg)
        self._tools_cache[server_id] = tools
        return tools

    def invoke_tool(
        self, server_id: str, tool: str, arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        cfg = self._require(server_id)
        if not cfg.enabled:
            raise RuntimeError(f"server '{server_id}' is disabled")
        return self._jsonrpc(
            cfg,
            method="tools/call",
            params={"name": tool, "arguments": arguments},
        )

    # ── helpers ────────────────────────────────────────────────────

    def _require(self, server_id: str) -> MCPServerConfig:
        cfg = self._servers.get(server_id)
        if cfg is None:
            raise KeyError(server_id)
        return cfg

    def _validate_transport(self, cfg: MCPServerConfig) -> None:
        if cfg.needs_command() and not cfg.command:
            raise ValueError("stdio transport requires 'command'")
        if cfg.needs_url() and not cfg.url:
            raise ValueError("http/sse transport requires 'url'")

    def _public_view(
        self, cfg: Optional[MCPServerConfig], mask_secrets: bool = True
    ) -> Optional[Dict[str, Any]]:
        if cfg is None:
            return None
        out = cfg.model_dump(mode="json")
        if mask_secrets:
            out["env"] = {k: _mask(v) for k, v in cfg.env.items()}
            out["headers"] = {k: _mask(v) for k, v in cfg.headers.items()}
        tools = self._tools_cache.get(cfg.id, [])
        out["tools_count"] = len(tools)
        out["tools"] = [t.model_dump(mode="json") for t in tools]
        return out

    # ── JSON-RPC plumbing ──────────────────────────────────────────

    def _list_tools(self, cfg: MCPServerConfig) -> List[MCPTool]:
        result = self._jsonrpc(cfg, method="tools/list", params={})
        tools_raw = (result or {}).get("tools", [])
        out: List[MCPTool] = []
        for t in tools_raw:
            if not isinstance(t, dict):
                continue
            out.append(
                MCPTool(
                    server_id=cfg.id,
                    name=t.get("name", ""),
                    description=t.get("description"),
                    input_schema=t.get("inputSchema") or t.get("input_schema") or {},
                )
            )
        return out

    def _jsonrpc(
        self, cfg: MCPServerConfig, method: str, params: Dict[str, Any]
    ) -> Dict[str, Any]:
        if cfg.transport == "stdio":
            return self._jsonrpc_stdio(cfg, method, params)
        return self._jsonrpc_http(cfg, method, params)

    def _jsonrpc_stdio(
        self, cfg: MCPServerConfig, method: str, params: Dict[str, Any]
    ) -> Dict[str, Any]:
        if not cfg.command:
            raise RuntimeError("stdio server missing command")

        # Spawn a fresh subprocess per request. MCP servers expect an
        # initialize handshake before any other method.
        proc_env = {**os.environ, **cfg.env}
        proc = subprocess.Popen(
            [cfg.command, *cfg.args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=proc_env,
            cwd=cfg.cwd or None,
            text=True,
            bufsize=1,
        )
        deadline = time.monotonic() + cfg.timeout_seconds
        try:
            # initialize
            self._write_frame(
                proc,
                {
                    "jsonrpc": "2.0",
                    "id": str(uuid.uuid4()),
                    "method": "initialize",
                    "params": {
                        "protocolVersion": PROTOCOL_VERSION,
                        "capabilities": {},
                        "clientInfo": CLIENT_INFO,
                    },
                },
            )
            self._read_frame(proc, deadline)

            # notify initialized
            self._write_frame(
                proc,
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
            )

            # the actual request
            req_id = str(uuid.uuid4())
            self._write_frame(
                proc,
                {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params},
            )
            resp = self._read_frame(proc, deadline)
            if "error" in resp:
                raise RuntimeError(resp["error"].get("message", "MCP error"))
            return resp.get("result", {})
        finally:
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except Exception:  # noqa: BLE001
                proc.kill()

    def _write_frame(self, proc: subprocess.Popen, payload: Dict[str, Any]) -> None:
        if proc.stdin is None:
            raise RuntimeError("stdin pipe closed")
        line = json.dumps(payload) + "\n"
        proc.stdin.write(line)
        proc.stdin.flush()

    def _read_frame(self, proc: subprocess.Popen, deadline: float) -> Dict[str, Any]:
        if proc.stdout is None:
            raise RuntimeError("stdout pipe closed")
        while True:
            if time.monotonic() > deadline:
                raise TimeoutError("MCP handshake timed out")
            line = proc.stdout.readline()
            if not line:
                stderr = ""
                if proc.stderr:
                    try:
                        stderr = proc.stderr.read() or ""
                    except Exception:  # noqa: BLE001
                        pass
                raise RuntimeError(
                    f"MCP server exited unexpectedly: {stderr.strip() or 'no stderr'}"
                )
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue  # skip non-JSON banner lines
            if msg.get("method", "").startswith("notifications/"):
                continue  # ignore server-initiated notifications
            if "id" in msg or "error" in msg or "result" in msg:
                return msg

    def _jsonrpc_http(
        self, cfg: MCPServerConfig, method: str, params: Dict[str, Any]
    ) -> Dict[str, Any]:
        if requests is None:
            raise RuntimeError("requests is not installed; cannot use http transport")
        if not cfg.url:
            raise RuntimeError("http server missing url")
        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": method,
            "params": params,
        }
        resp = requests.post(
            cfg.url,
            json=payload,
            headers=cfg.headers,
            timeout=cfg.timeout_seconds,
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        if "error" in data and data["error"]:
            err = data["error"]
            raise RuntimeError(
                err.get("message") if isinstance(err, dict) else str(err)
            )
        return data.get("result", {})


# ── Module singleton ────────────────────────────────────────────────────

_default_service: Optional[MCPService] = None


def get_mcp_service() -> MCPService:
    global _default_service
    if _default_service is None:
        _default_service = MCPService()
    return _default_service
