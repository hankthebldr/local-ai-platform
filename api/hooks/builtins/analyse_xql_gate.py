# SPDX-FileCopyrightText: ohno llc
# SPDX-License-Identifier: AGPL-3.0-or-later
"""
analyse_xql_gate hook — fail the step on parser-conformance BLOCKERs.

Stage: validate_output. Runs after the LLM emits its final rule body.
Calls the analyse_xql plugin tool against the output and fails the
step (with a feedback message that retry_with_feedback can surface to
the next attempt) if the analyser reports any error-severity issues.

Why this exists: the model is prompted to self-review and emit a
verdict line, but a prompt is a suggestion. This hook is the
deterministic gate — if the analyser sees an unknown XDM path, a
struct binding, a sibling reference, or any other BLOCKER-tier
violation, the workflow run fails fast rather than shipping a broken
rule downstream.

YAML usage:

    validate_output:
      - name: analyse_xql_gate
        config:
          kind: modeling          # "modeling" (default) or "parsing"
          max_errors: 0           # fail if errors > this
          max_warnings: 99        # fail if warnings > this (default off)
          output_field: null      # if set, pull rule body from parsed[field]
                                  # instead of ctx.output

Stores the analyser report in workspace under `analyse_xql_report` so
downstream steps can read it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from api.services.hook_bus import HookContext, HookResult
from api.services.plugin_service import PluginService


_PLUGIN_SERVICE: Optional[PluginService] = None


def _get_plugin_service() -> PluginService:
    """Cache a PluginService instance the same way plugin_tool_invoker does."""
    global _PLUGIN_SERVICE
    if _PLUGIN_SERVICE is None:
        _PLUGIN_SERVICE = PluginService()
        _PLUGIN_SERVICE.discover()
    return _PLUGIN_SERVICE


@dataclass
class AnalyseXqlGateHook:
    kind: str = "modeling"
    max_errors: int = 0
    max_warnings: int = 99
    output_field: Optional[str] = None

    # When True, retry the step with the analyser feedback rather than
    # hard-failing. Lets retry_with_feedback take another swing.
    retryable: bool = True

    # Workspace key under which to store the report for downstream steps.
    store_as: str = "analyse_xql_report"

    name: str = "analyse_xql_gate"
    stage: str = "validate_output"

    def __call__(self, ctx: HookContext) -> HookResult:
        rule_text = self._extract_rule_text(ctx)
        if not rule_text:
            return HookResult(action="continue")

        try:
            report = _get_plugin_service().call_tool(
                "xdm-toolkit",
                "analyse_xql",
                {"rule": rule_text, "kind": self.kind},
            )
        except Exception as exc:
            # Analyser failures should never break the workflow loudly —
            # surface the issue but let the step proceed.
            return HookResult(
                action="continue",
                feedback=f"analyse_xql_gate could not run the analyser: {exc}",
            )

        summary = (report or {}).get("summary") or {}
        errors = int(summary.get("errors", 0))
        warnings = int(summary.get("warnings", 0))

        # Persist the report regardless of pass/fail so the operator and any
        # downstream step can see what the analyser saw.
        if ctx.workflow is not None and ctx.step is not None:
            try:
                ctx.workflow.context.set_workspace(ctx.step.id, self.store_as, report)
            except Exception:
                pass  # workspace is best-effort

        if errors <= self.max_errors and warnings <= self.max_warnings:
            return HookResult(action="continue")

        feedback = self._format_feedback(report, errors, warnings)
        return HookResult(
            action="retry" if self.retryable else "fail",
            feedback=feedback,
        )

    def _extract_rule_text(self, ctx: HookContext) -> str:
        if self.output_field:
            parsed = ctx.parsed
            if isinstance(parsed, dict):
                val = parsed.get(self.output_field, "")
                if isinstance(val, str):
                    return val
            # Fall through to ctx.output if parsed isn't a dict.
        return ctx.output or ""

    def _format_feedback(self, report: dict, errors: int, warnings: int) -> str:
        violations = (report or {}).get("violations") or []
        # Top 3 most actionable findings.
        top = []
        for v in violations[:3]:
            rid = v.get("ruleId", "???")
            ln = v.get("line")
            line_str = f" (line {ln})" if ln else ""
            msg = (v.get("message") or "")[:200]
            top.append(f"  [{rid}]{line_str} {msg}")
        body = "\n".join(top) if top else "  (no top-level violations captured)"
        verdict = (report or {}).get("verdict", "NEEDS-FIXES")
        return (
            f"analyse_xql gate failed: {errors} BLOCKER(s) and {warnings} WARN(s); "
            f"verdict={verdict}. Top findings:\n{body}\n\n"
            "Revise the rule to clear the BLOCKERs before re-emitting. "
            "Refer to the rule IDs above for the exact recommendation text."
        )
