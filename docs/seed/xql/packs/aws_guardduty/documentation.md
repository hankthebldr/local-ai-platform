# AWS GuardDuty -- XDM Data Model Rule Documentation

Companion notes for `aws_guardduty_xdm_model_rule.xql`.

## Scope

Maps AWS GuardDuty finding events to the Cortex XDM (Cross Data Model) schema.
Covers all six GuardDuty action types: `AWS_API_CALL`, `NETWORK_CONNECTION`,
`DNS_REQUEST`, `KUBERNETES_API_CALL`, `PORT_PROBE`, `RDS_LOGIN_ATTEMPT`, plus
actionless findings (`AttackSequence`, `MalwareProtection`).

A defensive `coalesce(PascalCase, camelCase)` pattern is used throughout to
handle both field naming conventions emitted by the XSIAM parser.

## Validation corpus

Validated against 397 production sample events spanning 17 resource types,
6 action types, and 4 severity bands. Username coverage: 266/397 rows
(`RuntimeDetails.Process.User` and `AccessKeyDetails.UserName` sources).
`RuntimeDetails.Context` provides target process, module, tool, and threat
metadata for Runtime Monitoring findings (105 rows with context data).

## References

- GuardDuty API: https://docs.aws.amazon.com/guardduty/latest/APIReference/
- XDM schema: https://docs-cortex.paloaltonetworks.com/r/Cortex-XDM/XDM-Reference

## Query truncation note

The generic `| fields xdm.*` query truncates output at ~55 columns
(alphabetical cutoff at `xdm.source.host.ipv4_addresses`). To validate
`source.user.*`, `source.process.*`, and `target.*` fields, list explicit
field names in the query, e.g.:

```
datamodel dataset = aws_guardduty_generic_alert_raw
| fields xdm.source.user.username, xdm.source.process.name, ...
```

## Alert field mapping

Maps high-level XSIAM alert field names to XDM paths populated by this rule.
Used for alert layout configuration in Cortex XSIAM.

Directionality key (NETWORK_CONNECTION findings only):
- `INBOUND`: source = remote attacker, target = local resource
- `OUTBOUND`: source = local resource, target = remote destination
- Non-network findings: source = the actor/caller, target = the resource

| Alert field                | XDM mapping |
| -------------------------- | ----------- |
| Remote Host                | `xdm.target.ipv4` (OUTBOUND), `xdm.source.ipv4` (INBOUND / API call / K8s / RDS) |
| File name                  | NOT MAPPED (GuardDuty findings report threat names but not individual file paths) |
| File SHA256                | NOT MAPPED (GuardDuty findings do not include per-file hashes) |
| Local IP                   | `xdm.source.ipv4` (OUTBOUND), `xdm.target.ipv4` (INBOUND) |
| Target process CMD         | NOT MAPPED (GuardDuty `RuntimeDetails` provides `Name` and `ExecutablePath` but no command-line arguments) |
| Target process SHA256      | `xdm.source.process.executable.sha256` (initiator), `xdm.target.process.executable.sha256` (injection/escape target from `RuntimeDetails.Context`) |
| Process execution signature| NOT MAPPED (no code signing info from GuardDuty) |
| Process execution signer   | NOT MAPPED (no code signing info from GuardDuty) |
| Remote IP                  | `xdm.source.ipv4` (INBOUND / API call / K8s / RDS), `xdm.target.ipv4` (OUTBOUND) |
| Remote Port                | `xdm.source.port` (INBOUND), `xdm.target.port` (OUTBOUND) |
| User name                  | `xdm.source.user.username` (coalesce: RDS login user, `RuntimeDetails.Process.User`, `RuntimeDetails.Context.TargetProcess.User`, `AccessKeyDetails.UserName`, K8s user, K8s service account) |
| Initiator CMD              | NOT MAPPED (no command-line arguments in `RuntimeDetails`) |
| Initiated By               | `xdm.source.user.username`, `xdm.source.user.user_type` |
| Initiator path             | `xdm.source.process.executable.path` |
| Initiator SHA256           | `xdm.source.process.executable.sha256` |
| Initiator signature        | NOT MAPPED |
| Initiator signer           | NOT MAPPED |
| Host Name                  | `xdm.source.host.hostname` (the affected EC2 instance ID) |
| Host IP                    | `xdm.source.host.ipv4_addresses`, `xdm.source.host.ipv6_addresses` |
| Host OS                    | NOT MAPPED |
| Event ID                   | `xdm.event.id` (`finding_id` from `coalesce(Id, id)` -- the GuardDuty finding ID, critical for correlation) |
| Event Type                 | `xdm.event.type`, `xdm.event.operation_sub_type`, `xdm.alert.subcategory` |
| Event Description          | `xdm.event.description` (GuardDuty finding description) |
| Domain                     | `xdm.network.dns.dns_question.name`, `xdm.source.user.domain` |
| URL                        | `xdm.network.http.url` |
| Target process name        | `xdm.source.process.name` (initiator), `xdm.target.process.name` (injection/escape target from `RuntimeDetails.Context`) |
| Detection Feature          | `xdm.event.original_event_type`, `xdm.observer.type` (RuntimeMonitoring, EbsMalwareProtection, etc.) |
| Resource Role              | `xdm.observer.action` (TARGET or ACTOR) |
| Tool Name                  | `xdm.source.application.name` (suspicious tool from `RuntimeDetails.Context`) |

## Runtime context fields (Runtime Monitoring)

| Source field                                               | Mapping |
| ---------------------------------------------------------- | ------- |
| `TargetProcess.User`                                       | `xdm.source.user.username` (fallback after `RuntimeDetails.Process.User`) |
| `TargetProcess.Name`/`ExecutablePath`/`Sha256`/`Pid`       | extracted as intermediary fields |
| `ModuleName`/`ModuleFilePath`/`ModuleSha256`               | extracted as intermediary fields |
| `ToolName`/`ToolCategory`                                  | `xdm.source.application.name` |
| `ThreatFilePath`/`ScriptPath`/`ServiceName`                | extracted as intermediary fields |
| `SocketPath`/`MountSource`/`MountTarget`                   | extracted as intermediary fields |
| `RuncBinaryPath`/`ReleaseAgentPath`                        | extracted as intermediary fields |

## Anchors

The pack ships with `parser.xql`, an `[INGEST:]` rule that stamps two
anchor columns on every row written into `aws_guardduty_generic_alert_raw`.
Anchors turn high-volume `_raw_log` regex / JSON-path filters into cheap
column-equality scans. See `PRIVATE_DOCS/anchor_field_design.md` for the
underlying concept and the "two anchors per dataset" guidance.

| Anchor            | Vocabulary                                                                                                                                  | Source                                                                                                                |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| `_action_type`    | `AWS_API_CALL`, `NETWORK_CONNECTION`, `DNS_REQUEST`, `KUBERNETES_API_CALL`, `PORT_PROBE`, `RDS_LOGIN_ATTEMPT`, `AttackSequence`, `MalwareProtection` | `Service.Action.ActionType` (six action-type families) plus a `Type` prefix branch (AttackSequence) and a `FeatureName` regex branch (MalwareProtection) for the two actionless families |
| `_severity_band`  | `LOW` (1.0-3.9), `MEDIUM` (4.0-6.9), `HIGH` (7.0-8.9)                                                                                       | `Severity` numeric float, bucketed; `>=9.0` (the Critical band introduced 2024) is intentionally left as NULL so analysts see "no bucket" instead of a misleading one |

Both extractions use the same defensive PascalCase / camelCase coalesce
the data-model rule uses, so a single anchor value covers both XSIAM
parser paths.

Typical analyst-side use:

```
dataset = aws_guardduty_generic_alert_raw
| filter _action_type = "RDS_LOGIN_ATTEMPT" and _severity_band = "HIGH"
| fields _time, finding_type, ...
```

## Relationship to parser

`datamodel.xql` and `parser.xql` ship as a single pack. The
keep-in-both convention from `PRIVATE_DOCS/anchor_field_design.md`
applies:

- `service_action_type` in `datamodel.xql` is now derived as
  `coalesce(_action_type, <existing PascalCase/camelCase coalesce>,
  <AttackSequence/MalwareProtection fallbacks>)`. Parser-stamped rows
  short-circuit through the column read; rows ingested before the
  parser shipped, replayed sample data, and backfills all continue to
  model identically because the original extraction stays in place.
- `finding_severity_band` in `datamodel.xql` is now derived as
  `coalesce(_severity_band, <bucketing if-chain over numeric Severity>)`.
  Parser-stamped rows short-circuit through the column read; legacy /
  replayed / backfilled rows fall through to the same bucketing logic
  the parser applies. `xdm.alert.severity` continues to be driven off
  the numeric `Severity` float directly (it carries its own four-band
  vocabulary including `Critical`); the bucketed string column exists
  for symmetry with the parser and for downstream consumers that want
  the closed-vocabulary form.

When either anchor is added or removed, both `parser.xql` and the
`coalesce()` site in `datamodel.xql` change in the same commit. The
keep-in-both convention is what makes anchors backfill-safe; it only
works if the two files stay in lock-step.

## Body stage notes

- Stage 2 extracts the per-finding action sub-objects under
  `Service.Action{}` (network connection, AWS API call, Kubernetes API call,
  RDS login attempt). Each finding type stores its action details under a
  different key.
  Reference: https://docs.aws.amazon.com/guardduty/latest/APIReference/API_Action.html
- Stage 5 resolves the source/target IP and port pair according to the
  network direction. For `INBOUND` connections the source is the remote
  endpoint and the target is the local endpoint; for `OUTBOUND` the
  assignment is reversed. Non-network action types treat the remote IP as
  the source.
