# Symantec Endpoint Protection -- Pack documentation

Companion notes for the SEP pack -- `parser.xql` and `datamodel.xql`.

## Anchors

`parser.xql` stamps two anchor columns on every row that matches
`SymantecServer:`, plus the canonical `_time` from the syslog
header. See `PRIVATE_DOCS/anchor_field_design.md` for the underlying
concept and `PRIVATE_DOCS/cortex_xsiam_authoring_rules.md` rules
21-30 for the keep-in-both convention.

| Anchor          | Cardinality | Values                                                                                                               |
|-----------------|-------------|----------------------------------------------------------------------------------------------------------------------|
| `_sep_category` | 10          | `AntiVirus`, `IPS`, `DeviceControl`, `ApplicationControl`, `Auth`, `Policy`, `Tamper`, `System`, `Firewall`, `BehaviorMonitoring` |
| `_severity`     | 4           | `Info`, `Warning`, `Major`, `Critical`                                                                               |

`_sep_category` is finer-grained than the legacy `_subtype`
discriminator that is still used inside `datamodel.xql` to fan out
on the five sub-shapes (`RISK` / `IPS` / `BEHAVIOR` / `TRAFFIC` /
`SYSTEM`). The anchor splits the SYSTEM shape into
`DeviceControl` / `ApplicationControl` / `Auth` / `Policy` /
`Tamper` / `System` so analyst searches against `symantec_ep_raw`
can filter the sub-families on a single column-equality test
instead of regex-matching `_raw_log` on every row.

`_severity` is the SEP-native severity enum. The forwarder emits
the string `Severity:` token in some shapes (typically firewall /
IPS); when it does not, the anchor maps the numeric `Sensitivity:`
1-9 ladder to the four-bucket vocabulary (1-3 -> `Info`,
4-5 -> `Warning`, 6-7 -> `Major`, 8-9 -> `Critical`).

## Relationship to parser

`datamodel.xql` reads both anchors via the keep-in-both
convention -- the Stage 3.5 `alter` block calls
`coalesce(<column-from-parser>, <derivation-from-_raw_log>)` for
each anchor. Rows ingested before the parser shipped, replayed
sample data and any backfill all model identically because the
data-model rule independently re-derives the same values from
`_raw_log` when the parser-stamped column is NULL.

`xdm.alert.severity` is sunk as
`coalesce(_severity, _severity_band)`. The four-bucket SEP-native
enum is preferred when present; otherwise the rule falls back to
the legacy five-bucket `_severity_band` ladder
(`Critical` / `High` / `Medium` / `Low` / `Informational`)
so existing dashboards reading the legacy vocabulary continue to
see populated values. `xdm.alert.subcategory` is sunk as
`coalesce(_alert_subcategory, _sep_category)` so the anchor
populates the field when the per-subtype derivation is NULL.

## Scope

Maps Symantec Endpoint Protection (SEP) Manager-forwarded syslog events
to the Cortex XDM schema. SEP events arrive as syslog-wrapped delimited
strings (NOT JSON). The format varies by event sub-type but always uses
comma as the inter-field delimiter, with values formatted either
positionally or as `Key: Value` pairs.

## Sub-types handled

Five sub-types are routed and mapped in a single pipeline. Sub-type
detection is done by string discriminator with a strict ordering --
BEHAVIOR before TRAFFIC because both contain `Rule:`; RISK / IPS /
SYSTEM are identified by their own unique markers.

### RISK

`Potential risk found` reputation/heuristic malware detection AND
`Virus found` Auto-Protect / on-host antivirus detection. The two
malware shapes share the bulk of their grammar (Computer name,
IP Address, Risk name, File path, Application name/hash, Actual action,
Source/User context); a Stage-1 sibling `_risk_kind` discriminator pins
each record to `POTENTIAL` or `VIRUS` so Virus-only fields (Occurrences,
Requested / Secondary action, Event time / End Time, Disposition,
Category set, numeric Application type code, Certificate fields) can be
gated without re-pattern-matching the raw payload.

- Potential risk format:
  `SymantecServer: Potential risk found,Computer name: X,IP Address: Y,Detection type: Z,...`
- Virus format:
  `SymantecServer: Virus found,IP Address: X,Computer name: Y,Source: Auto-Protect scan,Risk name: WS.Malware.N,Occurrences: N,...`

Maps to `xdm.event.type = "ALERT"`.

### IPS

Network intrusion / IPS signature match.
Format: `...,Intrusion URL: ...` with Local/Remote Host fields and
CIDS Signature ID/string. Maps to `xdm.event.type = "ALERT"`.

### TRAFFIC

Firewall traffic policy match (no Action Type field).
Format: `...,Rule: ...` with Local/Remote Host fields and Action verb.
Distinguished from BEHAVIOR by the absence of an `Action Type:` token.
Maps to `xdm.event.type = "NETWORK"`.

### BEHAVIOR

SBP / behaviour-based detection.
Format: `...,Rule: ...,Action Type: ...` with process pid / name /
cmdline in positional form. Maps to `xdm.event.type = "ALERT"`.

### SYSTEM

SEPM audit / management server events.
Format:
`SymantecServer: Site: X,Server Name: Y,Domain Name: Z,<message>,<computer>,<user>,<userdomain>`.
Maps to `xdm.event.type = "AUDIT"`.

Reference: Broadcom KB TECH171741
(<https://knowledge.broadcom.com/external/article?legacyId=TECH171741>).

## Expected non-blocking validator findings

These are deliberate and should not be actioned:

- `INFO-006` -- Heavy in-line documentation. The retained comments are
  intentional for auditability and to record the rationale behind every
  per-subtype derivation; this raises maintenance signal-to-noise but is
  by design.
- `WARN-023` -- Some `xdm.*` sinks are populated only for a subset of
  sub-types (e.g. `xdm.network.*` is only set when subtype in
  IPS / TRAFFIC / BEHAVIOR). This is correct: SYSTEM and pure RISK
  events do not carry network context and leaving those sinks null is
  the canonical XDM idiom.

## XDM field mapping summary

### Observer

- `xdm.observer.vendor` = `"Symantec"`
- `xdm.observer.product` = `"Endpoint Protection"`
- `xdm.observer.name` = Server Name (or syslog hostname)
- `xdm.observer.action` = canonical `XDM_CONST.OUTCOME_*` value derived
  from `Actual action` / `Action` / `Action Type` (raw vendor verb is
  kept in `xdm.event.outcome_reason`)

### Event

- `xdm.event.type` = `"ALERT"` (RISK, IPS, BEHAVIOR) | `"NETWORK"`
  (TRAFFIC) | `"AUDIT"` (SYSTEM)
- `xdm.event.original_event_type` = `"Potential risk found"` |
  `"Virus found"` | `"Intrusion"` | `"Network Traffic"` |
  `"Behavioral Detection"` | `"System"`
- `xdm.event.description` = Source / Description / Event Type /
  Action Type / system message. For VIRUS records, `Occurrences: N`,
  `Event time: ...` and `End Time: ...` are appended (each suffix is
  omitted independently when the underlying field is null) because the
  Cortex schema reference does not expose canonical
  `xdm.event.event_count` / `xdm.event.start_time` /
  `xdm.event.end_time` sinks for this dataset (see "Not mapped" below).
- `xdm.event.log_level` = mapped from Sensitivity ladder (or VIRUS
  Disposition arm) to `XDM_CONST.LOG_LEVEL_*`.
- `xdm.event.outcome` = action verb mapped to `XDM_CONST.OUTCOME_*`.
- `xdm.event.outcome_reason` = raw action verb. For VIRUS the
  `Actual` + `Secondary` + `Requested` action chain is concatenated
  (e.g. `"Cleaned; secondary: Quarantined; requested: Quarantine"`);
  each suffix is appended independently when its temp is non-null,
  with `Requested` additionally gated on `!= Actual`.

### Alert

- `xdm.alert.name` = Risk name | CIDS Signature string | Rule name
  (BEHAVIOR).
- `xdm.alert.original_alert_id` = SEP `Event ID` / `Event Description ID`
  when present, otherwise a deterministic synthesised key
  (`subtype|insert_time|host|disc`).
- `xdm.alert.original_threat_name` = same as `alert.name`.
- `xdm.alert.original_threat_id` = CIDS Signature ID (IPS only).
- `xdm.alert.description` = Description / Event Description / behaviour
  event description.
- `xdm.alert.severity` = `coalesce(_severity, _severity_band)`. The
  preferred value is the four-bucket SEP-native anchor `_severity`
  (`Info` / `Warning` / `Major` / `Critical`) -- see the Anchors
  section above. When the anchor is NULL the rule falls back to the
  legacy five-bucket banded label `_severity_band`
  (`Critical` / `High` / `Medium` / `Low` / `Informational`) so
  existing dashboards keep populating. The schema datatype is String
  (no `XDM_CONST.SEVERITY_*` family exists in the Cortex schema). For
  VIRUS the banded ladder defaults to High when `Disposition = "Bad"`
  or Risk name matches `^WS\.Malware\.\d+$` and Sensitivity is empty.
- `xdm.alert.status` = `XDM_CONST.ALERT_STATUS_DONE` when the observer
  took a containment action (block / quarantine / clean / delete /
  terminate) or for SYSTEM audit events; otherwise
  `XDM_CONST.ALERT_STATUS_PENDING`.
- `xdm.alert.category` = mapped to `XDM_CONST.THREAT_CATEGORY_*` from
  Application type / Category type / IPS Event Type / URL Category.
- `xdm.alert.subcategory` = Detection type / Application type /
  URL Category / Action Type.
- `xdm.alert.mitre_tactics` = `TA0xxx` tokens mapped to
  `XDM_CONST.MITRE_TACTIC_*`.
- `xdm.alert.mitre_techniques` = `Txxxx[.xxx]` tokens mapped to
  `XDM_CONST.MITRE_TECHNIQUE_*`.

### Source (offender / origin)

- `xdm.source.ipv4` / `.ipv6` = direction-aware (IPS/TRAFFIC) |
  Source Computer IP (RISK) | SymantecServer-prefixed IP (BEHAVIOR).
- `xdm.source.port` = direction-aware Local/Remote Port.
- `xdm.source.host.hostname` = direction-aware Local/Remote Host Name
  (IPS/TRAFFIC) | Source Computer Name (RISK) | SymantecServer host
  (BEHAVIOR) | Server Name (SYSTEM).
- `xdm.source.host.mac_addresses` = direction-aware Local/Remote MAC.
- `xdm.source.host.device_id` = Device ID (BEHAVIOR).
- `xdm.source.user.username` = User Name | positional tail (SYSTEM).
- `xdm.source.user.domain` = Domain Name | positional tail (SYSTEM).
- `xdm.source.user.groups` = Group Name (RISK).
- `xdm.source.zone` = Location (IPS/TRAFFIC).
- `xdm.source.application.name` = Application (IPS/TRAFFIC).
- `xdm.source.process.name` = Application name (RISK) | Application
  (IPS/TRAFFIC) | process name from the slot immediately after the
  `Rule:<name>,<pid>,` prefix (BEHAVIOR).
- `xdm.source.process.pid` = positional pid (BEHAVIOR).
- `xdm.source.process.command_line` = positional cmdline (BEHAVIOR).
- `xdm.source.process.executable.sha256` = SHA-256 (IPS) |
  Application hash (RISK fallback).
- `xdm.source.process.executable.md5` = MD-5 (IPS).

### Target (victim / destination)

- `xdm.target.ipv4` / `.ipv6` = direction-aware (IPS/TRAFFIC) |
  IP Address (RISK).
- `xdm.target.port` = direction-aware Local/Remote Port.
- `xdm.target.host.hostname` = direction-aware Local/Remote Host Name
  (IPS/TRAFFIC) | Computer name (RISK) | positional computer name
  (SYSTEM).
- `xdm.target.host.mac_addresses` = direction-aware MAC.
- `xdm.target.url` = Intrusion URL (IPS).
- `xdm.target.file.path` = File path (RISK).
- `xdm.target.file.sha256` = Application hash (RISK).
- `xdm.target.file.size` = File size (bytes) (RISK).
- `xdm.target.file.signer` = Certificate signer (VIRUS, when non-empty
  -- ready for signed-binary detections).
- `xdm.target.file.is_signed` = `true` when any of the four Certificate
  fields is non-empty (VIRUS); null otherwise.
- `xdm.target.application.name` = intentionally unset (the SEP RISK
  `Application name` is the threat actor and is mapped to
  `xdm.source.process.name` only).

### Network

- `xdm.network.ip_protocol` = OTHERS / TCP / UDP / ICMP token.
- `xdm.network.rule` = Rule name (TRAFFIC, BEHAVIOR).

## Not mapped (intentional)

- SEP `Sensitivity` raw value -- consumed only by the banded severity
  ladder; not surfaced as a separate XDM field (no canonical sink for
  raw vendor severity numerics).
- SEP `Hash type` / `First Seen` -- vendor-specific labels with no
  canonical XDM sink (Hash type is implicit in the
  `target.file.sha256` mapping).
- SEP `Confidence` (Risk only) -- vendor confidence indicator. The
  Cortex schema has no canonical confidence sink; the Sensitivity
  ladder already drives banded severity.
- SEP `Application version` -- captured in the syslog payload but no
  application-version sink in the `target.application` schema is
  exposed; deliberately not extracted.
- SEP `Company name` (quoted) -- enrichment field with no clean XDM
  sink; deliberately not extracted.
- SEP Site name -- the SEPM administrative site label. No canonical
  `xdm.observer.zone` field is documented; omitted.
- SEP `Occurrences` (VIRUS) -- no canonical `xdm.event.event_count`
  sink in the Cortex schema. Folded into `xdm.event.description` as
  `Occurrences: N` so it remains queryable. Promote to
  `xdm.event.event_count` if the field is added to the schema in
  future.
- SEP Certificate issuer / thumbprint / serial -- only
  `xdm.target.file.signer` is in the Cortex schema reference. The
  other three Certificate fields drive `xdm.target.file.is_signed`
  but are dropped after that decision.
- SEP `Last update time` / `Event Insert Time` (VIRUS) -- syslog-window
  timestamps with no direct XDM sink; the SEP forwarder already
  preserves them in `_insert_time` (`xdr_data` column).
- SEP SONAR / Enforcer Traffic -- log shapes are not yet sampled. The
  sub-type discriminator returns `"UNKNOWN"` for these and they fall
  through unmapped. Add discriminator branches and extraction patterns
  when representative samples become available.

## Cortex parser pitfalls applied

- The sub-type discriminator lives in its own `alter` stage (Stage 1)
  so subsequent stages can gate temps on `_subtype` without sibling
  reference errors. Stage 2 extracts everything from `_raw_log` in
  parallel; no target references another sibling target. Stage 3
  derives leaf temps that depend only on stage-2 outputs. Stage 4
  derives direction-aware network temps that depend on stage-3
  IPv4/IPv6. Stage 5 derives sub-type-final picks. Stage 6 drains
  every temp into its `xdm.*` sink in a single alter.
- Numeric comparisons (e.g. `_risk_sensitivity ~= "^[89]$"`) keep the
  value as a string and pattern-match. Avoids string-vs-number
  coercion errors in the Sensitivity ladder.
- Object-type-gated routing for IPv4 vs IPv6 lives in Stage 3 and uses
  character-family pattern matches (a dotted-quad regex routes to v4;
  a colon-bearing hex regex routes to v6). Replaces the legacy
  fixed-width 8-group IPv6 regex which silently rejected any hextet
  shorter than five characters.
- Quoted fields containing commas (e.g.
  `"Company name: curl, https://curl.se/"`) would be extracted by
  anchoring on the closing quote rather than the next comma; this
  rule does not surface that field but the technique is documented
  for future use.
- File-size literal parens are escaped in the regex:
  `File size \(bytes\):\s+(\d+)`.
- Sub-type-positional regex chains (BEHAVIOR `_bhv_*`, SYSTEM
  `_sys_*`) are extracted unconditionally in Stage 2 because the
  `_subtype` discriminator is in a different alter; Stage 6 gates the
  drain on `_subtype = "BEHAVIOR"` / `"SYSTEM"` so accidental
  cross-shape regex matches are discarded before reaching XDM fields.
- All `XDM_CONST.*` values are bare (unquoted).
- All `_temp` variables extracted in Stage 2 are referenced in a
  downstream stage; no orphan temps.
- The Virus-found shape from at least one SEP forwarder build emits
  `Domain Name:<value>Group Name: <value>` -- no whitespace after the
  `Domain Name:` colon AND no comma between the adjacent KV pairs.
  The well-formed shape is `Domain Name: <value>,Group Name:`. The
  `_user_domain_kv` pattern uses a non-greedy capture anchored on the
  first of `,`, the literal token `Group Name:`, or end-of-line so
  both forms yield the intended `<value>`. Cortex's regex flavour
  does not (reliably) support lookahead, so the alternation token
  itself sits inside the match but outside the capturing group.

## KB snapshot

Snapshot date: 2026-04-26.

Broadcom KB TECH171741 (SEP log field reference) was the source of
record for the Virus-found field-name list and the numeric Application
type code map. The map itself is encoded inline in the Stage-3
`_category_const` derivation (see the `Application type` arm) rather
than a dedicated sibling temp -- this avoids the Stage-3 sibling-
reference contract and keeps the priority chain readable in one place.
The in-rule code map covers the codes observed in current samples
(notably 47, 48, 100, 124, 127) and a handful of frequently-seen
neighbouring codes (104, 126, 128); codes not present in the map fall
through to the `Category set` / textual `Application type` branches and
ultimately to null.

Where the current sample set disagrees with the KB (e.g. the malformed
`Domain Name:<value>Group Name:` boundary noted above; absent / blank
Sensitivity for true Virus-found detections) the sample-driven
behaviour wins. Update the code map AND bump the snapshot date above
when newer KB revisions or additional samples introduce codes the
current map does not handle.

## Severity ladder

RISK severity ladder: Sensitivity drives the band when present. For
Virus-found records the field is frequently empty, so a Disposition /
Risk-name arm runs first: `Disposition = "Bad"` or a canonical
malware-cloud name (`WS.Malware.\d+`) escalates to High even when
Sensitivity is blank. When neither Sensitivity nor the Disposition arm
fires, fall back on Detection type as a confidence indicator (signature
/ antivirus engine = high confidence -> High; heuristic / reputation =
lower confidence -> Medium; everything else -> Medium default).

## Threat category mapping (priority order)

1. Numeric `Application type` code map (Virus-found shape). Sourced
   from Broadcom KB TECH171741 (see KB snapshot); codes not present
   fall through. Where the KB taxonomy lacks a 1:1 Cortex equivalent
   (e.g. `Heuristic Virus` / generic Malware) the closest available
   generic constant (`THREAT_CATEGORY_BACKDOOR`) is used.
2. Coarse `Category set` text (e.g. `Malware`).
3. Textual `Application type` (Potential-risk shape).
4. Free-text `Category type` (both shapes).
5. IPS `event_type` / URL category fallback.

The Cortex schema has no `THREAT_CATEGORY_MALWARE`; "Malware" maps to
`BACKDOOR` (closest available generic). The code map is inlined in
Stage 3 (rather than derived into its own sibling temp) because
Stage-3 targets cannot reference each other.

## Outcome mapping

SEP `Actual action` values include `Quarantined`, `Cleaned`, `Deleted`,
`Left alone`, `Blocked`, etc. Firewall / IPS Action values include
`Allowed`, `Blocked`. Strict tri-state mapping per the task spec:
`SUCCESS` / `FAILED` / `UNKNOWN` only.

- For RISK, `Left alone` / `no action` means malware was detected but
  the security control did NOT contain it -- the user remains exposed,
  so the security outcome is `FAILED`.
- For firewall TRAFFIC and IPS, `Allow` / `Permit` / `Pass` means the
  control behaved exactly as policy intends, so the outcome is
  `SUCCESS`.
- SYSTEM audit events are intrinsically successful.

The IPS positional `Action` token (4th field after Remote Host MAC) is
carried over from the legacy rule's positional pattern; gives IPS
events a real action verb so `_outcome` / `observer.action` are not
stuck at `OUTCOME_UNKNOWN` for the IPS sub-type. CAUTION: this is a
positional regex and is fragile to SEP IPS field-order changes. Cover
with regression samples in the IPS sub-type test suite so format drift
surfaces early.

## Description suffix chain (VIRUS)

For VIRUS records the Cortex schema (per the in-repo schema-guide
reference) does not expose canonical `xdm.event.event_count` /
`xdm.event.start_time` / `xdm.event.end_time` sinks, so the
`Occurrences` value plus the `Event time` / `End Time` strings are
appended to the event description
(`<base>; Occurrences: N; Event time: ...; End Time: ...`). Each
suffix is omitted when the underlying temp is null. Promote to
dedicated XDM sinks if the schema gains them.

## Action chain (VIRUS)

For VIRUS records, fold the `Actual` / `Secondary` / `Requested` verbs
into a single human-readable string. Each suffix is appended
independently so any combination of present / absent sibling fields
produces a coherent string:

- `Actual=Cleaned, Secondary=Quarantined, Requested=Cleaned`
  -> `"Cleaned; secondary: Quarantined"`
- `Actual=Cleaned, Secondary=Quarantined, Requested=Quarantine`
  -> `"Cleaned; secondary: Quarantined; requested: Quarantine"`
- `Actual=Cleaned, Secondary=null, Requested=Quarantine`
  -> `"Cleaned; requested: Quarantine"`
- `Actual=Cleaned` alone -> `"Cleaned"`

`Requested` is appended only when present AND differs from `Actual` to
avoid noisy `Cleaned; requested: Cleaned` repetition. Other RISK shapes
and other sub-types keep the single-verb form.

## Stable alert identifier

SEP syslog very rarely carries a true unique ID, so the rule

1. tries to extract an `Event ID:` / `Event Description ID:` value
   when present; otherwise
2. synthesises a deterministic key from
   `subtype + ingest timestamp + best-available host + per-subtype discriminator`.

This is unique within an ingestion window and is stable across
retries, satisfying the `WARN-032` expectation that
`alert.severity` is paired with `alert.original_alert_id`.

## Backward-compat mirror

The legacy SEP rule placed the RISK `Domain Name` token on
`xdm.target.domain`. Semantically it is the user's AD domain (hence
the primary mapping is to `xdm.source.user.domain`); this mirror keeps
existing tenant dashboards / saved queries that look at
`xdm.target.domain` working.

## Certificate sinks (VIRUS)

Only `xdm.target.file.signer` has a canonical schema sink;
`xdm.target.file.is_signed` flips `true` when any of the four
Certificate fields is non-empty (post-trim) OR the `Signing
timestamp` is a non-zero numeric value. Issuer / thumbprint / serial
values are deliberately not surfaced (see "Not mapped" above).

## Technique mapping table

The `_mitre_techniques_const` map covers ATT&CK techniques observed in
SEP RISK and IPS payloads (including the in-batch sample IDs `T1048`
and `T1105`) plus the broader set of techniques commonly cited by SEP
detection content. Extend further when new ATT&CK IDs appear in
production samples.
