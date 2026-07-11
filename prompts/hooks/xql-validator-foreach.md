---
stage: before_step
target: plugin_tool_invoker
config:
  plugin_id: xdm-toolkit
  tool_id: validate_xql
  for_each: write_rules.rules
  param_template:
    rule: "{{ item.rule }}"
  store_as: validator_reports
tags: [xql, xsiam, validator, fan-out]
intended_output: "Per-rule validator reports for a batch of XQL rules"
---

# XQL validator fan-out

Runs the xdm-toolkit `validate_xql` tool once per item of an upstream list
output (`for_each` + `param_template` — `{{ item.* }}` substitutes each
element), collecting the reports in the workspace as `validator_reports`.
Point `for_each` at the producing step's list ref before attaching.

Derived from the shipped `workflows/xdm-bulk-onboarding.yaml` batch-validate
step.
