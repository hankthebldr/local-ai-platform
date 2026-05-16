# Trend Micro Vision One Detections -- XDM Data Model Rule Documentation

Companion notes for `trend_micro_vision_one_detections_xdm_model_rule.xql`.

## Anchors

This pack consumes two of the three anchors written by the shared
Vision One parser at
`PRIVATE_DOCS/packs/trend_micro_vision_one_detections/parser.xql`. See
`PRIVATE_DOCS/anchor_field_design.md` for the underlying concept.

| Anchor           | Vocabulary                                                | Purpose                                                |
|------------------|-----------------------------------------------------------|--------------------------------------------------------|
| `_source`        | open; canonical: `workbenchAlert` (legacy alias `detections`), plus sibling feeds `endpointActivityData`, `messageActivityData`, `networkActivityData`, `containerActivityData` | Discriminates this MODEL from sibling Vision One feeds |
| `_severity_band` | closed: `CRITICAL` / `HIGH` / `MEDIUM` / `LOW` (NULL on info) | Drives severity filters; feeds `xdm.alert.severity`    |

This MODEL's filter accepts both `workbenchAlert` (the canonical
ath-detections feed name) and `detections` (the legacy alias seen in
earlier ingest); the two are treated as synonyms.

The parser also stamps `_event_category` (six-value endpoint-activity
sub-shape discriminator) which is consumed only by the sibling
endpoint-activity MODEL and is NULL on detection rows.

## Relationship to parser

Both anchors consumed here are re-derived inside this MODEL using the
keep-in-both convention from `PRIVATE_DOCS/anchor_field_design.md`:

```
_source        = coalesce(_source,        source)
_severity_band = coalesce(_severity_band, <if-chain over detail.filterRiskLevel>)
```

On parser-stamped rows the MODEL pays one column read and a `coalesce`
short-circuit; on un-stamped rows (legacy ingest, replayed samples,
backfills) the same expression the MODEL would have run anyway is
evaluated. The MODEL is therefore backfill-safe and the parser is
purely additive.

## Scope

Maps Trend Micro Vision One detection events
(`source in ("workbenchAlert", "detections")`) to the Cortex XDM
schema. `workbenchAlert` is the canonical ath-detections value;
`detections` is a legacy alias seen in earlier ingest and is treated
as a synonym. Covers endpoint malware detections from Server &
Workload Protection, Apex One, and other Vision One connected
products.

Detection data resides primarily in the `detail{}` JSON object, with
supplementary MITRE ATT&CK metadata in the `filters[]` array. Process
details are available both in direct `detail` fields and in the
`processChainInfo[]` array of JSON strings; direct fields take
priority.

## Severity

Taken from `detail.filterRiskLevel`, the vendor-provided aggregate
(highest) severity across all matched filters. Individual per-filter
`riskLevel` values in `filters[]` are not used. The value is normalised
to proper case: `Informational`, `Low`, `Medium`, `High`, `Critical`.

## References

- Trend Micro Vision One Public API v3.0: `ath-detections`
- XDM schema: https://docs-cortex.paloaltonetworks.com/r/Cortex-XDM/XDM-Reference

## XDM field mapping summary (47 fields)

### Observer

- `xdm.observer.vendor` = `"Trend Micro"`
- `xdm.observer.product` = `"Vision One"`
- `xdm.observer.type` = `coalesce(detail.pname, detail.mpname)`
- `xdm.observer.version` = `detail.mpver`
- `xdm.observer.content_version` = `detail.patVer`
- `xdm.observer.unique_identifier` = `detail.mDeviceGUID`
- `xdm.observer.action` = composite action result string

### Event

- `xdm.event.id` = `uuid`
- `xdm.event.type` = `"ALERT"`
- `xdm.event.original_event_type` = `_source` (`"workbenchAlert"` / legacy `"detections"`)
- `xdm.event.description` = `detail.eventName`
- `xdm.event.operation_sub_type` = `detail.engineOperation`
- `xdm.event.log_level` = `detail.severity` mapped to `XDM_CONST.LOG_LEVEL_*`
- `xdm.event.outcome` = action result mapped to `XDM_CONST.OUTCOME_*`
- `xdm.event.outcome_reason` = composite action result string

### Alert

- `xdm.alert.original_alert_id` = `uuid`
- `xdm.alert.name` = `filters[].name` (joined)
- `xdm.alert.description` = `filters[].description` (joined)
- `xdm.alert.severity` = `coalesce(_severity_band -> proper-case, filterRiskLevel = "info" -> "Informational", filterRiskLevel verbatim)`. The `_severity_band` anchor (`CRITICAL` / `HIGH` / `MEDIUM` / `LOW`) is the preferred source; `Informational` and any non-closed-set vendor value still come from the legacy `filterRiskLevel` arm.
- `xdm.alert.category` = `detail.eventName`
- `xdm.alert.subcategory` = `detail.malType`
- `xdm.alert.original_threat_name` = `detail.malName`
- `xdm.alert.original_threat_id` = `detail.ruleIdStr`
- `xdm.alert.mitre_tactics` = `filters[].mitreTacticIds` mapped to `XDM_CONST.MITRE_TACTIC_*`

### Source (process / user that triggered the detection)

- `xdm.source.ipv4` = first IPv4 from `endpointIp[]`
- `xdm.source.port` = `detail.spt`
- `xdm.source.user.username` = `processChainInfo[0].process_user`
- `xdm.source.user.domain` = `processChainInfo[0].process_user_domain`
- `xdm.source.user.identifier` = `detail.senderGUID`
- `xdm.source.user_agent` = `detail.requestClientApplication`
- `xdm.source.host.hostname` = `detail.endpointHostName`
- `xdm.source.host.device_id` = `detail.endpointGUID`
- `xdm.source.host.ipv4_addresses` = `detail.endpointIp[]`
- `xdm.source.host.mac_addresses` = `detail.endpointMacAddress`
- `xdm.source.process.name` = `coalesce(detail, processChainInfo[0])`
- `xdm.source.process.pid` = `coalesce(detail, processChainInfo[0])`
- `xdm.source.process.command_line` = `coalesce(detail, processChainInfo[0])`
- `xdm.source.process.executable.path` = `coalesce(detail, processChainInfo[0])`
- `xdm.source.process.executable.sha256` = `coalesce(detail, processChainInfo[0])`
- `xdm.source.process.executable.md5` = `coalesce(detail, processChainInfo[0])`
- `xdm.source.process.executable.signer` = `coalesce(detail, processChainInfo[0])`
- `xdm.source.process.executable.size` = `processChainInfo[0].process_file_size`
- `xdm.source.process.integrity_level` = `processChainInfo[0].integrity_level`

### Target (detected file or object)

- `xdm.target.ipv4` = `detail.dst`
- `xdm.target.port` = `detail.dpt`
- `xdm.target.host.hostname` = `detail.dhost`
- `xdm.target.file.filename` = `coalesce(objectFileName, objectName)`
- `xdm.target.file.path` = `coalesce(objectFilePath, filePathName)`
- `xdm.target.file.directory` = `detail.filePath`
- `xdm.target.file.sha256` = `detail.objectFileHashSha256`
- `xdm.target.file.md5` = `detail.objectFileHashMd5`
- `xdm.target.file.size` = `detail.objectFileSize`

### Network

- `xdm.network.application_protocol` = `detail.app`
- `xdm.network.application_protocol_category` = `detail.appGroup`
- `xdm.network.http.url` = `detail.request`
- `xdm.network.http.referrer` = `detail.httpReferer`

### Session

- `xdm.session_context_id` = `uuid`

## Excluded fields

- `xdm.alert.mitre_techniques` -- causes Cortex IDE internal validation error on `_gc_raw` datasets. The `arraymap()` + `XDM_CONST.MITRE_TECHNIQUE_*` chain crashes the validator.
