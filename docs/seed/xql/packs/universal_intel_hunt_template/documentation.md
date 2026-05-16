# Universal Threat Intel Hunt Template -- Documentation

Companion notes for `hunt_query.xql`.

This pack ships an XQL hunt template, **not** a data model rule. It is
intentionally excluded from the `datamodel.xql` regression baselines for
that reason.

## Placeholder notation

The template's documentation header and the Step 1 prose write
placeholder names with `\` separators (e.g. `%\%INDICATOR_TYPE%\%`) so
that Spellbook's `%%...%%` substitution engine does not rewrite the
explanatory text while filling in the live query body. Strip the `\`
characters when reading. The XQL body itself uses the normal
`%%PLACEHOLDER%%` form so substitution proceeds as usual.

## Scope

This template matches events from any data source against the Cortex
XSIAM threat intelligence (`indicators`) dataset. It supports seven
hunt types:

| Hunt type        | `%\%INDICATOR_TYPE%\%` | `%\%MATCH_FIELD%\%`                              | Typical sources |
| ---------------- | ---------------------- | ------------------------------------------------ | --------------- |
| IP address       | `"IP"`                 | `source_ipv4` or `target_ipv4`                   | Firewall, proxy, NDR |
| Domain           | `"Domain"`             | `target_domain`                                  | DNS, proxy, web filter |
| File hash SHA256 | `"FileHash-SHA256"`    | `file_hash_sha256`                               | EDR, sandbox, email gateway |
| File hash MD5    | `"FileHash-MD5"`       | `file_hash_md5`                                  | EDR, sandbox, email gateway |
| Username         | `"Username"`           | `source_user_username` or `target_user_username` | Okta, Azure AD, Duo, Active Directory |
| URL              | `"URL"`                | `target_url`                                     | Proxy, web filter, CASB |
| Software         | `"SOFTWARE"`           | `software_package_purl`                          | SBOM, SCA, SAST |

Both `%\%INDICATOR_TYPE%\%` and `%\%MATCH_FIELD%\%` interpolate into
`IN (...)` lists, so a single-type / single-field hunt and a multi-type
/ multi-field hunt share one query shape.

## How to adapt this template

### Step 1: Set the four placeholders

| Placeholder            | Meaning |
| ---------------------- | ------- |
| `%\%LOOKBACK%\%`       | Retro-hunt period (e.g. `30d`, `7d`, `24h`) |
| `%\%DATASET%\%`        | Source dataset (e.g. `panw_ngfw_traffic_raw`) |
| `%\%INDICATOR_TYPE%\%` | One or more indicator types from the table above (comma separated) |
| `%\%MATCH_FIELD%\%`    | One or more intermediary field names to join on (comma separated) |

### Step 2: Update `%%SOURCE_FIELDS%%`

Use the raw field names from your data source. These are the
product-specific column names you want to pull through. Only list the
fields your source actually provides.

### Step 3: Update the FIELD MAPPING section (Section B)

Map each raw source field to the correct intermediary name. Set any
field your source does not provide to `null` (it is already `null` by
default). Only uncomment the filter sections relevant to your hunt
type.

## Source field examples (for `%%SOURCE_FIELDS%%`)

- **PANW Traffic**:
  `session_end_reason, rule_matched, _reporting_device_name, users, source_ip, source_port, dest_ip, dest_port, action, app, protocol, _time`
- **Okta System Log** (often via JSON extraction):
  `actor.displayName, actor.alternateId, client.ipAddress, client.userAgent.rawUserAgent, outcome.result, outcome.reason, eventType, target.0.displayName, _time`
- **CrowdStrike Falcon**:
  `UserName, SourceEndpointIpAddress, DestinationIpAddress, DestinationPort, SHA256HashData, MD5HashData, FileName, ComputerName, _time`
- **Cisco Umbrella (DNS)**:
  `InternalIp, ExternalIp, Domain, Action, QueryType, ResponseCode, Identity, _time`
- **Generic Proxy / Web Filter**:
  `src_ip, dst_ip, dst_port, url, domain, user, action, http_method, _time`
- **Software / SBOM (SCA, SAST)**:
  `package_version, package_purl, repository_name, asset_type_name, asset_provider, asset_name`

## Output schema / XDM mapping reference

Every output column from the `comp` stage maps to a known XDM field
path (or is preserved as metadata). This table is the specification
for the future `intelmatch_gc_raw` data model rule.

| Output column                  | XDM target field                   | Notes |
| ------------------------------ | ---------------------------------- | ----- |
| `_time`                        | `xdm.event.timestamp`              | Stamped with `current_time()` at match |
| `event_time`                   | (metadata)                         | Preserved original event `_time` |
| `source_ipv4`                  | `xdm.source.ipv4`                  | Source IP address |
| `source_ipv6`                  | `xdm.source.ipv6`                  | Source IPv6 address |
| `source_port`                  | `xdm.source.port`                  | Source port |
| `target_ipv4`                  | `xdm.target.ipv4`                  | Destination IP address |
| `target_ipv6`                  | `xdm.target.ipv6`                  | Destination IPv6 address |
| `target_port`                  | `xdm.target.port`                  | Destination port |
| `network_application_protocol` | `xdm.network.application_protocol` | Application-layer protocol (HTTP, DNS, SSL) |
| `action_protocol`              | `xdm.network.ip_protocol`          | Network-layer protocol (TCP, UDP, ICMP) |
| `target_domain`                | `xdm.target.domain`                | Queried / accessed domain |
| `target_url`                   | `xdm.target.url`                   | Full URL accessed |
| `source_user_username`         | `xdm.source.user.username`         | Initiating user |
| `source_user_domain`           | `xdm.source.user.domain`           | Initiating user domain |
| `target_user_username`         | `xdm.target.user.username`         | Target user (priv esc, etc.) |
| `target_user_domain`           | `xdm.target.user.domain`           | Target user domain |
| `auth_method`                  | `xdm.auth.auth_method`             | Authentication method (MFA, etc.) |
| `auth_outcome`                 | `xdm.event.outcome`                | Auth result (success / failure) |
| `event_type`                   | `xdm.event.type`                   | Event type (e.g. Okta `eventType`) |
| `file_hash_sha256`             | `xdm.target.file.sha256`           | File SHA-256 hash |
| `file_hash_md5`                | `xdm.target.file.md5`              | File MD5 hash |
| `software_package_version`     | (metadata)                         | Software package version |
| `software_package_purl`        | (metadata)                         | Package URL (purl) identifier |
| `software_repository_name`     | (metadata)                         | Source repository name |
| `software_asset_type_name`     | (metadata)                         | Asset type classification |
| `software_asset_provider`      | (metadata)                         | Asset provider / vendor |
| `software_asset_name`          | (metadata)                         | Software asset name |
| `observer_name`                | `xdm.observer.name`                | Reporting device / sensor |
| `observer_action`              | `xdm.observer.action`              | Action taken by the device |
| `network_rule`                 | `xdm.network.rule`                 | Rule / policy that matched |
| `network_session_reason`       | `xdm.event.outcome_reason`         | Session end / outcome reason |
| `matched_dataset`              | (metadata)                         | Source dataset name |
| `matched_timeframe`            | (metadata)                         | Look-back period used |
| `matched_field`                | (metadata)                         | Which field(s) were matched. Scalar string for single-field hunts (e.g. `"target_ipv4"`); `+`-joined string when multiple fields participate (e.g. `"target_domain+target_ipv4"`) |
| `indicator_type`               | (from indicators)                  | Indicator type (IP, Domain, etc.) |
| `indicator_verdict`            | (from indicators)                  | Indicator verdict (Malicious, etc.) |
| `indicator_tags`               | (from indicators)                  | Indicator tags / context |
| `count`                        | (aggregation)                      | Number of matching events |

## Section-by-section reference

The body of the template is divided into sections A through F. Edit
each section as documented inside the template itself; the per-section
notes below restate the intent so the file body can stay terse.

- **Section A -- DATA SOURCE AND FIELD SELECTION.** First
  `config timeframe` sets the data source look-back period (your
  retro-hunt period). Then select the raw fields from your data source
  via `| fields %%SOURCE_FIELDS%%`. An optional commented block shows
  how to pre-narrow noisy nested-payload sources (Microsoft
  Defender-style `category` filter plus `json_extract_scalar` lifts on
  the `properties` blob); uncomment when the source ships every
  telemetry sub-table inside one dataset.
- **Section B -- FIELD MAPPING.** Map raw source field names to the
  standardised intermediary names (see the output schema table above).
  Set any field your source does not provide to `null` (already null
  by default). When a single source scalar represents an address that
  may be either IPv4 or IPv6 (most logs do not pre-classify), assign
  the same scalar to both `source_ipv4` and `source_ipv6` (likewise on
  the target side); Section C splits the two by regex. This
  `v4 = v6 = same scalar` idiom is intentional, not a copy-paste
  error.
- **Section C -- DATA QUALITY FILTERS.** Uncomment only the sections
  you need.
  - *IP address validation*: ensure the data is cleaned up before
    presenting fields to functions such as `is_known_private_ipv4`,
    especially for long-term look-backs (CRTX-231221). The template
    ships **two** topology-filter variants side by side; pick ONE:
    - **(a) Bidirectional (NGFW)** -- private source AND public
      target. Suits network-flow sources where source IPs may
      legitimately be public (perimeter ingress, reflected rejects).
    - **(b) Target-only (EDR / proxy / DNS)** -- public target only.
      Suits sources where the source is always an internal asset and
      only the target is interesting for indicator matching.
  - *Domain validation*: strip trailing dots from FQDN notation and
    exclude internal domains.
  - *Username validation*: exclude service accounts or empty
    usernames.
  - *File hash validation*: ensure hashes are well-formed.
- **Section D -- THREAT INTELLIGENCE JOIN.** `type = inner` specifies
  an inner join, returning only records with matching values in both
  datasets. `conflict_strategy = left` resolves field name conflicts
  when joining datasets with overlapping field names. The second
  `config` sets the indicator (your threat-intel source) look-back. If
  you are running daily, you only need to use the last 24h of changed
  intel data. Both `type` and `tim_threat_intel.value` use `IN (...)`
  so single-type and multi-type hunts share one shape. The sub-query
  pulls `tags` so the comp stage can output `indicator_tags`.
- **Section E -- TIMESTAMP AND METADATA.** Preserve the original event
  time then stamp with current time. Without this the matched results
  inherit the dataset `_time` and appear backdated. `matched_field` is
  a scalar string for single-field hunts (e.g. `"target_ipv4"`) and a
  `+`-joined string for multi-field hunts (e.g.
  `"target_domain+target_ipv4"`).
- **Section F -- AGGREGATION AND OUTPUT.** Aggregate matched events.
  All field names are standardised intermediary names that map
  directly to XDM paths (see the output schema table above).
