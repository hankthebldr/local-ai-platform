"""
plugin_tool_invoker hook — invokes a plugin tool and stores the result in the
step's workspace BEFORE input resolution.

Stage: before_step.

Two modes:

1. Single-shot (default): resolve each value in `params_from` against the
   workflow context, call the tool once, store the dict result.

2. Iterating (`for_each` set): resolve a list, substitute `{{ item.X }}`
   placeholders in `param_template` for each item, call the tool per item,
   and store the list of results.

The result is written to `ctx.workflow.context.workspace[step.id][store_as]`,
which means a step can reference `<step_id>.<store_as>` as one of its own
inputs.  The workflow validator is aware of this and treats the hook-provided
key as available.
"""

from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from api.logging_config import logger
from api.services.hook_bus import HookContext, HookResult


# ── Shared PluginService singleton ────────────────────────────────────────────
#
# Lazily scan plugins on first use.  Tests can override by injecting a custom
# service instance with `set_plugin_service()`.

_service_lock = threading.Lock()
_plugin_service: Any = None


def _get_plugin_service():
    global _plugin_service
    if _plugin_service is not None:
        return _plugin_service
    with _service_lock:
        if _plugin_service is None:
            from api.services.plugin_service import PluginService

            svc = PluginService(plugins_dir=os.getenv("PLUGINS_DIR", "plugins"))
            try:
                svc.scan_plugins()
            except Exception as e:
                logger.warning(f"plugin_tool_invoker: initial scan failed: {e}")
            _plugin_service = svc
    return _plugin_service


def set_plugin_service(service) -> None:
    """Override the module-level plugin service. Intended for tests."""
    global _plugin_service
    _plugin_service = service


# ── Item-template substitution ───────────────────────────────────────────────

_ITEM_PATTERN = re.compile(r"\{\{\s*item(?:\.([A-Za-z0-9_.]+))?\s*\}\}")


def _resolve_item_path(item: Any, path: Optional[str]) -> Any:
    """Walk a dotted path on a dict/object. `None` path returns the item itself."""
    if not path:
        return item
    current = item
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        else:
            current = getattr(current, part, None)
        if current is None:
            return None
    return current


def _substitute_item(template: Any, item: Any) -> Any:
    """Recursively substitute `{{ item.X }}` placeholders in strings."""
    if isinstance(template, str):
        # Whole-string single-token shortcut so we preserve non-string types
        m = _ITEM_PATTERN.fullmatch(template.strip())
        if m:
            return _resolve_item_path(item, m.group(1))

        def _replace(match: re.Match) -> str:
            val = _resolve_item_path(item, match.group(1))
            return "" if val is None else str(val)

        return _ITEM_PATTERN.sub(_replace, template)
    if isinstance(template, dict):
        return {k: _substitute_item(v, item) for k, v in template.items()}
    if isinstance(template, list):
        return [_substitute_item(v, item) for v in template]
    return template


# ── Hook ──────────────────────────────────────────────────────────────────────


@dataclass
class PluginToolInvokerHook:
    plugin_id: str
    tool_id: str
    store_as: str
    params_from: Optional[Dict[str, str]] = None
    for_each: Optional[str] = None
    param_template: Optional[Dict[str, str]] = None

    name: str = field(default="plugin_tool_invoker")
    stage: str = field(default="before_step")

    def __call__(self, ctx: HookContext) -> HookResult:
        try:
            context = ctx.workflow.context if ctx.workflow is not None else None
            if context is None:
                raise RuntimeError("plugin_tool_invoker: no workflow context available")

            # Idempotency — before_step may be dispatched twice (once before
            # input resolution to populate hook-provided inputs, then again
            # after compose for prompt-aware hooks). Skip the re-invocation
            # if we've already populated the workspace key for this step.
            if context.get_workspace(ctx.step.id, self.store_as) is not None:
                return HookResult(action="continue")

            service = _get_plugin_service()

            if self.for_each:
                items = context.resolve_input(self.for_each)
                if items is None:
                    raise RuntimeError(
                        f"plugin_tool_invoker: for_each ref '{self.for_each}' resolved to None"
                    )
                if not isinstance(items, list):
                    raise RuntimeError(
                        f"plugin_tool_invoker: for_each ref '{self.for_each}' is "
                        f"not a list (got {type(items).__name__})"
                    )

                results: List[Any] = []
                template = self.param_template or {}
                for idx, item in enumerate(items):
                    params = _substitute_item(template, item)
                    if not isinstance(params, dict):
                        raise RuntimeError(
                            f"plugin_tool_invoker: param_template did not resolve "
                            f"to a dict at index {idx}"
                        )
                    result = self._call_with_instrumentation(ctx, service, params)
                    results.append(result)
                payload: Any = results
            else:
                params_from = self.params_from or {}
                params: Dict[str, Any] = {}
                for param_name, ref in params_from.items():
                    params[param_name] = context.resolve_input(ref)
                payload = self._call_with_instrumentation(ctx, service, params)

            context.set_workspace(ctx.step.id, self.store_as, payload)
            return HookResult(action="continue")

        except Exception as e:
            logger.error(
                f"plugin_tool_invoker failed (plugin={self.plugin_id} "
                f"tool={self.tool_id} step={getattr(ctx.step, 'id', '?')}): {e}"
            )
            return HookResult(action="fail", feedback=str(e))

    def _call_with_instrumentation(
        self, ctx: HookContext, service: Any, params: Dict[str, Any]
    ) -> Any:
        """Time one ``service.call_tool`` invocation and record a
        ``PluginToolCall`` on the step result.

        Phase 4.2 — extension instrumentation. The record is only written
        when ``ctx.step_result`` is present (step_executor passes it on
        every dispatch; workflow-stage callers may not). Errors are
        captured as ``status="error"`` records so a failed tool still
        shows up on the dashboard, then re-raised so the existing
        try/except in __call__ converts the hook to a fail result.
        """
        import time

        t0 = time.monotonic()
        try:
            result = service.call_tool(self.plugin_id, self.tool_id, params)
            duration_ms = (time.monotonic() - t0) * 1000.0
            self._record_call(ctx, duration_ms, status="ok")
            try:
                from api.hooks.builtins.mcp_tool_invoker import _emit_tool_called

                run_id = getattr(getattr(ctx, "workflow", None), "run_id", None) or ""
                _emit_tool_called(
                    run_id=run_id,
                    step_id=getattr(ctx.step, "id", ""),
                    tool=self.tool_id,
                    server=self.plugin_id,
                    status="ok",
                )
            except Exception:
                pass
            return result
        except Exception as exc:
            duration_ms = (time.monotonic() - t0) * 1000.0
            self._record_call(
                ctx,
                duration_ms,
                status="error",
                error_class=type(exc).__name__,
            )
            raise

    def _record_call(
        self,
        ctx: HookContext,
        duration_ms: float,
        *,
        status: str,
        error_class: Optional[str] = None,
    ) -> None:
        """Append a PluginToolCall record onto the step result, no-op when the
        result handle isn't attached (legacy callers, workflow-stage hooks)."""
        result = getattr(ctx, "step_result", None)
        if result is None:
            return
        try:
            from api.models.workflow_models import PluginToolCall

            result.plugin_tools_called.append(
                PluginToolCall(
                    plugin_id=self.plugin_id,
                    tool_id=self.tool_id,
                    duration_ms=round(duration_ms, 3),
                    status=status,  # type: ignore[arg-type]
                    error_class=error_class,
                )
            )
            result.extension_overhead_ms = round(
                result.extension_overhead_ms + duration_ms, 3
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"plugin_tool_invoker: instrumentation skipped: {exc}")
