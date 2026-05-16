# GoCortex BBWAF -- Pack Documentation

Companion notes for `parser.xql` and `datamodel.xql`.

## What this pack covers

Maps GoCortex BBWAF (Broken Bank Web Application Firewall)
detection events into the Cortex XDM schema. Each event records a
single inbound HTTP request that matched one of the 36 documented
vulnerability classes (OWASP Top 10 + extended CWE coverage).
Stream 2 of 4 in the GoCortex Broken Bank 1.5.0 SIEM contract.

Source-of-truth for the wire format and sample payloads:
`attached_assets/Pasted--GoCortex-Broken-Ban-1777803533165_1777803533165.txt`,
section labelled `netbank_application`. The producer ships compact
JSON records to a Cortex HTTP collector
(`https://api-MYTENANT.xdr.au.paloaltonetworks.com/logs/v1/event`),
one record per line; the entire JSON object lands in `_raw_log`
and the parser / datamodel pull fields with `json_extract_scalar`.

## Wire format

Single-line JSON per record. Documented fields:

| Field             | Type    | Notes                                              |
| ----------------- | ------- | -------------------------------------------------- |
| `event_id`        | string  | Stable per-detection id; mirrored as alert id.     |
| `timestamp`       | ISO8601 | Drives `_time`.                                    |
| `source_ip`       | string  | Offender IPv4; literal `"unknown"` collapsed.      |
| `vulnerability`   | string  | One of 36 OWASP / CWE classes.                     |
| `endpoint`        | string  | Logical endpoint label.                            |
| `request_path`    | string  | Concrete URL path on the wire.                     |
| `query_string`    | string  | Optional; appended to URL.                         |
| `request_method`  | string  | HTTP verb (closed set).                            |
| `user_agent`      | string  | UA header; `"unknown"` collapsed.                  |
| `payload`         | string  | Malicious payload text, truncated to 1000 chars.   |
| `severity`        | string  | `low` / `medium` / `high` / `critical`.            |
| `action`          | string  | `blocked` / `monitored` / `allowed`.               |

## Sample payloads

SQL injection blocked by the WAF:

```json
{
  "event_id": "bbwaf-2026-05-03-000123",
  "timestamp": "2026-05-03T12:34:56.789Z",
  "source_ip": "203.0.113.42",
  "vulnerability": "SQL_INJECTION",
  "endpoint": "/api/v1/accounts/search",
  "request_path": "/api/v1/accounts/search",
  "query_string": "q=' OR 1=1 --",
  "request_method": "GET",
  "user_agent": "sqlmap/1.7.2#stable",
  "payload": "q=' OR 1=1 --",
  "severity": "high",
  "action": "blocked"
}
```

Cross-site scripting attempt against the comment endpoint
(taken verbatim from the source-of-truth attached asset):

```json
{
  "timestamp": "2026-05-03T14:22:32.108214+00:00",
  "vendor": "GoCortex",
  "product": "BBWAF",
  "event_type": "security_detection",
  "endpoint": "/comment",
  "vulnerability": "CROSS_SITE_SCRIPTING",
  "payload": "comment=%3Cscript%3Ealert%281%29%3C%2Fscript%3E",
  "source_ip": "198.51.100.7",
  "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
  "request_method": "GET",
  "request_path": "/comment",
  "query_string": "comment=%3Cscript%3Ealert%281%29%3C%2Fscript%3E"
}
```

## Anchors

The parser stamps four anchor columns on every row; the datamodel
reads them via the keep-in-both `coalesce(<parser column>,
json_extract_scalar(_raw_log, ...))` pattern from
`PRIVATE_DOCS/anchor_field_design.md` (Task #100):

| Anchor              | XDM target                        | Notes |
| ------------------- | --------------------------------- | ----- |
| `_source_ip`        | `xdm.source.ipv4` (via tmp guard) | Producer occasionally writes literal `"unknown"`; collapsed to null. |
| `_vulnerability`    | `xdm.alert.category`, `xdm.alert.original_threat_name`, `xdm.event.description` | OWASP / CWE class label, used verbatim as the alert taxonomy. |
| `_endpoint`         | `xdm.target.resource.name`        | Logical endpoint label (e.g. `/api/v1/accounts/search`). |
| `_request_method`   | `xdm.network.http.method`         | Mapped through an `XDM_CONST.HTTP_METHOD_*` if-chain. |

## XDM coverage

Anchor-derived (keep-in-both):

- `_source_ip`       -> `xdm.source.ipv4`
- `_vulnerability`   -> `xdm.alert.category` (mapped to XDM_CONST.THREAT_CATEGORY_* via 36-value if-chain), `xdm.alert.original_threat_name`
- `_endpoint`        -> `xdm.target.resource.name`
- `_request_method`  -> `xdm.network.http.method` (XDM_CONST.HTTP_METHOD_* whitelist GET/POST/PUT/DELETE/HEAD/OPTIONS/PATCH; unknown -> null)

Secondary fields (pulled at model time via `json_extract_scalar`):

- `user_agent`     -> `xdm.source.user_agent` (`"unknown"` -> null collapse)
- `query_string`   -> appended to `xdm.network.http.url` as `endpoint?query` (XDM has no dedicated `url_query` path)
- `payload`        -> `xdm.event.description` (the malicious payload text, truncated at 1000 chars by the producer)
- `severity`       -> `xdm.alert.severity`
- `action`         -> `xdm.event.outcome_reason` (e.g. `blocked`, `monitored`)
- `event_id`       -> `xdm.event.id`, `xdm.alert.original_alert_id`

Static / synthesised:

- `xdm.observer.vendor / product`  -> `"GoCortex" / "BBWAF"`
- `xdm.event.type`                 -> `"SECURITY_DETECTION"`
- `xdm.event.outcome`              -> `XDM_CONST.OUTCOME_FAILED` (every BBWAF record is by definition a security control firing on a known-vulnerable endpoint; the underlying HTTP transaction often still returned a 200, so `xdm.network.http.response_code` is intentionally not populated -- modelling outcome from the HTTP status would routinely flip the alert to `success`)

## On the `baselines/` folder

The `baselines/` directory is a living mirror of the current pack
plus its analyser output, refreshed whenever `parser.xql` or
`datamodel.xql` changes materially. It is not a frozen historical
snapshot. Three files are kept in lock-step with the live rules:

- `gocortex_bbwaf_xdm_model_rule.xql` -- byte-for-byte copy of
  `../datamodel.xql` at the time of the last refresh. Diff target
  for PR review and the canonical input for the analyser baseline.
- `gocortex_bbwaf_xdm_model_rule.json` -- response from
  `POST /api/analyse` with `ruleType: "modeling"`, pretty-printed.
  Pins the analyser's expected verdict (score, summary counts,
  every violation) so any inadvertent regression in the analyser
  surfaces as a baseline diff in CI.
- `gocortex_bbwaf_parser.json` -- the same analyser output for
  `../parser.xql` with `ruleType: "parsing"`.
- `sample_logs.txt` -- a small set of representative `_raw_log`
  rows lifted directly from the source-of-truth attached asset.

If you change either rule, refresh all four files in the same
commit. The current analyser baseline is score 99 with one INFO-011
hit (WAF records do not carry an upstream / destination IP, so
`xdm.source.ipv4` is mapped without a corresponding
`xdm.target.ipv4`).
