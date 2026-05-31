"""
mcp_tool_invoker hook — invokes an MCP tool and stores the result in the
step's workspace BEFORE input resolution.

Mirrors ``plugin_tool_invoker`` (api/hooks/builtins/plugin_tool_invoker.py)
for MCP-protocol tools. Routes through ``MCPService.invoke_tool`` with the
workflow's ``run_id`` so calls share the warm runner pool (Phase 2) instead
of paying a fresh handshake per call.

Stage: before_step.

Two modes:

1. **Single-shot** (default): resolve each value in ``params_from`` against
   the workflow context, call ``MCPService.invoke_tool(server_id, tool, args,
   run_id=…)`` once, store the result.

2. **Iterating** (``for_each`` set): resolve a list, substitute
   ``{{ item.X }}`` placeholders in ``param_template`` for each item, call
   the tool per item, store the list of results.

The result is written to ``ctx.workflow.context.workspace[step.id][store_as]``,
so the step can reference ``<step_id>.<store_as>`` as one of its own inputs
(the workflow validator handles this same as plugin_tool_invoker).

Instrumentation (Phase 4.2 + 4.3): every call appends a Pydantic ``MCPCall``
record onto ``ctx.step_result.mcp_calls`` and bumps
``extension_overhead_ms`` so the Phase 4.4 rollup picks it up in the run
record.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from api.logging_config import logger
from api.services.hook_bus import HookContext, HookResult

from .plugin_tool_invoker import _substitute_item

# ── Shared MCPService singleton ─────────────────────────────────────────


_service_lock = threading.Lock()
_mcp_service: Any = None


def _get_mcp_service():
    """Lazy MCPService accessor, mirrors plugin_tool_invoker's pattern.

    Defaults to the module-level singleton from ``api.services.mcp_service``;
    tests can swap in a stub via ``set_mcp_service``.
    """
    global _mcp_service
    if _mcp_service is not None:
        return _mcp_service
    with _service_lock:
        if _mcp_service is None:
            from api.services.mcp_service import get_mcp_service

            _mcp_service = get_mcp_service()
    return _mcp_service


def set_mcp_service(service) -> None:
    """Override the module-level MCP service. Intended for tests."""
    global _mcp_service
    _mcp_service = service


# ── Hook ────────────────────────────────────────────────────────────────


@dataclass
class MCPToolInvokerHook:
    """Declarative MCP tool invocation as a step hook.

    Configured via the workflow YAML's `hooks.before_step` block:

        hooks:
          before_step:
            - name: mcp_tool_invoker
              config:
                server_id: filesystem-local
                tool_name: read_file
                store_as: file_contents
                params_from:
                  path: "seed.target_path"
    """

    server_id: str
    tool_name: str
    store_as: str
    params_from: Optional[Dict[str, str]] = None
    for_each: Optional[str] = None
    param_template: Optional[Dict[str, str]] = None
    # Step / region / workflow — passed through to MCPService so the runner
    # pool knows whether to keep the runner warm across the step boundary.
    scope: str = "workflow"

    name: str = field(default="mcp_tool_invoker")
    stage: str = field(default="before_step")

    def __call__(self, ctx: HookContext) -> HookResult:
        try:
            context = ctx.workflow.context if ctx.workflow is not None else None
            if context is None:
                raise RuntimeError("mcp_tool_invoker: no workflow context available")

            # Idempotency — before_step is dispatched twice (Phase 4.2 split).
            # Skip the re-invocation if we've already populated the workspace
            # key for this step.
            if context.get_workspace(ctx.step.id, self.store_as) is not None:
                return HookResult(action="continue")

            service = _get_mcp_service()
            run_id = self._resolve_run_id(ctx)

            if self.for_each:
                items = context.resolve_input(self.for_each)
                if items is None:
                    raise RuntimeError(
                        f"mcp_tool_invoker: for_each ref '{self.for_each}' resolved to None"
                    )
                if not isinstance(items, list):
                    raise RuntimeError(
                        f"mcp_tool_invoker: for_each ref '{self.for_each}' is "
                        f"not a list (got {type(items).__name__})"
                    )

                results: List[Any] = []
                template = self.param_template or {}
                for idx, item in enumerate(items):
                    params = _substitute_item(template, item)
                    if not isinstance(params, dict):
                        raise RuntimeError(
                            f"mcp_tool_invoker: param_template did not resolve "
                            f"to a dict at index {idx}"
                        )
                    result = self._call_with_instrumentation(
                        ctx, service, params, run_id
                    )
                    results.append(result)
                payload: Any = results
            else:
                params_from = self.params_from or {}
                params: Dict[str, Any] = {}
                for param_name, ref in params_from.items():
                    params[param_name] = context.resolve_input(ref)
                payload = self._call_with_instrumentation(ctx, service, params, run_id)

            context.set_workspace(ctx.step.id, self.store_as, payload)
            return HookResult(action="continue")

        except Exception as e:
            logger.error(
                f"mcp_tool_invoker failed (server={self.server_id} "
                f"tool={self.tool_name} step={getattr(ctx.step, 'id', '?')}): {e}"
            )
            return HookResult(action="fail", feedback=str(e))

    # ── instrumentation helpers ────────────────────────────────────────

    def _resolve_run_id(self, ctx: HookContext) -> Optional[str]:
        """Best-effort run_id pluck so the call routes through the runner pool
        (Phase 2). When ``ctx.workflow`` is a real ``WorkflowRun``, this gives
        us the in-flight run id; for tests / workflow-stage hooks where it's
        a duck-typed namespace, fall back to None (cold path)."""
        wf = ctx.workflow
        return getattr(wf, "run_id", None) if wf is not None else None

    def _call_with_instrumentation(
        self,
        ctx: HookContext,
        service: Any,
        params: Dict[str, Any],
        run_id: Optional[str],
    ) -> Any:
        """Time one ``MCPService.invoke_tool`` call, record an ``MCPCall`` on
        the step result. Errors bubble up after recording so the existing
        try/except in ``__call__`` converts the hook to a fail result.

        Status mapping:
          - successful response          → status="ok"
          - TimeoutError                 → status="timeout"
          - anything else                → status="error" + error_message

        Request / response size fields are populated when the engine can
        cheaply measure them (json.dumps overhead is negligible here); the
        operator can ratio response_size against duration to spot 20 MB
        round-trips in long-running RAG flows.
        """
        request_size = _json_size(params)
        t0 = time.monotonic()
        try:
            result = service.invoke_tool(
                self.server_id,
                self.tool_name,
                params,
                run_id=run_id,
                scope=self.scope,
            )
            duration_ms = (time.monotonic() - t0) * 1000.0
            self._record_call(
                ctx,
                duration_ms,
                status="ok",
                request_size_bytes=request_size,
                response_size_bytes=_json_size(result),
            )
            return result
        except TimeoutError as exc:
            duration_ms = (time.monotonic() - t0) * 1000.0
            self._record_call(
                ctx,
                duration_ms,
                status="timeout",
                request_size_bytes=request_size,
                error_message=str(exc),
            )
            raise
        except Exception as exc:
            duration_ms = (time.monotonic() - t0) * 1000.0
            self._record_call(
                ctx,
                duration_ms,
                status="error",
                request_size_bytes=request_size,
                error_message=str(exc),
            )
            raise

    def _record_call(
        self,
        ctx: HookContext,
        duration_ms: float,
        *,
        status: str,
        request_size_bytes: int = 0,
        response_size_bytes: int = 0,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """Append an MCPCall record onto the step result; no-op when the
        result handle isn't attached (legacy callers, workflow-stage hooks)."""
        result = getattr(ctx, "step_result", None)
        if result is None:
            return
        try:
            from api.models.workflow_models import MCPCall

            result.mcp_calls.append(
                MCPCall(
                    server_id=self.server_id,
                    tool_name=self.tool_name,
                    duration_ms=round(duration_ms, 3),
                    status=status,  # type: ignore[arg-type]
                    request_size_bytes=request_size_bytes,
                    response_size_bytes=response_size_bytes,
                    error_code=error_code,
                    error_message=error_message,
                )
            )
            result.extension_overhead_ms = round(
                result.extension_overhead_ms + duration_ms, 3
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"mcp_tool_invoker: instrumentation skipped: {exc}")


def _json_size(obj: Any) -> int:
    """Cheap payload size in bytes — ``len(json.dumps())`` with a defensive
    fallback. Used for MCPCall.request_size_bytes / response_size_bytes."""
    import json

    try:
        return len(json.dumps(obj, default=str))
    except Exception:  # noqa: BLE001
        return 0
