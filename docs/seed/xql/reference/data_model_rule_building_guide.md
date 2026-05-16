# Data Model Rule Building Guide

## Overview

This guide documents the end-to-end process for building a Cortex XSIAM data model rule from raw log samples. It was developed from a real-world exercise mapping Palo Alto Networks IoT Security alert logs to XDM fields, validated against production data.

## Where rules live: the packs/ layout

Every vendor + product combination ships as a self-contained pack
under `PRIVATE_DOCS/packs/<vendor_product>/`. Conventional file
names inside each pack:

```
PRIVATE_DOCS/packs/<vendor_product>/
    parser.xql        # INGEST rule(s); optional, only when the
                      #   pack pre-extracts anchor columns at
                      #   ingest. See PRIVATE_DOCS/anchor_field_design.md.
    datamodel.xql     # MODEL rule; always present.
    documentation.md  # Per-pack notes; optional.
    samples/          # Reserved for future raw-ingest samples.
```

Folder names are lower-case, vendor + product, joined by an
underscore (e.g. `efficientip_ddi`, `extrahop_revealx`,
`symantec_endpoint_protection`). Anything that previously lived
under the (now-removed) `PRIVATE_DOCS/datamodel_rules/`
directory is in the matching `packs/<vendor_product>/datamodel.xql`.

## Process

### Step 1: Analyse the Raw Log Structure

Export a sample of raw logs (10-100 rows) from the target dataset. Identify:

- **Top-level columns**: Fields already extracted during parsing (e.g. `name`, `severity`, `hostname`, `deviceid`)
- **Nested JSON fields**: Rich metadata stored in JSON string columns like `msg` or `_raw_log`
- **Data types**: Distinguish strings from numbers (e.g. `severityNumber` is an integer, not a string)
- **Field availability patterns**: Some fields only appear in certain alert types (e.g. `fromip` in firewall alerts, `localip` in IoT Security alerts)

### Step 2: Map Source Fields to XDM

Cross-reference the raw fields against the XDM schema (645 fields across 12 categories). Prioritise:

1. **Required observer fields**: `xdm.observer.vendor`, `xdm.observer.product` (hardcoded to vendor/product name)
2. **Event type**: `xdm.event.type` (e.g. "ALERT", "NETWORK", "AUTH")
3. **Alert fields**: `xdm.alert.*` for security alert datasets
4. **Source/target fields**: IP addresses, hostnames, ports, interfaces
5. **Network fields**: Protocol, application, direction
6. **Location fields**: City, country from geo metadata

### Step 3: Write the Rule

Structure the rule as:

```
[MODEL: dataset=dataset_name_raw]
filter
    <null guard or category filter>
| alter
    <extract temporary fields from nested JSON>
| alter
    <assign XDM fields using extracted temps and top-level columns>
```

**Before you start writing, decide whether you need one MODEL block
with one pipeline or one MODEL block with several.** A single
dataset can contain multiple distinct event shapes that each need
their own discriminator + extraction pipeline (e.g. one dataset
that carries DNS, DHCP, SSH and sudo events from the same
appliance). When that happens, the file still gets exactly **one**
`[MODEL: dataset=...]` header for that dataset; the multiple
event-shape branches live INSIDE that single MODEL block as
separate `;`-terminated pipelines, one per event shape. Putting two
`[MODEL: dataset=NAME]` headers in one file for the same dataset is
a structural error -- Cortex permits exactly one MODEL block per
`(dataset, model)` tuple per file, and the analyser flags duplicates
as `ERR-026`. If a single dataset really does need two distinct
modelling views, distinguish them with the optional `model=` qualifier
(e.g. `model=Auth` vs `model=Network`) so the `(dataset, model)`
tuples are unique.

If two or more pipelines inside the same MODEL block would share
more than ~15 lines of identical header parsing or common-field
extraction, factor that shared work into a `[RULE: name]` block
at the top of the file and `call name` from each pipeline -- see
[Pattern 10](#pattern-10-shared-logic-via-rule--call) for the
decision rule, syntax notes, and a worked example. Spotting this
early is much cheaper than rewriting four near-identical preludes
later.

### Step 4: Validate

- Every `_temp` variable extracted in the first `alter` MUST be referenced in the second `alter`
- Numeric fields must be compared with numeric literals (not strings)
- XDM_CONST values must not be quoted
- Dataset names must not be quoted in block headers
- **Do NOT use a leading `|` pipe before the first stage** -- the first `alter` or `filter` after the `[MODEL: ...]` header must not have a pipe prefix. Write `[MODEL: dataset=name_raw]\nalter` not `[MODEL: dataset=name_raw]\n| alter`. Subsequent stages after the first DO use `| alter`, `| filter` etc.
- **Do NOT use `action_evtlog_data_fields` in MODEL rules** -- even though this field is in the xdr_data schema, Cortex may reject it as "unknown field" for specific datasets. Always extract vendor metadata directly from `_raw_log` using the original JSON paths (e.g. `json_extract_scalar(_raw_log, "$.imperva.audit_trail.resource_type")`)
- Simple xdr_data fields set by the parser (e.g. `event_id`, `actor_primary_username`, `action_evtlog_message`, `actor_remote_ip`) ARE available and work correctly in MODEL rules
- **XDM field availability is per-dataset, not universal** -- the XDM schema defines 645+ fields, but not all are available on every dataset. A valid XDM field (e.g. `xdm.target.ipv4`) may be rejected as "unknown field" on one dataset while working perfectly on another. Always test field availability against the specific dataset. If a field is rejected, document it in the Excluded Fields section with the dataset name and move on
- **Do NOT self-reference XDM fields in assignments** -- in MODEL rules, you cannot read an XDM field on the right-hand side of the same assignment. `xdm.target.ipv4 = coalesce(xdm.target.ipv4, _fallback)` is INVALID because the XDM field has no value yet when the assignment executes. Use an intermediary `_temp` variable or assign the fallback directly: `xdm.target.ipv4 = _fallback`

---

## Key Patterns

### Pattern 1: JSON Label/Value Array Extraction

Many Cortex data sources store threat metadata as an array of label/value pairs:

```json
"values": [
  {"label": "Client Port", "value": 41192},
  {"label": "Threat ID", "value": 599805},
  {"label": "Threat Category", "value": "malicious-elf"}
]
```

`json_extract_scalar` cannot easily filter by label within an array. Use `regextract` instead:

```xql
_client_port = arrayindex(regextract(msg, "\"Client Port\"\s*,\s*\"value\"\s*:\s*(\d+)"), 0),
_threat_category = arrayindex(regextract(msg, "\"Threat Category\"\s*,\s*\"value\"\s*:\s*\"([^\"]+)\""), 0)
```

- For **numeric values**: capture group `(\d+)`, then wrap with `to_number()` when assigning to a Number XDM field
- For **string values**: capture group `\"([^\"]+)\"`
- Always wrap in `arrayindex(..., 0)` since `regextract` returns an array

### Pattern 2: MAC Address vs Hostname Routing

Some datasets store MAC addresses in the `hostname` field. Detect and route:

```xql
_hostname = coalesce(internal_hostname, hostname)
```

Then in the XDM assignment:

```xql
xdm.source.host.hostname = if(_hostname ~= "^[0-9a-fA-F]{2}(:[0-9a-fA-F]{2}){5}$", null, _hostname),
xdm.source.host.mac_addresses = if(_hostname ~= "^[0-9a-fA-F]{2}(:[0-9a-fA-F]{2}){5}$", arraycreate(_hostname), null)
```

### Pattern 3: Severity Number to Log Level Mapping

Map numeric severity values to XDM_CONST.LOG_LEVEL using an `if()` chain with **numeric comparisons** (not string):

```xql
xdm.event.log_level = if(
    severityNumber = 4, XDM_CONST.LOG_LEVEL_ERROR,
    severityNumber = 3, XDM_CONST.LOG_LEVEL_WARNING,
    severityNumber = 2, XDM_CONST.LOG_LEVEL_WARNING,
    severityNumber = 1, XDM_CONST.LOG_LEVEL_INFORMATIONAL,
    XDM_CONST.LOG_LEVEL_NOTICE)
```

**Pitfall**: `severityNumber = "4"` fails with "Expected number but received string". Always use unquoted numeric literals for integer fields.

### Pattern 4: Coalesce for Multi-Path Fields

When the same logical data appears under different JSON paths depending on alert type:

```xql
xdm.source.ipv4 = coalesce(_fromip, json_extract_scalar(msg, "$.localip")),
xdm.alert.original_threat_id = coalesce(_threat_id, _rule_id),
xdm.source.host.device_category = coalesce(_local_category, profileCategory)
```

### Pattern 5: Firewall Interface Mapping

Map inbound/outbound firewall interfaces to source/target:

```xql
xdm.source.interface = _fw_inbound_if,
xdm.target.interface = _fw_outbound_if
```

### Pattern 6: Remote Host Metadata Extraction

For nested objects within arrays, use indexed JSON paths:

```xql
_remote_ip = json_extract_scalar(msg, "$.remoteHostMetadata[0].ip"),
_remote_port = json_extract_scalar(msg, "$.remoteHostMetadata[0].connections[0].port"),
_remote_proto = json_extract_scalar(msg, "$.remoteHostMetadata[0].connections[0].ipProto"),
_remote_city = json_extract_scalar(msg, "$.remoteHostMetadata[0].cityName"),
_remote_country = json_extract_scalar(msg, "$.remoteHostMetadata[0].countryCode")
```

### Pattern 7: Vendor-Provided Aggregate Severity

When a vendor provides both per-filter/per-rule severity values (e.g. in a `filters[]` array) and a pre-computed aggregate severity (e.g. `filterRiskLevel`), always prefer the aggregate. The aggregate represents the vendor's own "highest severity wins" logic and avoids the need to join multiple values into a single scalar field.

Normalise the vendor's lowercase labels to proper case for `xdm.alert.severity`:

```xql
xdm.alert.severity = if(
    filter_risk_level = "critical", "Critical",
    filter_risk_level = "high", "High",
    filter_risk_level = "medium", "Medium",
    filter_risk_level = "low", "Low",
    filter_risk_level = "info", "Informational"),
```

Never join multiple severity strings into a single value (e.g. `"medium, low, info"`) -- `xdm.alert.severity` is a scalar field and expects exactly one value.

If no vendor aggregate is available, use `arraymax()` on numeric weights to select the highest severity from an array, then map back to the label.

### Pattern 8: Single-Entity Mirroring

When a payload contains only one entity of a given type (one IP address, one username, one hostname), map it to both `xdm.source.*` and `xdm.target.*` fields. This is a deliberate design choice that maximises correlation coverage in XSIAM -- analysts may query either source or target fields depending on context.

Common mirroring pairs:

| Field pair | When to mirror |
|-----------|----------------|
| `xdm.source.ipv4` / `xdm.target.ipv4` | Payload has only one IP (e.g. ATO alert with just `client.ip`) |
| `xdm.source.user.username` / `xdm.target.user.username` | Payload has only one user (e.g. victim account with no attacker identity) |
| `xdm.source.host.hostname` / `xdm.target.host.hostname` | Payload has only one hostname |

Example from the Imperva ATO rule where `client.ip` is the only IP and `request_user` is the only user:

```xql
    // XDM Source fields
    xdm.source.ipv4 = _client_ip,
    xdm.source.user.username = _request_user,

    // XDM Target fields -- same values, different correlation path
    xdm.target.ipv4 = _client_ip,
    xdm.target.user.username = _request_user,
```

This is NOT an error -- the rules engine (INFO-011) suggests mirroring when it detects one-sided mappings. When the source and target are genuinely different entities, do not mirror.

### Pattern 9: Positional/Syslog Log Extraction

When `_raw_log` contains a syslog-wrapped positional (space-delimited) log rather than JSON, use `regextract()` to strip the syslog prefix and `split()` + `arrayindex()` for field extraction by position.

**Step 1: Strip the syslog wrapper**

Identify the consistent delimiter between the syslog prefix and the actual log payload. Extract everything after it:

```xql
_stripped_log = arrayindex(regextract(_raw_log, "Info:\s+(.+)$"), 0),
_syslog_host = arrayindex(regextract(_raw_log, ">\w+\s+\d+\s+[\d:]+\s+(\S+)\s+accesslogs"), 0)
```

**Step 2: Split by space and extract positional fields**

Use `split()` to break the stripped log into an array, then `arrayindex()` to access each field by its 0-indexed position:

```xql
_parts = split(_stripped_log, " ")
| alter
    _timestamp = arrayindex(_parts, 0),
    _elapsed = arrayindex(_parts, 1),
    _client_ip = arrayindex(_parts, 2),
    _result_status = arrayindex(_parts, 3),
    _bytes = arrayindex(_parts, 4),
    _method = arrayindex(_parts, 5),
    _url = arrayindex(_parts, 6),
    _user = arrayindex(_parts, 7)
```

**Step 3: Decompose composite fields**

Split compound tokens (e.g. `TCP_MISS/200`, `DIRECT/hostname`) into their components:

```xql
_cache_result = arrayindex(split(to_string(_result_status), "/"), 0),
_http_status = arrayindex(split(to_string(_result_status), "/"), 1)
```

**Step 4: Extract from non-positional sections**

For sections that contain spaces (e.g. angle-bracket-enclosed scanning details), use `regextract()` with targeted patterns:

```xql
_acl_tag = arrayindex(regextract(_stripped_log, "ERR:\d+\s+(\S+)\s"), 0)
```

**Key considerations**:
- The `split()` approach only works when positional fields are single tokens (no embedded spaces). Verify this by examining diverse samples
- Always wrap `arrayindex()` values in `to_string()` before passing to `split()` or `regextract()` for sub-field decomposition
- For usernames in `"DOMAIN\user@domain"` format, extract domain and username separately using `regextract()` with backslash-aware patterns
- Syslog hostname extraction gives the observer/intermediary device identity -- map to both `xdm.observer.name` and `xdm.intermediate.host.*` for proxy devices
- Fields that are genuinely empty use `-` (hyphen) in Squid format -- always check `field != "-"` before assigning to XDM

Example from the Cisco WSA access log rule where `_raw_log` contains a syslog-wrapped Squid access log:

```xql
// Strip syslog wrapper
alter
    _wsa_log = arrayindex(regextract(_raw_log, "Info:\s+(.+)$"), 0)
// Split positional fields
| alter
    _parts = split(_wsa_log, " ")
| alter
    _client_ip = arrayindex(_parts, 2),
    _result_status = arrayindex(_parts, 3),
    _http_method = arrayindex(_parts, 5),
    _url = arrayindex(_parts, 6),
    _user_raw = arrayindex(_parts, 7)
// Decompose and map
| alter
    _cache_result = arrayindex(split(to_string(_result_status), "/"), 0),
    _http_status = arrayindex(split(to_string(_result_status), "/"), 1)
| alter
    xdm.source.ipv4 = _client_ip,
    xdm.network.http.method = _http_method,
    xdm.network.http.response_code = _http_status,
    xdm.event.outcome = if(
        _cache_result = "TCP_MISS" or _cache_result = "TCP_HIT", XDM_CONST.OUTCOME_SUCCESS,
        _cache_result = "TCP_DENIED", XDM_CONST.OUTCOME_FAILED,
        XDM_CONST.OUTCOME_UNKNOWN)
```

### Pattern 10: Shared logic via [RULE:] + call

When a single dataset feeds two or more event shapes (daemons,
action types, message families) and the per-shape pipelines would
otherwise repeat the same header parsing, allow-list filter, or
common-field extraction, factor that shared work into a `[RULE:]`
block once and `call` it from each pipeline.

**File shape.** A Pattern 10 rule file has exactly **one**
`[MODEL: dataset=...]` header for the dataset. Inside that single
MODEL block there are several `;`-terminated pipelines, one per
event shape, each opening with `call shared_rule | filter ...`.
Putting two `[MODEL: dataset=NAME]` headers in one file for the
same dataset is a structural error (Cortex rejects it; the
analyser flags it as `ERR-026`). The two-or-more `[MODEL:]`
headers in earlier drafts of this guide were wrong on this point;
the corrected EfficientIP DDI worked example below is the
authoritative shape.

**When to use it.** Apply this pattern when the MODEL block would
otherwise contain two or more pipelines that share more than ~15
lines of identical `alter` (or `filter` + `alter`) logic. Two
pipelines with five duplicated lines is not enough -- the
indirection costs more than the duplication. Four pipelines with
twenty duplicated lines each is exactly the case Pattern 10 is for.
The analyser fires `SUG-017` once the shared count crosses 18
normalised lines per pair.

**What it buys you and what it does not.** It buys cleaner files,
trivial extension to a new event shape (one new pipeline inside the
same MODEL block, no new header parser), and a single point of
repair when the upstream log format changes. It does **not** buy a
runtime performance gain -- Cortex inlines the called rule per
pipeline, so the work is done once per pipeline either way. Use
the pattern for maintainability, not speed.

**Syntax notes.**

- A `[RULE: name]` block stands on its own at the top of the file
  (or in a separate file at the same vendor level). The name is
  unquoted, lowercase with underscores, and conventionally prefixed
  with the vendor or product (e.g. `efficientip_syslog_header`,
  `beyondtrust_pra_common_fields_modeling`,
  `esxi_general_fields_mapping`).
- Like a MODEL pipeline, the RULE body's first stage has no leading
  `|`; subsequent stages do. The block ends with a semicolon.
- `call rule_name` is a first-class XQL stage. Like any other
  stage it omits the leading `|` when it is the first stage of a
  pipeline (`call efficientip_syslog_header`) and takes a `|` when
  it is not (`| call esxi_general_fields_mapping`). It is normally
  the first stage of every pipeline in the MODEL block, immediately
  followed by a daemon / event-shape `| filter` so the rest of the
  pipeline sees only the rows that pipeline is responsible for. The
  ESXi worked example in `PRIVATE_DOCS/all_modeling_rules.txt:1056-1408`
  calls two RULE blocks back-to-back per pipeline: one for event
  classification, one for general field mapping.
- A called rule sees the same `_raw_log` and any other dataset
  columns the pipeline sees. Any intermediates the RULE produces
  (conventionally underscore-prefixed, e.g. `_syslog_proc`,
  `_syslog_msg`) are visible to every stage of the calling
  pipeline after the `call`. Treat the intermediates the RULE
  produces as the rule's "public interface" and document them in
  the file header.
- A RULE may itself contain its own filter; rows that do not pass
  the RULE's filter are dropped from the calling pipeline too.
  This is exactly how a top-of-file allow-list is centralised.

**Worked example: EfficientIP DDI.** The EfficientIP DDI rule
(`PRIVATE_DOCS/packs/efficientip_ddi/datamodel.xql`)
ingests four daemons -- BIND named, ISC dhcpd, sshd, sudo -- from a
single `efficientip_raw` dataset, in two syslog envelope shapes
(RFC 3164 plus RFC 5424 wrapped inside an outer kernel record).
Every event shape needs the same header parsing: priority,
facility, severity, host, pid, proc, msg. Without RULE/CALL that
would be ~20 lines of duplicated `alter` at the top of every
pipeline, with two regex paths each (one per envelope shape). The
file uses Pattern 10 -- ONE `[RULE:]`, ONE `[MODEL:]`, FOUR
`;`-terminated pipelines inside the MODEL:

```xql
[RULE: efficientip_syslog_header]

filter _raw_log ~= "(\s(named|dhcpd|sshd|sudo)\[\d+\]:|\skernel:\s+\S+\s+\S+\s+(named|dhcpd|sshd|sudo)\s+\d+\s+-\s+-\s)"

| alter
    _syslog_priority = to_integer(arrayindex(regextract(_raw_log, "^<(\d{1,3})>"), 0)),
    _syslog_proc = coalesce(
        arrayindex(regextract(_raw_log, "\s(named|dhcpd|sshd|sudo)\[\d+\]:"), 0),
        arrayindex(regextract(_raw_log, "\skernel:\s+\S+\s+\S+\s+(named|dhcpd|sshd|sudo)\s+\d+\s+-\s+-"), 0)),
    _syslog_msg = coalesce(
        arrayindex(regextract(_raw_log, "(?:named|dhcpd|sshd|sudo)\[\d+\]:\s*(.+)$"), 0),
        arrayindex(regextract(_raw_log, "(?:named|dhcpd|sshd|sudo)\s+\d+\s+-\s+-\s+(.+)$"), 0))
    // ... _syslog_pid, _syslog_host, _syslog_facility, _syslog_severity ...
;

[MODEL: dataset = efficientip_raw]

// Pipeline 1 -- BIND named (DNS).
call efficientip_syslog_header
| filter _syslog_proc = "named"
| alter
    // ... DNS-specific extractions, all reading from _syslog_msg ...
;

// Pipeline 2 -- ISC dhcpd (DHCP).
call efficientip_syslog_header
| filter _syslog_proc = "dhcpd"
| filter not _raw_log ~= "(balanc(?:ing|ed) pool|...)"
| alter
    // ... DHCP-specific extractions ...
;

// Pipeline 3 -- OpenSSH sshd. ... ;
// Pipeline 4 -- sudo audit.    ... ;
```

The same `_syslog_*` intermediates feed all four daemon pipelines;
adding a fifth daemon (or a third envelope shape) is now a
one-rule edit, not a four-pipeline rewrite. Note in particular
that there is exactly one `[MODEL: dataset = efficientip_raw]`
header -- the four daemon pipelines are statements INSIDE that
single MODEL block, each terminated by its own `;`. A second
`[MODEL: dataset = efficientip_raw]` header would be rejected by
Cortex and is caught at write-time by `ERR-026`.

**Cross-references.** Two further worked examples ship in
`PRIVATE_DOCS/all_modeling_rules.txt`:

- BeyondTrust PRA (`all_modeling_rules.txt:286-348`) -- one
  `[RULE: beyondtrust_pra_common_fields_modeling]` produces all
  XDM mappings that are common to every BeyondTrust PRA event
  type, then per-event-type pipelines INSIDE the single MODEL
  block filter to a specific event family and `call` the common
  rule.
- ESXi (`all_modeling_rules.txt:1056-1408`) -- two RULE blocks
  back-to-back: `esxi_event_classification` produces a single
  `esxi_event_type` discriminator from a wall of regex tests,
  and `esxi_general_fields_mapping` derives the syslog priority /
  facility / severity / log-level fields. Every per-event-type
  pipeline INSIDE the single MODEL block opens with
  `call esxi_event_classification | call esxi_general_fields_mapping
  | filter esxi_event_type = ...`.

---

## Common Pitfalls

| Pitfall | Example | Fix |
|---------|---------|-----|
| Unused temp field | `_unused = something` never assigned to XDM | Remove the extraction or map to an XDM field |
| String-vs-number comparison | `severityNumber = "4"` | Use `severityNumber = 4` (no quotes) |
| Quoted XDM_CONST | `"XDM_CONST.OUTCOME_SUCCESS"` | Use `XDM_CONST.OUTCOME_SUCCESS` (no quotes) |
| Quoted dataset name | `dataset="name_raw"` | Use `dataset=name_raw` (no quotes) |
| Missing observer fields | No `xdm.observer.vendor` or `xdm.observer.product` | Always hardcode these |
| Missing event type | No `xdm.event.type` | Always set to "ALERT", "NETWORK", "AUTH", etc. |
| Missing null guard | No filter in the MODEL block | Add `filter name != null` or similar |

---

## Reference: panw_iot_security_alerts_raw Data Model Rule

This rule was validated against production IoT Security alert data from Palo Alto Networks. It maps 30+ fields across 7 XDM categories.

### Source Fields Available

**Top-level columns**: date, _time, severityNumber, id, msg, url, name, type, siteid, vendor, profile, category, deviceid, hostname, resolved, severity, siteName, tenantid, profileId, description, inspectorid, serviceLevel, primaryDevice, profileCategory, profileVertical, internal_hostname, trafficRestricted

**Nested in msg JSON (top-level paths)**: fromip, toip, localip, alertType, alertSource, ruleid, trafficDirection, localDeviceRole, localCategory, localProfile, localVertical, generationTimestamp, id, severity, description

**Nested in msg JSON (values array)**: Client Port, Threat ID, Threat Category, Threat Type, Number of Occurrences, CVE, Alert Source, Firewall Name, Firewall Action, Firewall Inbound Interface, Firewall Outbound Interface, Name of the Transferred File, user agent

**Nested in msg JSON (remoteHostMetadata array)**: ip, cityName, countryCode, connections[].app, connections[].port, connections[].ipProto

### Field Mapping Table

| Source Field | XDM Field | Type | Notes |
|-------------|-----------|------|-------|
| id | xdm.alert.original_alert_id | String | Unique IoT Security alert ID |
| name | xdm.alert.name | String | Alert display name |
| description | xdm.alert.description | String | Full threat description |
| severity | xdm.alert.severity | String | "low", "high" etc. |
| msg -> Threat Category / category | xdm.alert.category | String | coalesce: values array then top-level |
| msg -> Threat Type / alertType | xdm.alert.subcategory | String | coalesce: values array then JSON path |
| msg -> Threat ID / ruleid | xdm.alert.original_threat_id | String | coalesce: numeric ID then rule ID |
| name | xdm.alert.original_threat_name | String | Same as alert name |
| url | xdm.alert.source_url | URL | Link to IoT Security portal |
| resolved | xdm.alert.status | XDM_CONST | DONE if resolved, else PENDING |
| "ALERT" | xdm.event.type | String | Hardcoded |
| description | xdm.event.description | String | Same as alert description |
| type | xdm.event.original_event_type | String | Original alert type value |
| severityNumber | xdm.event.log_level | XDM_CONST | Numeric if() chain |
| resolved | xdm.event.outcome | XDM_CONST | SUCCESS if resolved, else UNKNOWN |
| "Palo Alto Networks" | xdm.observer.vendor | String | Hardcoded |
| "IoT Security" | xdm.observer.product | String | Hardcoded |
| msg -> alertSource | xdm.observer.type | String | "Firewall", "IoT Security" |
| msg -> Firewall Name | xdm.observer.name | String | e.g. "PA-440" |
| msg -> Firewall Action | xdm.observer.action | String | e.g. "Dropped the session" |
| msg -> fromip / localip | xdm.source.ipv4 | IPv4 | coalesce both paths |
| msg -> Client Port | xdm.source.port | Number | to_number() from values array |
| msg -> user agent | xdm.source.user_agent | String | e.g. "Wget/1.21.2" |
| msg -> Firewall Inbound Interface | xdm.source.interface | String | e.g. "ethernet1/5" |
| internal_hostname / hostname | xdm.source.host.hostname | String | Excludes MAC addresses |
| hostname (MAC pattern) | xdm.source.host.mac_addresses | Array | arraycreate() when MAC detected |
| deviceid | xdm.source.host.device_id | String | IoT device identifier |
| msg -> localCategory / profileCategory | xdm.source.host.device_category | String | "IT Server", "generic" |
| msg -> localProfile / profile | xdm.source.host.device_model | String | "Proxmox Server", "Apple Device" |
| msg -> toip / remoteHostMetadata[0].ip | xdm.target.ipv4 | IPv4 | coalesce both paths |
| msg -> remoteHostMetadata[0]...port | xdm.target.port | Number | to_number() |
| msg -> Firewall Outbound Interface | xdm.target.interface | String | e.g. "ethernet1/6" |
| msg -> remoteHostMetadata[0].cityName | xdm.target.location.city | String | e.g. "Singapore" |
| msg -> remoteHostMetadata[0].countryCode | xdm.target.location.country | String | e.g. "SG" |
| msg -> remoteHostMetadata[0]...filename | xdm.target.file.filename | String | Transferred file name |
| msg -> remoteHostMetadata[0]...app | xdm.network.application_protocol | String | e.g. "web-browsing" |
| msg -> remoteHostMetadata[0]...ipProto | xdm.network.ip_protocol | String | e.g. "tcp" |

### Complete Validated Rule

```xql
[MODEL: dataset=panw_iot_security_alerts_raw]
filter
    name != null
| alter
    _fromip = json_extract_scalar(msg, "$.fromip"),
    _toip = json_extract_scalar(msg, "$.toip"),
    _alert_type = json_extract_scalar(msg, "$.alertType"),
    _alert_source = json_extract_scalar(msg, "$.alertSource"),
    _rule_id = json_extract_scalar(msg, "$.ruleid"),
    _local_category = json_extract_scalar(msg, "$.localCategory"),
    _local_profile = json_extract_scalar(msg, "$.localProfile"),
    _remote_ip = json_extract_scalar(msg, "$.remoteHostMetadata[0].ip"),
    _remote_port = json_extract_scalar(msg, "$.remoteHostMetadata[0].connections[0].port"),
    _remote_proto = json_extract_scalar(msg, "$.remoteHostMetadata[0].connections[0].ipProto"),
    _remote_app = json_extract_scalar(msg, "$.remoteHostMetadata[0].connections[0].app"),
    _remote_city = json_extract_scalar(msg, "$.remoteHostMetadata[0].cityName"),
    _remote_country = json_extract_scalar(msg, "$.remoteHostMetadata[0].countryCode"),
    _client_port = arrayindex(regextract(msg, "\"Client Port\"\s*,\s*\"value\"\s*:\s*(\d+)"), 0),
    _threat_id = arrayindex(regextract(msg, "\"Threat ID\"\s*,\s*\"value\"\s*:\s*(\d+)"), 0),
    _threat_category = arrayindex(regextract(msg, "\"Threat Category\"\s*,\s*\"value\"\s*:\s*\"([^\"]+)\""), 0),
    _threat_type = arrayindex(regextract(msg, "\"Threat Type\"\s*,\s*\"value\"\s*:\s*\"([^\"]+)\""), 0),
    _fw_name = arrayindex(regextract(msg, "\"Firewall Name\"\s*,\s*\"value\"\s*:\s*\"([^\"]+)\""), 0),
    _fw_action = arrayindex(regextract(msg, "\"Firewall Action\"\s*,\s*\"value\"\s*:\s*\"([^\"]+)\""), 0),
    _user_agent = arrayindex(regextract(msg, "\"user agent\"\s*,\s*\"value\"\s*:\s*\"([^\"]+)\""), 0),
    _fw_inbound_if = arrayindex(regextract(msg, "\"Firewall Inbound Interface\"\s*,\s*\"value\"\s*:\s*\"([^\"]+)\""), 0),
    _fw_outbound_if = arrayindex(regextract(msg, "\"Firewall Outbound Interface\"\s*,\s*\"value\"\s*:\s*\"([^\"]+)\""), 0),
    _transferred_file = arrayindex(regextract(msg, "\"Name of the Transferred File\"\s*,\s*\"value\"\s*:\s*\"([^\"]+)\""), 0),
    _hostname = coalesce(internal_hostname, hostname)
| alter
    xdm.alert.original_alert_id = id,
    xdm.alert.name = name,
    xdm.alert.description = description,
    xdm.alert.severity = severity,
    xdm.alert.category = coalesce(_threat_category, category),
    xdm.alert.subcategory = coalesce(_threat_type, _alert_type),
    xdm.alert.original_threat_id = coalesce(_threat_id, _rule_id),
    xdm.alert.original_threat_name = name,
    xdm.alert.source_url = url,
    xdm.alert.status = if(resolved = "true", XDM_CONST.ALERT_STATUS_DONE, XDM_CONST.ALERT_STATUS_PENDING),
    xdm.event.type = "ALERT",
    xdm.event.description = description,
    xdm.event.original_event_type = type,
    xdm.event.log_level = if(severityNumber = 4, XDM_CONST.LOG_LEVEL_ERROR, severityNumber = 3, XDM_CONST.LOG_LEVEL_WARNING, severityNumber = 2, XDM_CONST.LOG_LEVEL_WARNING, severityNumber = 1, XDM_CONST.LOG_LEVEL_INFORMATIONAL, XDM_CONST.LOG_LEVEL_NOTICE),
    xdm.event.outcome = if(resolved = "true", XDM_CONST.OUTCOME_SUCCESS, XDM_CONST.OUTCOME_UNKNOWN),
    xdm.observer.vendor = "Palo Alto Networks",
    xdm.observer.product = "IoT Security",
    xdm.observer.type = coalesce(_alert_source, "IoT Security"),
    xdm.observer.name = _fw_name,
    xdm.observer.action = _fw_action,
    xdm.source.ipv4 = coalesce(_fromip, json_extract_scalar(msg, "$.localip")),
    xdm.source.port = to_number(_client_port),
    xdm.source.user_agent = _user_agent,
    xdm.source.interface = _fw_inbound_if,
    xdm.source.host.hostname = if(_hostname ~= "^[0-9a-fA-F]{2}(:[0-9a-fA-F]{2}){5}$", null, _hostname),
    xdm.source.host.mac_addresses = if(_hostname ~= "^[0-9a-fA-F]{2}(:[0-9a-fA-F]{2}){5}$", arraycreate(_hostname), null),
    xdm.source.host.device_id = deviceid,
    xdm.source.host.device_category = coalesce(_local_category, profileCategory),
    xdm.source.host.device_model = coalesce(_local_profile, profile),
    xdm.target.ipv4 = coalesce(_toip, _remote_ip),
    xdm.target.port = to_number(coalesce(_remote_port, "")),
    xdm.target.interface = _fw_outbound_if,
    xdm.target.location.city = _remote_city,
    xdm.target.location.country = _remote_country,
    xdm.target.file.filename = _transferred_file,
    xdm.network.application_protocol = _remote_app,
    xdm.network.ip_protocol = _remote_proto;
```

### Validation Results

Tested against 10 production IoT Security alert rows covering three alert types:
- **Non-Standard User Agent** (IoT Security sourced, no firewall metadata)
- **Code Execution Vulnerability** (Firewall sourced, CVE data, threat ID)
- **Malicious ELF File Transfer** (Firewall sourced, file transfer metadata)

All 30+ XDM fields populated correctly. Zero validation errors from Cortex.

---

---

## Reference Example 2: AWS GuardDuty Data Model Rule

### Dataset: `aws_guardduty_generic_alert_raw`

A complex data model rule mapping AWS GuardDuty finding events to XDM. This rule demonstrates several advanced patterns:

- **Defensive coalesce(PascalCase, camelCase)** throughout to handle both field naming conventions from the XSIAM parser
- **Multi-stage extraction pipeline** (7 stages) with progressive field refinement
- **Directional IP/port resolution** for NETWORK_CONNECTION findings (INBOUND vs OUTBOUND)
- **XDM_CONST mapping chains** for HTTP method, HTTP response code, and identity type
- **Comprehensive user/identity mapping** across IAM, Kubernetes, RDS, and Runtime Monitoring source types
- **Transitive field usage** where intermediary fields feed into other intermediary fields before final XDM assignment
- **Array aggregation** for multi-source IP addresses from Kubernetes API calls and port probes

### Key Pattern: XDM_CONST Mapping Chains

When a source field value must be mapped to an XDM constant enumeration, use a full `if()` chain covering all possible values. The Cortex IDE validates that XDM constant fields receive only valid XDM_CONST values.

**HTTP Method (xdm.network.http.method)**:
```xql
xdm.network.http.method = if(
    http_verb = null, http_verb,
    http_verb = "GET", XDM_CONST.HTTP_METHOD_GET,
    http_verb = "POST", XDM_CONST.HTTP_METHOD_POST,
    http_verb = "PUT", XDM_CONST.HTTP_METHOD_PUT,
    // ... all 35+ HTTP methods ...
    uppercase(http_verb))  // fallback: uppercase the raw value
```

**HTTP Response Code (xdm.network.http.response_code)**:
```xql
xdm.network.http.response_code = if(
    http_code = null, null,
    http_code = 200, XDM_CONST.HTTP_RSP_CODE_OK,
    http_code = 201, XDM_CONST.HTTP_RSP_CODE_CREATED,
    http_code = 302, XDM_CONST.HTTP_RSP_CODE_FOUND,
    // ... all 50+ HTTP status codes ...
    service_action_k8s_api_call_status_code)  // fallback: raw value
```

### Key Pattern: Identity Type Mapping (XDM_CONST.IDENTITY_TYPE_*)

When mapping vendor-specific user types to XDM identity classifications, use an `if()` chain that maps each known value to the appropriate XDM_CONST. The available identity types are: `MACHINE`, `USER`, `BUILTIN`, `VIRTUAL`, `UNKNOWN`.

**IAM UserType to XDM Identity Type**:
```xql
xdm.source.user.identity_type = if(
    resource_user_type = "Root", XDM_CONST.IDENTITY_TYPE_BUILTIN,         // Built-in account
    resource_user_type = "IAMUser", XDM_CONST.IDENTITY_TYPE_USER,         // Human user
    resource_user_type = "AssumedRole", XDM_CONST.IDENTITY_TYPE_MACHINE,  // Service/automation
    resource_user_type = "FederatedUser", XDM_CONST.IDENTITY_TYPE_VIRTUAL, // Federated identity
    resource_user_type = "AWSAccount", XDM_CONST.IDENTITY_TYPE_MACHINE,   // Cross-account
    resource_user_type = "AWSService", XDM_CONST.IDENTITY_TYPE_MACHINE,   // AWS service
    resource_user_type = "Directory", XDM_CONST.IDENTITY_TYPE_USER,       // Directory user
    resource_user_type != null, XDM_CONST.IDENTITY_TYPE_UNKNOWN)          // Fallback
```

This pattern is reusable for any vendor that provides user/identity type classifications (e.g. Azure AD account types, GCP IAM principal types, Okta user types).

### Key Pattern: Comprehensive User/Identity Mapping

For data sources with multiple identity contexts (IAM, Kubernetes, database, OS process), map each context to the appropriate `xdm.source.user.*` and `xdm.target.user.*` fields:

| XDM Field | IAM Context | K8s Context | RDS Context | Runtime Context |
|---|---|---|---|---|
| `xdm.source.user.username` | IAM UserName | K8s Username | RDS login user | OS process user |
| `xdm.source.user.identifier` | PrincipalId, AccessKeyId | K8s UID | -- | OS user ID |
| `xdm.source.user.domain` | AWS account ID | K8s namespace | AWS account ID | -- |
| `xdm.source.user.ou` | -- | K8s namespace | -- | -- |
| `xdm.source.user.roles` | Instance profile ARN | K8s role binding | -- | -- |
| `xdm.source.user.identity_type` | UserType mapped | -- | -- | -- |
| `xdm.target.user.username` | -- | -- | RDS login user / DB instance ID | -- |
| `xdm.target.user.identifier` | -- | -- | DB instance ARN | -- |

Use `coalesce()` chains to select the most specific value available, with fallbacks ordered by priority.

### Key Pattern: Transitive Field Usage

Intermediary fields may feed into other intermediary fields before ultimately reaching an XDM assignment. The Cortex IDE validates that ALL intermediary fields are eventually consumed.

```xql
// Stage 4: Extract intermediary
http_code = to_integer(service_action_k8s_api_call_status_code)

// Stage 7: Map to XDM (http_code is consumed here)
xdm.network.http.response_code = if(http_code = null, null, http_code = 200, XDM_CONST.HTTP_RSP_CODE_OK, ...)
```

If `http_code` were extracted but NOT mapped to any XDM field, the Cortex IDE would reject the rule with: "Data Model validation error - Data Model Rules contains unused fields: http_code".

### Validation Results

Tested against 397 production GuardDuty sample events spanning:
- **6 action types**: AWS_API_CALL, NETWORK_CONNECTION, DNS_REQUEST, KUBERNETES_API_CALL, PORT_PROBE, RDS_LOGIN_ATTEMPT
- **17 resource types**: Instance, AccessKey, S3Bucket, EKSCluster, ECSCluster, Lambda, Container, RDS, and more
- **4 severity bands**: Low (1.0-3.9), Medium (4.0-6.9), High (7.0-8.9), Critical (9.0+)

All 71 XDM fields populated correctly across 119 intermediary field extractions (342 lines). Zero validation errors. Zero unused field warnings.

The full rule is at: `PRIVATE_DOCS/aws_guardduty_xdm_model_rule.xql`

---

## See Also

- [Parsing Rule Building Guide](parsing_rule_building_guide.md) -- end-to-end guide for building INGEST rules (the upstream step before data model rules)
- [Rules Engine Reference](rules_engine_reference.md) -- full documentation of all 59 validation rules

### Additional Pitfall: `parse_epoch` vs `from_epoch`

When setting `_time` from epoch values, always use `parse_epoch(string_field, "MILLIS")`:
- `from_epoch` does NOT exist in XQL -- it will trigger ERR-007 (unknown function)
- `parse_epoch` expects a STRING argument -- do NOT wrap in `to_integer()`
- `json_extract_scalar` already returns a string, so pass its output directly

### Additional Pitfall: Unused Intermediary Fields (BLOCKING ERROR)

Every non-underscore-prefixed field extracted in an `alter` block MUST be referenced in a subsequent `xdm.*` assignment (directly or transitively). The Cortex IDE treats this as a **blocking validation error** -- the rule will not save. The error message is: `Data Model Rules contains unused fields: "field_name"`.

This applies to both `_raw` and `_gc_raw` datasets. It is NOT just a warning -- it is a hard block.

This is caught by WARN-019 in the rules engine. Given the Cortex IDE treats this as a blocking error, WARN-019 severity should be considered equivalent to an error.

Common causes:
- Extracting a field for debugging but forgetting to remove it
- Renaming a field but not updating the XDM assignment
- Extracting HTTP verb/code but not adding the XDM_CONST mapping chain
- Removing an XDM field assignment without also removing the intermediary field(s) that fed it

### Additional Pitfall: Terminal Semicolon and Trailing Commas

- Every rule block MUST end with a semicolon (`;`) -- caught by ERR-009
- The last field assignment before the semicolon must NOT have a trailing comma -- caught by ERR-010
- Common cause: deleting or reordering the last field in a comma-separated assignment list

---

## Known XDM Field Compatibility Issues

Not all XDM fields defined in the Cortex XDM reference are available on every dataset's data model. Attempting to map an unavailable field can cause the Cortex IDE to return an opaque "internal error" rather than a clean validation message.

### Root Cause Analysis

After two full rounds of binary search debugging (isolating failures from 50+ field rules down to individual fields), three distinct failure categories have been identified:

**Category 1: Non-Existent XDM Fields**
Fields that do not exist in the XDM schema at all (no entry in `xdm-schema.ts`). These always fail on every dataset with an "internal error". The Cortex IDE does not produce a helpful "field not found" message -- it simply crashes the validator.
- Example: `xdm.source.process.parent_process.*` -- these paths look plausible but the XDM schema has no `parent_process` child object under `process`.
- Prevention: Always cross-reference every field path against `xdm-schema.ts` before writing any mapping. Use the schema check command in the "Mandatory Pre-Mapping Validation" section.

**Category 2: Dataset-Incompatible Fields**
Fields that exist in the XDM schema but are not part of the selected data model for a specific dataset. These produce a cleaner error: "not part of the selected data model".
- Example: `xdm.network.direction` on `_gc_raw` datasets.
- Example: `xdm.session_context_id` on `_gc_raw` datasets.
- Prevention: There is no way to know this in advance without testing. Use the binary search methodology to isolate.

**Category 3: XDM_CONST Enum Mapping Crashes**
Fields that use `XDM_CONST.*` enumeration constants in `if()` or `arraymap()` chains crash the Cortex IDE validator with a generic "internal error" on `_gc_raw` datasets. The field path itself is valid and exists in the schema, but the validator cannot handle the constant-mapping pattern.
- Example: `xdm.alert.mitre_techniques` with `arraymap()` + `XDM_CONST.MITRE_TECHNIQUE_*` (hundreds of constants).
- Example: `xdm.target.process.integrity_level` with `if()` + `XDM_CONST.INTEGRITY_LEVEL_*`.
- Counter-example: `xdm.alert.mitre_tactics` with `arraymap()` + `XDM_CONST.MITRE_TACTIC_*` WORKS. The tactics enum set is smaller than techniques -- this may be related, or the field itself may simply be included in the data model whilst techniques is not.
- Prevention: Test any `XDM_CONST` mapping chain individually on your target dataset before adding it to a full rule. These are the most common cause of the opaque "internal error".

**Key Insight**: The "internal error" message from Cortex IDE is not a single root cause -- it is the generic fallback for at least three distinct problems. The binary search methodology is essential because the IDE provides no field-level error detail for any of these categories.

### Confirmed Incompatible Fields

| XDM Field | Confirmed On | Behaviour | Date |
|---|---|---|---|
| `xdm.alert.mitre_techniques` | `trend_micro_vision_one_gc_raw` | Cortex IDE returns "There was an internal error while trying to validate mapping" -- no clean field-level error. The `arraymap()` + `XDM_CONST.MITRE_TECHNIQUE_*` chain causes the validator to crash. | 2026-03-09 |
| `xdm.network.direction` | `trend_micro_vision_one_gc_raw` | Not part of the selected data model. | 2026-03-09 |
| `xdm.source.process.parent_process.name` | ALL datasets | Field does not exist in the XDM schema at all (no entry in xdm-schema.ts). Causes Cortex IDE internal error. | 2026-03-09 |
| `xdm.source.process.parent_process.pid` | ALL datasets | Field does not exist in the XDM schema at all (no entry in xdm-schema.ts). Causes Cortex IDE internal error. | 2026-03-09 |
| `xdm.source.process.parent_process.command_line` | ALL datasets | Field does not exist in the XDM schema at all (no entry in xdm-schema.ts). Causes Cortex IDE internal error. | 2026-03-09 |
| `xdm.session_context_id` | `trend_micro_vision_one_gc_raw` | Causes internal error on _gc_raw datasets. Field exists in XDM schema but is incompatible with this dataset. | 2026-03-09 |
| `xdm.target.process.integrity_level` | `trend_micro_vision_one_gc_raw` | Cortex IDE returns "There was an internal error while trying to validate mapping". The `if()` chain with `XDM_CONST.INTEGRITY_LEVEL_*` constants causes the validator to crash. Isolated via binary search V3 -> V3A -> V3A3. | 2026-03-09 |

### Unaffected Related Fields

| XDM Field | Status | Notes |
|---|---|---|
| `xdm.alert.mitre_tactics` | Works | Full `arraymap()` + `XDM_CONST.MITRE_TACTIC_*` chain validated on `_gc_raw` |
| `xdm.network.application_protocol` | Works | String assignment validated |
| `xdm.network.http.url` | Works | String assignment validated |

### Mandatory Pre-Mapping Validation

Before writing any XDM field assignment in a model rule, **every field path must be cross-referenced against `server/data/xdm-schema.ts`**. This is the local source of truth for which XDM fields exist.

A field that does not appear in `xdm-schema.ts` does not exist in the XDM schema and will cause an internal error in the Cortex IDE. This is distinct from a field that exists in the schema but is not available on a specific dataset's data model (which also causes errors, but must be discovered through testing).

Quick check command:
```bash
grep -oP 'xdm\.[a-z_.]+(?=\s*=)' <rule_file>.xql | sort -u | while read f; do
  grep -q "\"$f\"" server/data/xdm-schema.ts || echo "NOT IN SCHEMA: $f"
done
```

### Untested Fields on `_gc_raw` (Binary Search Candidates)

The following XDM fields were originally untested. After binary search isolation, the following have been confirmed:

**Confirmed WORKING** (validated individually via V3A1, V3A2, V3B binary search versions):
- `xdm.target.process.name` -- V3A1 PASS
- `xdm.target.process.executable.path` -- V3A2 PASS
- `xdm.target.process.pid` -- in V3B group (V3B not yet tested individually but V3A isolated the failure)
- `xdm.target.user.username` -- in V3B group

**Confirmed INCOMPATIBLE** (moved to table above):
- `xdm.target.process.integrity_level` -- V3A3 FAIL

**Still untested individually** (passed as part of V1 or V2 batch but not isolated):
- `xdm.network.dns.dns_question.name`
- `xdm.source.application.name`
- `xdm.source.host.os`
- `xdm.source.host.os_family`
- `xdm.source.user.user_type`
- `xdm.target.process.command_line`

### Debugging Methodology: Binary Search for Data Model Errors

When the Cortex IDE returns "internal error" on a model rule, use this approach to isolate the offending field:

1. **Start minimal** -- create a rule with only the `[MODEL:]` header, filter, and 3-5 basic XDM fields (e.g. `xdm.observer.vendor`, `xdm.event.id`). Confirm it saves.
2. **Add fields in batches** -- create 3-4 progressive versions, each adding a category of fields (observer, event, alert, source, target, network). Save each version.
3. **Binary search the failing batch** -- when a version fails, split its new fields into halves and test each half independently.
4. **Isolate the single field** -- continue halving until you identify the exact field causing the crash.

This was used to isolate `xdm.alert.mitre_techniques` from a 50-field rule across 10 test iterations (V1 -> V2 -> V3 -> V3A/B/C -> V3C1/C2 -> V3C1A/C1B).

### Standard Practice: Preserving the `source` Filter Value

Both Trend Micro Vision One rules use `filter source = "endpointActivityData"` or `filter source = "detections"` to select log subtypes. This `source` field value must be preserved in the data model so downstream queries and dashboards can identify the original log type.

The correct XDM mapping is:
```
xdm.event.original_event_type = source,
```

This is distinct from `xdm.event.type` which should hold a normalised event category (e.g. `"ENDPOINT_ACTIVITY"`, `"ALERT"`). Both should be set in every model rule.

### Rules Engine Coverage

- **WARN-023** flags usage of `xdm.alert.mitre_techniques` in model rules with a data model compatibility warning.
- **WARN-024** flags usage of `xdm.target.process.integrity_level` in model rules (XDM_CONST enum mapping crash on `_gc_raw`).
- **WARN-025** flags usage of `xdm.session_context_id` in model rules (incompatible on `_gc_raw` datasets).
- **WARN-026** flags usage of `xdm.network.direction` in model rules (not part of selected data model on `_gc_raw`).
- **WARN-027** flags usage of `xdm.source.process.parent_process.*` (fields do not exist in XDM schema).
- **WARN-028** flags model rules that filter on `source` but do not map `xdm.event.original_event_type` (ensures the source value is preserved).
- **ERR-011** flags self-referencing XDM fields in assignments (e.g. `xdm.target.ipv4 = coalesce(xdm.target.ipv4, _fallback)`).
- **INFO-011** suggests mirroring source/target fields when only one side is mapped (ipv4, user.username).
- Future incompatible fields should be added to this table AND to the rules engine as new WARN rules.
