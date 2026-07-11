---
stage: validate_output
target: analyse_xql_gate
config:
  kind: modeling
  max_errors: 0
  max_warnings: 99
  retryable: true
  store_as: datamodel_analysis_report
tags: [xql, xsiam, quality-gate, modeling]
intended_output: "Validated XDM data-model rule (zero blockers)"
---

# XQL modeling gate

Validates a step's XDM MODEL-block output against the 82-rule analyse_xql
engine (modeling kind). Any BLOCKER triggers a retry carrying the analyser's
rule-ID + recommendation feedback; the report lands in the step workspace as
`datamodel_analysis_report`.

Derived from the shipped `workflows/xdm-vendor-pack.yaml` datamodel step and
`workflows/xdm-rule-from-log.yaml` review step — attach on any step that
emits `datamodel.xql` content.
