# Cisco WSA Access Log -- XDM Data Model Rule Documentation

Companion notes for `cisco_wsa_access_log_xdm_model_rule.xql`.

## Scope

Maps Cisco Web Security Appliance (WSA) access log entries to the Cortex
XDM schema. The WSA is a forward web proxy / secure web gateway. Each log
entry records a single HTTP transaction: a client request through the
proxy to an upstream destination, together with the proxy's caching,
scanning, and policy decisions.

## Log format

Squid-style positional (space-delimited), wrapped in a syslog prefix
injected by an intermediate forwarder:

```
<PRI>MMM DD HH:MM:SS hostname accesslogs: Info: <WSA_LOG>
```

The WSA log portion (everything after `Info: `) follows this field order
(0-indexed positions after a space-split):

| Pos | Field             | Notes |
| --- | ----------------- | ----- |
| 0   | timestamp         | Epoch seconds with millisecond fraction |
| 1   | elapsed           | Transaction duration in milliseconds |
| 2   | client_ip         | Source client IPv4 address |
| 3   | result/status     | Cache result code / HTTP status (e.g. `TCP_MISS/200`, `TCP_DENIED/407`, `NONE/504`) |
| 4   | sc_bytes          | Bytes delivered from server to client |
| 5   | method            | HTTP method (`GET`, `POST`, `CONNECT`, `HEAD`) or `TCP_CONNECT` for transparent HTTPS |
| 6   | url               | Requested URL or `tunnel://host:port/` for `CONNECT` tunnels, or raw `host:port` for `TCP_CONNECT` |
| 7   | user              | Authenticated username in `DOMAIN\user@domain` format, or `-` when unauthenticated |
| 8   | hierarchy/peer    | Fetch hierarchy code / upstream server (e.g. `DIRECT/www.example.com`, `NONE/-`) |
| 9   | content_type      | MIME type (e.g. `application/octet-stream`) or `-` when not applicable |
| 10  | CMF:n             | Cisco Meta Framework score |
| 11  | DCF:n             | Decision Framework score |
| 12  | ERR:n             | Error code (`0` = no error) |
| 13  | acl_decision_tag  | Hyphen-separated policy decision string (e.g. `DEFAULT_CASE_12-WebTesting-Users-NONE-NONE-NONE-DefaultGroup-NONE`) |
| 14+ | scanning_details  | Angle-bracket-enclosed, comma-separated scanning verdicts including URL category code, WBRS score, application name, and category descriptions |

The `_raw_log` column carries the full syslog-wrapped line. Field
extractions use `regextract()` to strip the syslog prefix, then `split()`
plus `arrayindex()` for positional access (Pattern 9).

The scanning details section is enclosed in angle brackets and contains
comma-separated values with embedded quotes. Key fields extracted via
`regextract`:

- URL category code (e.g. `IW_srch`, `IW_snet`, `IW_comp`)
- WBRS score (web reputation, e.g. `6.2`, `-3.0`)

## Username format

`DOMAIN\samaccountname@upn_suffix` (e.g. `DESBT\indahwatsx@desbt.local`).
The domain prefix is split into `xdm.source.user.domain` and the UPN
suffix into `xdm.source.user.username`.

## Outcome mapping

| Result codes                                                                                       | Outcome           |
| -------------------------------------------------------------------------------------------------- | ----------------- |
| `TCP_MISS`, `TCP_HIT`, `TCP_MEM_HIT`, `TCP_REFRESH_HIT`, `TCP_IMS_HIT`, `TCP_CLIENT_REFRESH_MISS`  | OUTCOME_SUCCESS   |
| `TCP_DENIED`                                                                                       | OUTCOME_FAILED (blocked by policy) |
| `NONE`                                                                                             | OUTCOME_FAILED (connection failed) |
| any other                                                                                          | OUTCOME_UNKNOWN   |

## XDM field mapping summary (23 fields)

### Observer (3)

- `xdm.observer.vendor` = `"Cisco"`
- `xdm.observer.product` = `"Secure Web Appliance"`
- `xdm.observer.name` = syslog hostname (the WSA appliance FQDN from the syslog prefix)

### Event (5)

- `xdm.event.type` = `"NETWORK"`
- `xdm.event.description` = structured summary (method, URL, result/status, client IP, user, upstream server) via `concat`
- `xdm.event.duration` = elapsed time in milliseconds
- `xdm.event.outcome` = mapped from cache result code (`TCP_MISS/HIT` -> SUCCESS, `TCP_DENIED/NONE` -> FAILED)
- `xdm.event.outcome_reason` = full result/status string (e.g. `TCP_DENIED/407`)

### Source (3)

- `xdm.source.ipv4` = client IP address
- `xdm.source.user.username` = authenticated username (UPN portion after `DOMAIN\` prefix)
- `xdm.source.user.domain` = AD domain from `DOMAIN\user` (e.g. `DESBT`)

### Target (4)

- `xdm.target.host.hostname` = upstream destination server (from hierarchy/peer field)
- `xdm.target.url` = full requested URL
- `xdm.target.port` = target port extracted from URL
- `xdm.target.sent_bytes` = bytes delivered to client (sc-bytes from the log)

### Network (6)

- `xdm.network.http.method` = HTTP method string
- `xdm.network.http.response_code` = HTTP status code string (200, 401, 403, etc.)
- `xdm.network.http.content_type` = MIME type when present
- `xdm.network.http.url` = full requested URL (mirror of `xdm.target.url` for HTTP-specific query coverage)
- `xdm.network.http.domain` = hostname extracted from URL
- `xdm.network.rule` = ACL decision tag (full policy decision string)

### Intermediate (2)

- `xdm.intermediate.host.hostname` = WSA appliance short hostname
- `xdm.intermediate.host.fqdn` = WSA appliance FQDN (same as `observer.name`; the proxy is both the observer and the intermediary)

## Excluded XDM fields -- not applicable or no source data

- `xdm.alert.*` -- network traffic access log, not a security alert dataset
- `xdm.source.port` -- the WSA Squid access log does not record the client source port
- `xdm.target.ipv4` -- upstream server IP is not explicitly logged in standard Squid format. The hierarchy/peer field carries the hostname only. Do not fabricate an IP from the hostname.
- `xdm.network.http.url_category` -- WSA proprietary category codes (e.g. `IW_srch`, `IW_snet`) do not map to `XDM_CONST.URL_CATEGORY` numeric IDs. The raw category code is preserved in the ACL tag and scanning details for manual analysis.
- `xdm.network.http.referrer` -- not present in standard Squid access log format
- `xdm.network.http.browser` -- user-agent string is not logged by default
- `xdm.network.ip_protocol` -- all WSA traffic is TCP (HTTP/HTTPS); the protocol is implicit
- `xdm.session_context_id` -- no session identifier in the access log

## Excluded payload fields -- no suitable XDM target

- CMF score (position 10) -- Cisco Meta Framework internal scoring; no XDM field for vendor-specific scanning scores
- DCF score (position 11) -- Decision Framework internal scoring; no XDM field
- ERR code (position 12) -- Cisco internal error code; condition reflected in HTTP status and outcome mapping
- WBRS score -- Web-Based Reputation Score (-10..+10); no XDM field for web reputation
- URL category code (e.g. `IW_srch`) -- proprietary identifiers; see `xdm.network.http.url_category` exclusion above
- URL category description (e.g. `Search Engines and Portals`) -- no standard XDM field for free-text category descriptions
- Application name and type (e.g. `Office 365/OneDrive`, `Office Suites`) -- proprietary classification; could fold into `xdm.network.application_protocol` but values are not standard protocol names

## Body stage notes

- Stage 1 strips the syslog wrapper, extracting `_wsa_log` (the WSA log
  portion after `Info: `) and `_syslog_fqdn` (the appliance FQDN).
- Stage 2 splits positions 0..13 from `_wsa_log`. Position 14+ is the
  scanning-details section and is extracted separately via `regextract`
  because it carries embedded spaces.

## Anchors

The pack ships a parser (`parser.xql`) which stamps two anchor columns
on every row in `cisco_websecurityappliance_raw` at ingest time. The
anchors are defined in `PRIVATE_DOCS/anchor_field_design.md`; this
section documents the WSA-specific values.

### `_wsa_decision` -- W3C ACL decision tag

The first hyphen-separated component of the policy decision string at
position 13. Closed vocabulary of roughly 15 values. Universal proxy
triage filter ("show me everything we blocked"):

| Value family   | Examples                                              | Outcome  |
| -------------- | ----------------------------------------------------- | -------- |
| `ALLOW_*`      | `ALLOW_WBRS`, `ALLOW_ADMIN`                           | success  |
| `BLOCK_*`      | `BLOCK_AVC`, `BLOCK_AMW_REQ`, `BLOCK_AMW_RESP`,       | blocked  |
|                | `BLOCK_ADMIN`, `BLOCK_CONTENT`, `BLOCK_WBRS`          |          |
| `MONITOR_*`    | `MONITOR`, `MONITOR_AVC`, `MONITOR_HTTPS`             | observed |
| `REDIRECT`     | `REDIRECT`                                            | success  |
| `DEFAULT_CASE` | `DEFAULT_CASE`, `DEFAULT_CASE_12`                     | varies   |
| `OTHER`        | `OTHER`                                               | varies   |

Sample analyst query:

```
dataset = cisco_websecurityappliance_raw
| filter _wsa_decision ~= "^BLOCK_"
| comp count() by _wsa_decision
```

### `_wsa_http_method` -- HTTP method

HTTP method at position 5. Tightly closed vocabulary. The parser regex
`^(GET|POST|CONNECT|HEAD|PUT|DELETE)$` constrains the anchor so
non-method tokens (e.g. WSA's transparent `TCP_CONNECT` placeholder)
leave the column NULL rather than poisoning the indexed values:

| Value     | Notes                                                  |
| --------- | ------------------------------------------------------ |
| `GET`     | Standard request                                       |
| `POST`    | Form / API submit                                      |
| `CONNECT` | HTTPS tunnel establishment                             |
| `HEAD`    | Metadata-only request                                  |
| `PUT`     | REST API write                                         |
| `DELETE`  | REST API delete                                        |

Rows where the method field carried `TCP_CONNECT` (transparent HTTPS
interception) or any other non-RFC-7231 verb leave `_wsa_http_method`
NULL; analysts who want those rows can fall back to the position-5
split inside `_raw_log` (or use `xdm.network.http.method` after the
data-model rule has run).

Sample analyst query:

```
dataset = cisco_websecurityappliance_raw
| filter _wsa_http_method = "POST"
| comp count() by _wsa_decision
```

## Relationship to parser

This pack ships the parser and the data-model rule together as a unit
(`PRIVATE_DOCS/anchor_field_design.md`, "Ship parser + datamodel as
one pack"). Both files change in the same commit when an anchor is
added or removed. The data-model rule uses the **keep-in-both**
`coalesce()` convention so the parser column is purely additive:

- `_http_method` in `datamodel.xql` is now derived as
  `coalesce(_wsa_http_method, arrayindex(_parts, 5))`. Parser-stamped
  rows short-circuit through the column read; rows ingested before the
  parser shipped, replayed sample data, and backfills all continue to
  model identically because the original position-5 split stays in
  place.
- `wsa_acl_decision` in `datamodel.xql` (a new non-underscore
  intermediate) is derived as `coalesce(_wsa_decision,
  arrayindex(split(_acl_tag, "-"), 0))` and is consumed by
  `xdm.event.outcome` as a defensive fallback so blocked / allowed /
  monitored / redirected requests still land in the right outcome
  bucket when the cache-result code is an unfamiliar token.

`xdm.network.rule` continues to carry the full hyphen-separated policy
decision string from `_acl_tag`; the W3C decision anchor is the
high-selectivity discriminator that drives interactive triage, while
the full string remains available for forensic reconstruction.

When either anchor is added or removed, both `parser.xql` and the
`coalesce()` site in `datamodel.xql` change in the same commit. The
keep-in-both convention is what makes anchors backfill-safe; it only
works if the two files stay in lock-step.
