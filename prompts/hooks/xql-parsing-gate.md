---
stage: validate_output
target: analyse_xql_gate
config:
  kind: parsing
  max_errors: 0
  max_warnings: 99
  retryable: true
  store_as: parser_analysis_report
tags: [xql, xsiam, quality-gate, parsing]
intended_output: "Validated XQL parsing rule (zero blockers)"
---

# XQL parsing gate

Validates a step's XQL parsing-rule output against the 82-rule analyse_xql
engine (parsing kind) and retries with structured feedback on any BLOCKER.
The full report is stored in the step workspace as
`parser_analysis_report` for downstream steps.

Derived from the shipped `workflows/xdm-vendor-pack.yaml` parser step —
attach on the step that emits `parser.xql` content.
