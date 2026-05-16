# GoCortex BrokenBank Auth -- Pack Documentation

Companion notes for `parser.xql` and `datamodel.xql`.

## What this pack covers

Maps GoCortex BrokenBank NetBank authentication events into the
Cortex XDM schema. Each event records a single user login attempt
against the BrokenBank web application: success, failure (with a
typed reason), or simulated background traffic. Stream 3 of 4 in
the GoCortex Broken Bank 1.5.0 SIEM contract.

Source-of-truth for the wire format and sample payloads:
`attached_assets/Pasted--GoCortex-Broken-Ban-1777803533165_1777803533165.txt`,
section labelled `netbank_auth`. The producer ships compact JSON
records to a Cortex HTTP collector
(`https://api-MYTENANT.xdr.au.paloaltonetworks.com/logs/v1/event`),
one record per line; the entire JSON object lands in `_raw_log`
and the parser / datamodel pull fields with `json_extract_scalar`.

## Wire format

Single-line JSON per record. Documented fields:

| Field             | Type    | Notes                                              |
| ----------------- | ------- | -------------------------------------------------- |
| `event_id`        | string  | Stable per-attempt id; mirrored as `xdm.event.id`. |
| `timestamp`       | ISO8601 | Drives `_time`.                                    |
| `username`        | string  | NetBank login id.                                  |
| `status`          | string  | `success` / `failure`.                             |
| `failure_reason`  | string  | Typed cause when `status = failure`.               |
| `source_ip`       | string  | Offender IPv4; literal `"unknown"` collapsed.      |
| `country`         | string  | ISO-3166-1 alpha-2 country code.                   |
| `device_type`     | string  | `desktop` / `mobile` / `unknown`.                  |
| `user_agent`      | string  | UA header; `"unknown"` collapsed.                  |
| `simulated`       | string  | `"true"` for Faker-driven background traffic.      |

## Sample payloads

Failed mobile login from GB:

```json
{
  "event_id": "auth-2026-05-03-000456",
  "timestamp": "2026-05-03T12:34:56.789Z",
  "username": "alice",
  "status": "failure",
  "failure_reason": "invalid_password",
  "source_ip": "198.51.100.7",
  "country": "GB",
  "device_type": "mobile",
  "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) ...",
  "simulated": "false"
}
```

Synthetic background traffic (Faker):

```json
{
  "event_id": "auth-2026-05-03-000457",
  "timestamp": "2026-05-03T12:34:58.111Z",
  "username": "bob",
  "status": "success",
  "source_ip": "203.0.113.42",
  "country": "AU",
  "device_type": "desktop",
  "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64) ...",
  "simulated": "true"
}
```

## Anchors

The parser stamps six anchor columns; the datamodel reads them
via the keep-in-both `coalesce(<parser column>,
json_extract_scalar(_raw_log, ...))` pattern from
`PRIVATE_DOCS/anchor_field_design.md` (Task #100):

| Anchor          | XDM target                              | Notes |
| --------------- | --------------------------------------- | ----- |
| `_username`     | `xdm.source.user.username`              | NetBank login id. |
| `_status`       | drives `xdm.event.outcome` if-chain     | `success` / `failure`; anything else lands as `OUTCOME_UNKNOWN`. |
| `_source_ip`    | `xdm.source.ipv4` (via tmp guard)       | Producer writes literal `"unknown"` when GeoIP lookup fails; collapsed to null. |
| `_country`      | `xdm.source.location.country`           | ISO-3166-1 alpha-2 code; auto-enriched downstream by Cortex. |
| `_device_type`  | `xdm.source.host.device_category`       | Producer-side UA classification (`desktop`, `mobile`, `unknown`). NOT placed into `xdm.network.http.browser` -- per WARN-031 that field is reserved for the declared browser name. |
| `_simulated`    | drives `xdm.event.tags`                 | Boolean. `true` rows are Faker-driven background traffic; tag-only -- only `true` emits `arraycreate("simulated")`, `false` and unparseable both yield NULL. |

## XDM coverage

Anchor-derived (keep-in-both):

- `_username`        -> `xdm.source.user.username`
- `_status`          -> drives `xdm.event.outcome` (`success` -> SUCCESS, `failure` -> FAILED, else UNKNOWN)
- `_source_ip`       -> `xdm.source.ipv4`
- `_country`         -> `xdm.source.location.country`
- `_device_type`     -> `xdm.source.host.device_category`
- `_simulated`       -> `xdm.event.tags = if(_simulated = true, arraycreate("simulated"), null)` (tag-only; absence of the tag is the signal for real traffic; mislabelling unknown rows as `"real"` would corrupt detection-author noise filters; the populated branch uses `arraycreate` so the typed Array shape is preserved per WARN-020 / WARN-030 / WARN-035)

Secondary fields (pulled at model time):

- `user_agent`     -> `xdm.source.user_agent` (`"unknown"` collapse)
- `failure_reason` -> `xdm.event.outcome_reason` (e.g. `invalid_password`, `account_locked`, `mfa_required`)
- `event_id`       -> `xdm.event.id` (falls back to `_id`)

Static / synthesised:

- `xdm.observer.vendor / product`  -> `"GoCortex" / "BrokenBank"`
- `xdm.event.type`                 -> `"AUTHENTICATION"`

Country / device caveats:

- `xdm.source.location.country` expects an ISO-3166-1 alpha-2
  code; the producer guarantees this via its GeoIP layer.
- `xdm.source.host.device_category` is the right path for a
  classification label (mobile/desktop/unknown). The
  `xdm.network.http.browser` path is reserved for a declared
  browser name (WARN-031); the auth pack deliberately does not
  populate it.

## On the `baselines/` folder

The `baselines/` directory is a living mirror of the current pack
plus its analyser output, refreshed whenever `parser.xql` or
`datamodel.xql` changes materially. It is not a frozen historical
snapshot. Three files are kept in lock-step with the live rules:

- `gocortex_brokenbank_auth_xdm_model_rule.xql` -- byte-for-byte
  copy of `../datamodel.xql` at the time of the last refresh.
  Diff target for PR review and the canonical input for the
  analyser baseline.
- `gocortex_brokenbank_auth_xdm_model_rule.json` -- response from
  `POST /api/analyse` with `ruleType: "modeling"`, pretty-printed.
  Pins the analyser's expected verdict (score, summary counts,
  every violation) so any inadvertent regression in the analyser
  surfaces as a baseline diff in CI.
- `gocortex_brokenbank_auth_parser.json` -- the same analyser
  output for `../parser.xql` with `ruleType: "parsing"`.
- `sample_logs.txt` -- a small set of representative `_raw_log`
  rows lifted directly from the source-of-truth attached asset.

If you change either rule, refresh all four files in the same
commit. The current analyser baseline is score 98 with two
INFO-011 hits: `xdm.source.ipv4` mapped without `xdm.target.ipv4`
(the auth log records the offender IP only -- the BrokenBank app
server IP is not on the wire) and `xdm.source.user.username`
mapped without `xdm.target.user.username` (auth events have a
single principal -- the login subject -- with no separate target
user identity).
