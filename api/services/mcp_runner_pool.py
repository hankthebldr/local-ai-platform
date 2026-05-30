"""
MCP Runner Pool — warm long-lived runners per workflow run.

The pre-Phase-2 path spawned a fresh subprocess for every stdio MCP tool call
(see ``MCPService._jsonrpc_stdio``). Each call paid the full
``initialize → notify → request → terminate`` cycle — 200–500 ms of overhead
for a sub-second tool call. The pool fixes that: one subprocess per
``(run_id, server_id)``, one handshake, many ``tools/call`` requests.

Scopes
------
The runner's lifetime is determined by who calls ``release`` on it:

  ``release_server(run_id, server_id)``  →  step-scoped (engine releases at
                                            step boundary; max freshness)
  ``release_workflow(run_id)``           →  workflow-scoped (engine releases
                                            at run end; fewest handshakes)

The pool itself only keys on the tuple; the scope label on
``MCPRunnerStats`` tells the operator what shape this run used. Region-scope
(compiler-promoted, contiguous same-MCP runs that don't straddle a heavy-
model step) is Phase 2b — it lands as a new caller pattern, not a pool
change.

Concurrency
-----------
The pool is safe to share across threads. Acquiring a runner that already
exists (alive + healthy) is a dict lookup under the RLock; spawning is
serialized on the same lock per ``(run_id, server_id)`` so two threads can't
race a duplicate subprocess into existence.

Two concurrent workflows that both declare the same server get separate
runners by design (cross-workflow isolation). MCP runner sharing across
workflows is deferred to 2.x.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Protocol, Tuple

try:
    import psutil  # type: ignore
except ImportError:  # pragma: no cover - psutil is a core dep
    psutil = None  # type: ignore

try:
    import requests  # type: ignore
except ImportError:  # pragma: no cover - requests is a core dep
    requests = None  # type: ignore

from ..logging_config import logger
from ..models.mcp_models import MCPServerConfig
from ..models.workflow_models import MCPRunnerStats

PROTOCOL_VERSION = "2024-11-05"
CLIENT_INFO = {"name": "enclave-runner-pool", "version": "1.0.0"}


# ── Runner protocol ───────────────────────────────────────────────────────


class MCPRunner(Protocol):
    """Capability contract every warm runner satisfies."""

    server_id: str
    pid: Optional[int]

    def call(self, method: str, params: Dict[str, object]) -> Dict[str, object]: ...

    def is_alive(self) -> bool: ...

    def close(self) -> MCPRunnerStats: ...

    def current_rss_mb(self) -> Optional[float]: ...


# ── Stdio runner ─────────────────────────────────────────────────────────


class StdioMCPRunner:
    """Warm stdio MCP runner.

    Lifecycle: ``spawn()`` boots the subprocess and performs the initialize
    handshake once. Subsequent ``call()`` invocations write a single
    JSON-RPC frame and read the matching response off the persisted
    stdin/stdout pipes. ``close()`` sends SIGTERM and reaps the subprocess,
    returning the captured stats.
    """

    def __init__(
        self,
        cfg: MCPServerConfig,
        proc: subprocess.Popen,
        scope: str,
        started_at: datetime,
        handshake_ms: float,
    ):
        self.server_id = cfg.id
        self.pid: Optional[int] = proc.pid
        self._cfg = cfg
        self._proc = proc
        self._scope = scope
        self._lock = threading.Lock()
        self._started_at = started_at
        self._handshake_ms = handshake_ms
        self._requests_handled = 0
        self._errors = 0
        self._total_response_ms = 0.0
        self._peak_rss_mb: Optional[float] = None
        self._closed = False
        self._closed_at: Optional[datetime] = None
        self._exit_code: Optional[int] = None

    @classmethod
    def spawn(cls, cfg: MCPServerConfig, scope: str = "workflow") -> "StdioMCPRunner":
        if not cfg.command:
            raise RuntimeError(f"stdio server '{cfg.id}' missing command")

        proc_env = {**os.environ, **cfg.env}
        started_at = datetime.now(timezone.utc)
        t0 = time.monotonic()
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
        try:
            deadline = time.monotonic() + cfg.timeout_seconds
            _write_frame(
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
            _read_frame(proc, deadline)
            _write_frame(
                proc, {"jsonrpc": "2.0", "method": "notifications/initialized"}
            )
        except Exception:
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except Exception:  # noqa: BLE001
                proc.kill()
            raise
        handshake_ms = (time.monotonic() - t0) * 1000.0
        logger.info(
            "stdio MCP runner '%s' spawned (pid=%s, scope=%s, handshake=%.1fms)",
            cfg.id,
            proc.pid,
            scope,
            handshake_ms,
        )
        return cls(cfg, proc, scope, started_at, handshake_ms)

    def call(self, method: str, params: Dict[str, object]) -> Dict[str, object]:
        if self._closed:
            raise RuntimeError(f"runner '{self.server_id}' already closed")
        if not self.is_alive():
            raise RuntimeError(f"runner '{self.server_id}' subprocess is dead")
        with self._lock:
            t0 = time.monotonic()
            req_id = str(uuid.uuid4())
            try:
                _write_frame(
                    self._proc,
                    {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "method": method,
                        "params": params,
                    },
                )
                deadline = time.monotonic() + self._cfg.timeout_seconds
                resp = _read_frame(self._proc, deadline)
            except Exception:
                self._errors += 1
                raise
            finally:
                self._total_response_ms += (time.monotonic() - t0) * 1000.0
                self._requests_handled += 1
            if "error" in resp and resp["error"]:
                self._errors += 1
                err = resp["error"]
                msg = err.get("message") if isinstance(err, dict) else str(err)
                raise RuntimeError(msg or "MCP error")
            return resp.get("result", {}) or {}

    def is_alive(self) -> bool:
        return self._proc.poll() is None and not self._closed

    def current_rss_mb(self) -> Optional[float]:
        if psutil is None or self.pid is None:
            return None
        try:
            p = psutil.Process(self.pid)
            rss_mb = p.memory_info().rss / (1024.0 * 1024.0)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return None
        # Track the high-water mark for the closing stats record.
        if self._peak_rss_mb is None or rss_mb > self._peak_rss_mb:
            self._peak_rss_mb = rss_mb
        return rss_mb

    def close(self) -> MCPRunnerStats:
        if self._closed:
            return self._stats()
        # Sample RSS one last time so peak_rss_mb reflects the lifetime peak
        # even when nobody polled current_rss_mb() during the run.
        self.current_rss_mb()
        self._closed = True
        self._closed_at = datetime.now(timezone.utc)
        try:
            self._proc.terminate()
            self._exit_code = self._proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            try:
                self._exit_code = self._proc.wait(timeout=1)
            except Exception:  # noqa: BLE001
                self._exit_code = None
        except Exception:  # noqa: BLE001
            self._exit_code = None
        logger.info(
            "stdio MCP runner '%s' closed (pid=%s, requests=%d, errors=%d, peak_rss=%s)",
            self.server_id,
            self.pid,
            self._requests_handled,
            self._errors,
            f"{self._peak_rss_mb:.1f}MB" if self._peak_rss_mb is not None else "n/a",
        )
        return self._stats()

    def _stats(self) -> MCPRunnerStats:
        avg = (
            self._total_response_ms / self._requests_handled
            if self._requests_handled
            else 0.0
        )
        return MCPRunnerStats(
            server_id=self.server_id,
            transport="stdio",
            pid=self.pid,
            scope=self._scope,  # type: ignore[arg-type]
            started_at=self._started_at,
            closed_at=self._closed_at,
            handshake_duration_ms=self._handshake_ms,
            requests_handled=self._requests_handled,
            errors=self._errors,
            peak_rss_mb=self._peak_rss_mb,
            avg_response_ms=avg,
            exit_code=self._exit_code,
        )


# ── HTTP session ─────────────────────────────────────────────────────────


class HttpMCPSession:
    """Long-lived HTTP session against an MCP endpoint.

    HTTP MCPs run externally, so there's no RSS to sample and no
    handshake to amortize beyond reusing a TCP connection. The "warm"
    benefit is keepalive + skipping initialize per call.
    """

    def __init__(self, cfg: MCPServerConfig, scope: str = "workflow"):
        if requests is None:
            raise RuntimeError("requests is not installed; HTTP MCP unavailable")
        if not cfg.url:
            raise RuntimeError(f"http server '{cfg.id}' missing url")
        self.server_id = cfg.id
        self.pid: Optional[int] = None
        self._cfg = cfg
        self._scope = scope
        self._session = requests.Session()
        self._session.headers.update(cfg.headers)
        self._started_at = datetime.now(timezone.utc)
        self._closed = False
        self._closed_at: Optional[datetime] = None
        self._requests_handled = 0
        self._errors = 0
        self._total_response_ms = 0.0
        # No handshake on HTTP — the spec relies on per-call params.
        self._handshake_ms = 0.0

    def call(self, method: str, params: Dict[str, object]) -> Dict[str, object]:
        if self._closed:
            raise RuntimeError(f"http session '{self.server_id}' already closed")
        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": method,
            "params": params,
        }
        t0 = time.monotonic()
        try:
            resp = self._session.post(
                self._cfg.url,
                json=payload,
                timeout=self._cfg.timeout_seconds,
            )
        except Exception:
            self._errors += 1
            self._requests_handled += 1
            self._total_response_ms += (time.monotonic() - t0) * 1000.0
            raise
        self._total_response_ms += (time.monotonic() - t0) * 1000.0
        self._requests_handled += 1
        if resp.status_code >= 400:
            self._errors += 1
            raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        if data.get("error"):
            self._errors += 1
            err = data["error"]
            msg = err.get("message") if isinstance(err, dict) else str(err)
            raise RuntimeError(msg or "MCP error")
        return data.get("result", {}) or {}

    def is_alive(self) -> bool:
        return not self._closed

    def current_rss_mb(self) -> Optional[float]:
        return None  # external process; not measurable from here

    def close(self) -> MCPRunnerStats:
        if not self._closed:
            self._closed = True
            self._closed_at = datetime.now(timezone.utc)
            try:
                self._session.close()
            except Exception:  # noqa: BLE001
                pass
        avg = (
            self._total_response_ms / self._requests_handled
            if self._requests_handled
            else 0.0
        )
        return MCPRunnerStats(
            server_id=self.server_id,
            transport="http",
            pid=None,
            scope=self._scope,  # type: ignore[arg-type]
            started_at=self._started_at,
            closed_at=self._closed_at,
            handshake_duration_ms=0.0,
            requests_handled=self._requests_handled,
            errors=self._errors,
            peak_rss_mb=None,
            avg_response_ms=avg,
            exit_code=None,
        )


# ── Pool ─────────────────────────────────────────────────────────────────


class MCPRunnerPool:
    """Per-process pool of warm MCP runners keyed on ``(run_id, server_id)``.

    The pool is created at app startup (module singleton via
    ``get_mcp_runner_pool``) and shared across workflow runs. Each run
    contributes its own keys; ``release_workflow(run_id)`` drains every
    runner attached to that run and returns the stats record list that
    the engine attaches to ``WorkflowRun.mcp_runners``.
    """

    def __init__(self, mcp_service=None):
        # mcp_service is a duck-typed handle to the registry; we only call
        # ``_require`` on it. Late-resolved to avoid a circular import.
        self._mcp_service = mcp_service
        self._runners: Dict[Tuple[str, str], MCPRunner] = {}
        self._stats: Dict[str, List[MCPRunnerStats]] = {}
        self._lock = threading.RLock()

    def attach_service(self, mcp_service) -> None:
        """Late-bind the MCPService handle (used when the pool is
        constructed before MCPService is importable)."""
        self._mcp_service = mcp_service

    def acquire(
        self, run_id: str, server_id: str, *, scope: str = "workflow"
    ) -> MCPRunner:
        """Return a warm runner for ``server_id`` under ``run_id``.

        Spawns a new runner on first call, or after a previous runner has
        died (subprocess crash, explicit close). Subsequent calls within
        the same ``run_id`` reuse the same instance.
        """
        if scope not in ("step", "region", "workflow"):
            raise ValueError(f"invalid scope: {scope!r}")
        key = (run_id, server_id)
        with self._lock:
            existing = self._runners.get(key)
            if existing is not None and existing.is_alive():
                return existing
            # Either no runner yet, or the previous one died.
            if existing is not None:
                # Capture stats for the dead runner so we don't lose its history.
                self._stats.setdefault(run_id, []).append(existing.close())
            runner = self._spawn(server_id, scope)
            self._runners[key] = runner
            return runner

    def release_server(self, run_id: str, server_id: str) -> Optional[MCPRunnerStats]:
        """Close one runner. Returns its stats, or None if it wasn't acquired."""
        key = (run_id, server_id)
        with self._lock:
            runner = self._runners.pop(key, None)
            if runner is None:
                return None
            stats = runner.close()
            self._stats.setdefault(run_id, []).append(stats)
            return stats

    def release_workflow(self, run_id: str) -> List[MCPRunnerStats]:
        """Close every runner attached to ``run_id``. Returns all stats records
        for the run (including any from earlier crashes/respawns)."""
        with self._lock:
            keys = [k for k in self._runners if k[0] == run_id]
            for key in keys:
                runner = self._runners.pop(key)
                self._stats.setdefault(run_id, []).append(runner.close())
            return self._stats.pop(run_id, [])

    def total_runner_overhead_mb(self) -> float:
        """Sum of current RSS across every live stdio runner. Used by the
        arch scheduler (Phase 6) to subtract MCP overhead from the effective
        memory budget. HTTP sessions contribute 0 (external process)."""
        with self._lock:
            total = 0.0
            for runner in self._runners.values():
                rss = runner.current_rss_mb()
                if rss is not None:
                    total += rss
            return total

    def runner_count(self) -> int:
        """Currently-live runner count (debug surface)."""
        with self._lock:
            return len(self._runners)

    def list_runners(self) -> List[Dict[str, object]]:
        """Debug snapshot: one entry per live runner.

        Used by the operator dashboard (``GET /api/mcp/runners``) and the
        Phase 7 ``/api/system/extensions`` overview.
        """
        with self._lock:
            return [
                {
                    "run_id": run_id,
                    "server_id": server_id,
                    "pid": runner.pid,
                    "rss_mb": runner.current_rss_mb(),
                }
                for (run_id, server_id), runner in self._runners.items()
            ]

    # ── internals ──────────────────────────────────────────────────

    def _spawn(self, server_id: str, scope: str) -> MCPRunner:
        if self._mcp_service is None:
            from .mcp_service import get_mcp_service

            self._mcp_service = get_mcp_service()
        cfg = self._mcp_service._require(server_id)  # noqa: SLF001
        if not cfg.enabled:
            raise RuntimeError(f"server '{server_id}' is disabled")
        if cfg.transport == "stdio":
            return StdioMCPRunner.spawn(cfg, scope=scope)
        if cfg.transport in ("http", "sse"):
            return HttpMCPSession(cfg, scope=scope)
        raise RuntimeError(f"unknown transport for '{server_id}': {cfg.transport}")


# ── JSON-RPC frame helpers (shared with MCPService) ──────────────────────


def _write_frame(proc: subprocess.Popen, payload: Dict[str, object]) -> None:
    if proc.stdin is None:
        raise RuntimeError("stdin pipe closed")
    proc.stdin.write(json.dumps(payload) + "\n")
    proc.stdin.flush()


def _read_frame(proc: subprocess.Popen, deadline: float) -> Dict[str, object]:
    if proc.stdout is None:
        raise RuntimeError("stdout pipe closed")
    while True:
        if time.monotonic() > deadline:
            raise TimeoutError("MCP request timed out")
        line = proc.stdout.readline()
        if not line:
            stderr = ""
            if proc.stderr is not None:
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
            continue  # banner / log line
        if msg.get("method", "").startswith("notifications/"):
            continue
        if "id" in msg or "error" in msg or "result" in msg:
            return msg


# ── Module singleton ─────────────────────────────────────────────────────

_default_pool: Optional[MCPRunnerPool] = None
_default_pool_lock = threading.Lock()


def get_mcp_runner_pool() -> MCPRunnerPool:
    """Return the process-wide pool, lazily created on first call."""
    global _default_pool
    with _default_pool_lock:
        if _default_pool is None:
            _default_pool = MCPRunnerPool()
        return _default_pool


def reset_mcp_runner_pool() -> None:
    """Drop the singleton (testing only)."""
    global _default_pool
    with _default_pool_lock:
        if _default_pool is not None:
            with _default_pool._lock:  # noqa: SLF001
                for runner in list(_default_pool._runners.values()):  # noqa: SLF001
                    try:
                        runner.close()
                    except Exception:  # noqa: BLE001
                        pass
                _default_pool._runners.clear()  # noqa: SLF001
                _default_pool._stats.clear()  # noqa: SLF001
        _default_pool = None
