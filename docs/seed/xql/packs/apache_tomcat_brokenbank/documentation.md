# Apache Tomcat (GoCortex Broken Bank) -- Pack Documentation

Companion notes for `parser.xql` and `datamodel.xql`.

## What this pack covers

Maps the Apache Tomcat "combined" access log produced by the GoCortex
Broken Bank exploit container into the Cortex XDM schema. Each log
entry records a single HTTP transaction handled by the embedded Tomcat
fronting the BrokenBank web application. Stream 1 of 4 in the
GoCortex Broken Bank 1.5.0 SIEM contract.

Source-of-truth for the wire format and sample payloads:
`attached_assets/Pasted--GoCortex-Broken-Ban-1777803533165_1777803533165.txt`,
section labelled `tomcat_access`. The producer ships each
combined-log line verbatim to a Cortex HTTP collector
(`https://api-MYTENANT.xdr.au.paloaltonetworks.com/logs/v1/event`).
The bare CLF line lands in `_raw_log`.

## Wire format

Apache combined access log:

```
%h %l %u %t "%r" %>s %b "%{Referer}i" "%{User-Agent}i"
```

Nine whitespace / quote delimited fields per row:

| CLF token         | Meaning                                           |
| ----------------- | ------------------------------------------------- |
| `%h`              | remote host (client IP)                           |
| `%l`              | remote logname (always `-` from this producer)    |
| `%u`              | remote user (HTTP basic auth principal, or `-`)   |
| `%t`              | request time `[DD/Mon/YYYY:HH:MM:SS +ZZZZ]`       |
| `"%r"`            | request line `METHOD URI HTTP/VER`                |
| `%>s`             | final response status code                        |
| `%b`              | response body byte count (or `-` for zero)        |
| `"%{Referer}i"`   | request `Referer` header (or `-`)                 |
| `"%{User-Agent}i"`| request `User-Agent` header (or `-`)              |

The four `-` sentinels (`%l`, `%u`, `%{Referer}i`, `%b` when zero)
are collapsed to `null` by the parser per the OpenAPI schema notes.

## Sample payloads

Typical browser request:

```
192.0.2.10 - alice [03/May/2026:12:34:56 +0000] "GET /login HTTP/1.1" 200 1820 "https://bank.gocortex.test/" "Mozilla/5.0 (Windows NT 10.0; Win64) Chrome/124.0.0.0"
```

Scanner traffic with no auth principal and no referer:

```
198.51.100.7 - - [03/May/2026:12:35:01 +0000] "POST /login HTTP/1.1" 401 0 "-" "sqlmap/1.7.2#stable"
```

## Anchors

The parser stamps the following five anchor columns on every row;
the datamodel reads them via the keep-in-both `coalesce(<parser
column>, <regextract over _raw_log>)` pattern from
`PRIVATE_DOCS/anchor_field_design.md` (Task #100):

| Anchor             | XDM target                       | Notes |
| ------------------ | -------------------------------- | ----- |
| `_client_ip`       | `xdm.source.ipv4`                | First whitespace-delimited token. |
| `_request_method`  | `xdm.network.http.method`        | First token of the quoted request line. Mapped through an `XDM_CONST.HTTP_METHOD_*` if-chain. |
| `_request_uri`     | `xdm.network.http.url`           | Path + query of the quoted request line. |
| `_status_code`     | `xdm.network.http.response_code` | HTTP response code as integer; also drives `xdm.event.outcome`. |
| `_user_agent`      | `xdm.source.user_agent`          | The trailing quoted UA string. |

The four non-anchor parser columns (`_remote_logname`,
`_remote_user`, `_referer`, `_response_bytes`) feed the secondary
XDM mappings without being indexed for analyst search.

## XDM coverage

Anchor-derived fields (keep-in-both via `coalesce(<parser column>,
regextract(_raw_log, ...))`):

- `_client_ip`       -> `xdm.source.ipv4`
- `_request_method`  -> `xdm.network.http.method` (XDM_CONST.HTTP_METHOD_* enum, unknown verb -> null per WARN-029)
- `_request_uri`     -> `xdm.network.http.url`
- `_status_code`     -> `xdm.network.http.response_code` and drives `xdm.event.outcome` (`null` -> UNKNOWN, `>= 400` -> FAILED, else SUCCESS) and `xdm.event.outcome_reason` (status as string)
- `_user_agent`      -> `xdm.source.user_agent`, drives `xdm.network.http.browser` (UA family parse: Edge/Opera/Chrome/Firefox/Safari only -- bot labels stay out per WARN-031)

Non-anchor fields:

- `_remote_user`     -> `xdm.source.user.username`
- `_response_bytes`  -> `xdm.target.sent_bytes` (XDM has no dedicated `network.http.response_content_length` path; the byte count lives on the network-bytes envelope and the server is the side that sent the bytes)
- `_referer`         -> `xdm.network.http.referrer`

Static / synthesised:

- `xdm.observer.vendor / product / type` -> `"Apache" / "Tomcat" / "Web Server"`
- `xdm.event.type`        -> `"ACCESS"`
- `xdm.event.id`          -> `_id`
- `xdm.event.description` -> `concat(method, " ", url, " status ", code)`

The fallback regex shapes used by the keep-in-both `coalesce` mirror
the parser regexes verbatim, with the literal-quote bytes written as
`\x22` (regex hex-escape) instead of `\"` so the analyser's
`collectStageStatements` helper does not mis-track escaped quotes.
The wire-format match is identical (Cortex regex evaluates `\x22` as
the `"` byte).

## On the `baselines/` folder

The `baselines/` directory is a living mirror of the current pack
plus its analyser output, refreshed whenever `parser.xql` or
`datamodel.xql` changes materially. It is not a frozen historical
snapshot. Three files are kept in lock-step with the live rules:

- `apache_tomcat_brokenbank_xdm_model_rule.xql` -- byte-for-byte
  copy of `../datamodel.xql` at the time of the last refresh.
  Useful as a diff target when reviewing a PR that touches the
  rule, and as the canonical input for the analyser baseline below.
- `apache_tomcat_brokenbank_xdm_model_rule.json` -- response from
  `POST /api/analyse` with `{code: <the rule>, ruleType:
  "modeling"}`, pretty-printed. Pins the analyser's expected verdict
  (score, summary counts, every violation) so any inadvertent
  regression in the analyser surfaces as a baseline diff in CI
  rather than as a silent change in production behaviour.
- `apache_tomcat_brokenbank_parser.json` -- the same analyser
  output for `../parser.xql` with `ruleType: "parsing"`.
- `sample_logs.txt` -- a small set of representative `_raw_log`
  rows lifted directly from the source-of-truth attached asset.

If you change either rule, refresh all four files in the same
commit. The current analyser baseline is score 98 with two
INFO-011 hits (no destination IP / username on a one-way CLF
combined log).
