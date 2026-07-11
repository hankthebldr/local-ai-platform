---
stage: before_step
target: plugin_tool_invoker
config:
  plugin_id: xdm-toolkit
  tool_id: validate_xql
  params_from:
    rule: write_rule.rule
  store_as: validator_report
tags: [xql, xsiam, validator, pre-step]
intended_output: "Structured validator report injected into the step input"
---

# XQL validator pre-step

Runs the xdm-toolkit `validate_xql` tool against an upstream step's rule
BEFORE this step executes, storing the structured report in the workspace as
`validator_report` so the LLM sees rule-ID + recommendation feedback rather
than generic prose. Adjust `params_from` to point at your producing step's
output ref.

Derived from the shipped `workflows/xdm-rule-from-log.yaml` review step.
