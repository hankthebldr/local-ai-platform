// GoCortex BBWAF -- Parsing rule (anchor extraction)
// Dataset: gocortex_bbwaf_raw
// Vendor:  GoCortex | Product: BBWAF
//
// BBWAF (Broken Bank Web Application Firewall) is the in-app
// security appliance shipped by GoCortex Broken Bank 1.5.0. One
// compact JSON object is POSTed for every request that reaches a
// known-vulnerable Flask endpoint declared in
// `log_shipping.VULNERABILITY_MAPPING`.
//
// Reference: attached_assets/Pasted--GoCortex-Broken-Ban-...txt
// (Stream 2 of 4, "netbank_application").
//
// Anchors written by this parser:
//   1. `_source_ip`       -- the originating client IP (or NULL
//                            when Flask emitted the literal string
//                            "unknown"). Drives attacker / scanner
//                            pivots without re-parsing the JSON.
//   2. `_vulnerability`   -- the OWASP / CWE category (closed
//                            36-value enum, see OpenAPI schema).
//                            High-selectivity discriminator that
//                            every per-vulnerability search uses.
//   3. `_endpoint`        -- the vulnerable Flask route path that
//                            was hit. Identical to `request_path`;
//                            kept as a separate anchor because the
//                            producer guarantees the join, and the
//                            value is a low-cardinality dimension
//                            analysts pivot on.
//   4. `_request_method`  -- HTTP verb (closed enum: GET / POST /
//                            PUT / PATCH / DELETE / HEAD /
//                            OPTIONS).
//
// `"unknown"` is collapsed to NULL for `_source_ip` so downstream
// XDM `xdm.source.ipv4` does not ingest the literal sentinel
// string; the data-model rule applies the same collapse to
// `user_agent` because that field also defaults to "unknown" when
// the request header is absent.
//
// No XDM mappings live in this rule. `_time` is stamped from the
// ISO-8601 `timestamp` field which always carries microsecond
// precision plus the `+00:00` suffix
// (`datetime.now(timezone.utc).isoformat()`).
//
// RELATIONSHIP TO datamodel.xql
// -----------------------------
// `datamodel.xql` reads the four anchor columns this parser
// stamps via the keep-in-both `coalesce(<parser column>, json_extract_scalar(_raw_log, ...))` pattern (anchor_field_design.md, Task #100) and does not
// re-extract anchored fields from `_raw_log` directly.
// Secondary fields that the parser does not anchor
// (`user_agent`, `query_string`, `payload`, `severity`,
// `action`, `event_id`, `request_path`) are pulled at model
// time via `json_extract_scalar`.
// Legacy / replayed rows that pre-date this parser are still
// modelled correctly: the keep-in-both `coalesce` reaches the
// `json_extract_scalar` fallback when the anchor column is
// NULL, so the datamodel produces XDM output regardless of
// whether the parser has run on a given row.
//
// Documentation: documentation.md (in this pack)

[INGEST: vendor = "gocortex", product = "bbwaf", target_dataset = "gocortex_bbwaf_raw", no_hit = keep]

filter
    _raw_log != null
    and _raw_log ~= "(?i)\"vulnerability\""

| alter
    tmp_source_ip = json_extract_scalar(_raw_log, "$.source_ip"),
    tmp_event_ts = json_extract_scalar(_raw_log, "$.timestamp")

| alter
    _source_ip = if(tmp_source_ip != null and tmp_source_ip != "unknown", tmp_source_ip),
    _vulnerability = json_extract_scalar(_raw_log, "$.vulnerability"),
    _endpoint = json_extract_scalar(_raw_log, "$.endpoint"),
    _request_method = json_extract_scalar(_raw_log, "$.request_method"),
    _time = if(tmp_event_ts != null and tmp_event_ts != "", parse_timestamp("%Y-%m-%dT%H:%M:%E*S%Ez", tmp_event_ts), null)

| fields -tmp_source_ip, -tmp_event_ts;
