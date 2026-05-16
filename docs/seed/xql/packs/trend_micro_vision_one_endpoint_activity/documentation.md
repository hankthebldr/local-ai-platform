# Trend Micro Vision One Endpoint Activity -- XDM Data Model Rule Documentation

Companion notes for `trend_micro_vision_one_endpoint_activity_xdm_model_rule.xql`.

## Anchors

This pack consumes two of the three anchors written by the shared
Vision One parser, which lives at
`PRIVATE_DOCS/packs/trend_micro_vision_one_detections/parser.xql`
(one parser file serves both Vision One MODEL packs because they
share a single `target_dataset`). See
`PRIVATE_DOCS/anchor_field_design.md` for the underlying concept.

| Anchor             | Vocabulary                                                            | Purpose                                                  |
|--------------------|-----------------------------------------------------------------------|----------------------------------------------------------|
| `_source`          | open; this MODEL's value is `endpointActivityData`                    | Discriminates this MODEL from sibling Vision One feeds   |
| `_event_category`  | closed: `process` / `file` / `network` / `dns` / `registry` / `account` | Six-bucket sub-shape discriminator; feeds `xdm.alert.subcategory` |

`_event_category` is derived from `detail.eventId` (1..6); event ids
outside that closed set are NULL on the anchor and surfaced verbatim
through this MODEL's broader `event_category` derivation
(`INTERNET`, `WMI`, `MEMORY`, etc.) which feeds
`xdm.event.operation_sub_type`.

The parser also stamps `_severity_band` (CRITICAL / HIGH / MEDIUM /
LOW, lifted from `detail.filterRiskLevel`). This MODEL deliberately
does NOT consume it -- per Task #111 scope, only the sibling
detections MODEL consumes the severity-band anchor. Endpoint-activity
severity continues to flow from `detail.filterRiskLevel` directly.

## Relationship to parser

Both anchors consumed here are re-derived inside this MODEL using the
keep-in-both convention from `PRIVATE_DOCS/anchor_field_design.md`:

```
_source         = coalesce(_source,         source)
_event_category = coalesce(_event_category, <if-chain over detail.eventId 1..6>)
```

On parser-stamped rows the MODEL pays one column read and a `coalesce`
short-circuit per anchor; on un-stamped rows (legacy ingest, replayed
samples, backfills) the same expression the MODEL would have run
anyway is evaluated. The MODEL is therefore backfill-safe and the
parser is purely additive.

## Scope

Maps Trend Micro Vision One endpoint activity events
(`source = "endpointActivityData"`) to the Cortex XDM schema. Covers
process execution, file operations, network connections, DNS queries,
registry changes, and account events from the Endpoint Sensor (XES)
product.

## Process model

Endpoint activity data uses a three-tier process model:

| Tier      | Meaning |
| --------- | ------- |
| `object`  | The child / target process or file being acted upon |
| `process` | The launching / parent process that spawned the object |
| `parent`  | The grandparent process (no valid XDM mapping exists) |

All useful fields reside in the `detail{}` JSON object. Top-level
fields are largely null. MITRE ATT&CK metadata is in the `filters[]`
array. XSAE tags are in `detail.tags[]`.

## Severity

Taken from `detail.filterRiskLevel`, the vendor-provided aggregate
(highest) severity across all matched filters. Individual per-filter
`riskLevel` values in `filters[]` are not used. The value is normalised
to proper case: `Informational`, `Low`, `Medium`, `High`, `Critical`.

## References

- Trend Micro Vision One Public API v3.0: `ath-endpointActivityData`
- XDM schema: https://docs-cortex.paloaltonetworks.com/r/Cortex-XDM/XDM-Reference

## XDM field mapping summary (40 fields)

### Observer

- `xdm.observer.vendor` = `"Trend Micro"`
- `xdm.observer.product` = `"Vision One"`
- `xdm.observer.type` = `detail.pname`
- `xdm.observer.version` = `detail.pver`
- `xdm.observer.action` = `detail.filterRiskLevel`

### Event

- `xdm.event.id` = `uuid`
- `xdm.event.type` = `"ENDPOINT_ACTIVITY"`
- `xdm.event.original_event_type` = `source` (`"endpointActivityData"`)
- `xdm.event.description` = `filters[0].name`
- `xdm.event.operation_sub_type` = `eventId`/`eventSubId` mapped to `"CATEGORY / ACTION"` string
- `xdm.event.log_level` = `filterRiskLevel` mapped to `XDM_CONST.LOG_LEVEL_*`

### Alert

- `xdm.alert.original_alert_id` = `uuid`
- `xdm.alert.name` = `filters[].name` (joined)
- `xdm.alert.description` = `filters[].description` (joined)
- `xdm.alert.severity` = `filterRiskLevel` (proper case). The `_severity_band` anchor exists in the parser but is intentionally not consumed by this MODEL (Task #111 scope: endpoint-activity keep-in-both is `_source` + `_event_category` only).
- `xdm.alert.subcategory` = `coalesce(detail.tags[] XSAE IDs, _event_category)`. XSAE tags win when present; the six-value `_event_category` anchor (`process` / `file` / `network` / `dns` / `registry` / `account`) fills in when no XSAE tag is attached.
- `xdm.alert.mitre_tactics` = `filters[].mitreTacticIds` mapped to `XDM_CONST.MITRE_TACTIC_*`

### Source (launching process and endpoint host)

- `xdm.source.ipv4` = first IPv4 from `endpointIp[]`
- `xdm.source.port` = `detail.spt`
- `xdm.source.application.name` = `detail.productCode`
- `xdm.source.user.username` = `coalesce(processUser, logonUser[0])`
- `xdm.source.user.domain` = `detail.userDomain[0]`
- `xdm.source.user.user_type` = derived from `logonUser` context
- `xdm.source.host.hostname` = `detail.endpointHostName`
- `xdm.source.host.device_id` = `detail.endpointGuid`
- `xdm.source.host.ipv4_addresses` = `endpointIp[]` (IPv4 only)
- `xdm.source.host.ipv6_addresses` = `endpointIp[]` (IPv6 only)
- `xdm.source.host.mac_addresses` = `detail.endpointMacAddress[]`
- `xdm.source.host.os` = `detail.osDescription`
- `xdm.source.host.os_family` = `detail.osName` mapped to `XDM_CONST.OS_FAMILY_*`
- `xdm.source.process.name` = `detail.processName`
- `xdm.source.process.pid` = `detail.processPid`
- `xdm.source.process.command_line` = `detail.processCmd`
- `xdm.source.process.executable.path` = `detail.processFilePath`
- `xdm.source.process.executable.sha256` = `detail.processFileHashSha256`
- `xdm.source.process.executable.md5` = `detail.processFileHashMd5`

### Target (child process, file, or resource being acted upon)

- `xdm.target.ipv4` = `coalesce(detail.dst, objectIp)`
- `xdm.target.port` = `coalesce(detail.dpt, objectPort)`
- `xdm.target.host.hostname` = `detail.objectHostName`
- `xdm.target.process.name` = `detail.objectName`
- `xdm.target.process.pid` = `detail.objectPid`
- `xdm.target.process.command_line` = `detail.objectCmd`
- `xdm.target.process.executable.path` = `detail.objectFilePath`
- `xdm.target.process.executable.sha256` = `detail.objectFileHashSha256`
- `xdm.target.process.executable.md5` = `detail.objectFileHashMd5`
- `xdm.target.user.username` = `detail.objectUser`

### Network

- `xdm.network.http.url` = `detail.request`
- `xdm.network.dns.dns_question.name` = `detail.objectName` (`eventId=4` only)

## Excluded fields

- `xdm.alert.mitre_techniques` -- causes Cortex IDE internal validation error on `_gc_raw` datasets. The `arraymap()` + `XDM_CONST.MITRE_TECHNIQUE_*` chain crashes the validator.
- `xdm.target.process.integrity_level` -- causes Cortex IDE internal validation error on `_gc_raw` datasets. The `if()` chain with `XDM_CONST.INTEGRITY_LEVEL_*` constants crashes the validator.
- `xdm.session_context_id` -- causes internal error on `_gc_raw` datasets. Field exists in the XDM schema but is not part of the selected data model for this dataset.
- `xdm.source.process.parent_process.*` -- these fields (name, pid, command_line) do not exist in the XDM schema at all. Grandparent process data (`parentName`, `parentCmd`, `parentPid`) cannot be mapped to any valid XDM field path.
