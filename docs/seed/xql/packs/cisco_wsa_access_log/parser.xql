// Cisco Secure Web Appliance (WSA) -- Parsing rule (anchor extraction)
// Dataset: cisco_websecurityappliance_raw
// Vendor:  Cisco | Product: Secure Web Appliance
//
// This parser is the third worked example of the ANCHOR pattern
// described in PRIVATE_DOCS/anchor_field_design.md (after EfficientIP
// DDI in Task #95 and AWS GuardDuty in Task #102). WSA access logs
// are single-shape (Squid-style space-delimited rows wrapped in a
// syslog header), but two positional fields are universally used as
// triage filters: the W3C ACL decision tag and the HTTP method. Every
// per-decision and per-method search currently has to position-split
// `_raw_log` and regex over the policy decision string. This parser
// pulls both anchors out one row earlier so they become real indexed
// columns on `cisco_websecurityappliance_raw`.
//
// Anchors written by this parser:
//   1. `_wsa_decision`    -- the W3C ACL decision tag, the first
//                            hyphen-separated component of the policy
//                            decision string at position 13. Closed
//                            vocabulary (~15 values) including
//                            `ALLOW_WBRS`, `BLOCK_AVC`, `BLOCK_AMW_REQ`,
//                            `BLOCK_AMW_RESP`, `BLOCK_ADMIN`,
//                            `BLOCK_CONTENT`, `BLOCK_WBRS`, `MONITOR_*`,
//                            `REDIRECT`, `DEFAULT_CASE`, `OTHER`. The
//                            universal proxy triage filter -- "show me
//                            everything we blocked" maps directly to
//                            `| filter _wsa_decision ~= "^BLOCK_"`.
//   2. `_wsa_http_method` -- HTTP method at position 5. Closed
//                            vocabulary {GET, POST, CONNECT, HEAD, PUT,
//                            DELETE}; the regex constraint means
//                            non-method tokens (e.g. WSA's transparent
//                            `TCP_CONNECT` placeholder) leave the anchor
//                            NULL rather than poisoning the column.
//
// No XDM mappings live in this rule -- all heavy lifting stays in the
// data-model rule (`datamodel.xql` in this pack). The parser only has
// three jobs: write the two anchor columns and stamp `_time` from the
// syslog header (required for every parsing rule -- see
// PRIVATE_DOCS/parsing_rule_building_guide.md, "Step 4: Validate").
//
// RELATIONSHIP TO datamodel.xql
// -----------------------------
// `datamodel.xql` is migrated to the keep-in-both `coalesce()` shape
// in the same commit as this parser ships:
//
//   `_http_method        = coalesce(_wsa_http_method, arrayindex(_parts, 5))`
//   `wsa_acl_decision    = coalesce(_wsa_decision,
//                                   arrayindex(split(_acl_tag, "-"), 0))`
//
// Parser-stamped rows short-circuit through the column read; legacy
// rows ingested before this parser shipped, replayed sample data, and
// backfills all continue to model identically because the data-model
// rule still performs the same split it has always performed when the
// anchor column is NULL. `wsa_acl_decision` is consumed by
// `xdm.event.outcome` as a defensive fallback so the W3C decision
// drives the outcome enum even when the cache-result code does not
// match a known token.
//
// PRE-FILTER GUARD
// ----------------
// `_raw_log ~= "(?i)accesslogs"` keeps the parser off non-WSA syslog
// noise that is routed to the same dataset. The `(?i)` modifier makes
// the guard casing-defensive in line with the architect's review of
// Task #102. `no_hit=keep` ensures filtered rows still land in
// `cisco_websecurityappliance_raw` so the data-model rule can deal
// with them; the parser just declines to stamp the anchors or `_time`
// on rows that are not WSA access-log lines.
//
// TIMESTAMP HANDLING
// ------------------
// The WSA log carries an epoch float at position 0 of the body and
// the syslog header carries an RFC 3164 `MMM DD HH:MM:SS` timestamp.
// We derive `_time` from the syslog header rather than the WSA epoch
// for consistency with other syslog-wrapped packs (and because the
// syslog header is what the forwarder timestamps, which is what
// analysts correlate against). RFC 3164 timestamps do not include a
// year; the year is derived from `_insert_time` and the year-boundary
// edge case (a log emitted in late December but ingested in early
// January) is handled by the same idiom the EfficientIP DDI parser
// uses: if the reconstructed timestamp lands in the future, roll the
// year back by one. INFO-005 may fire on this rule as an
// acknowledgement that year-boundary heuristics are inherently
// approximate; the alternative (no `_time`) is worse.
//
// Documentation: documentation.md (in this pack)
//
// SPDX-FileCopyrightText: GoCortexIO
// SPDX-License-Identifier: AGPL-3.0-or-later

[INGEST: vendor = "cisco", product = "secure_web_appliance", target_dataset = "cisco_websecurityappliance_raw", no_hit = keep]

filter
    _raw_log != null
    and _raw_log ~= "(?i)accesslogs"

| alter
    tmp_wsa_log = arrayindex(regextract(_raw_log, "Info:\s+(.+)$"), 0),
    tmp_syslog_ts = arrayindex(regextract(_raw_log, "^<\d{1,3}>(\w{3}\s+\d{1,2}\s+\d{1,2}:\d{2}:\d{2})"), 0),
    tmp_year = format_timestamp("%Y", _insert_time)

| alter
    tmp_parts = split(tmp_wsa_log, " "),
    tmp_acl_tag = arrayindex(regextract(tmp_wsa_log, "ERR:\d+\s+(\S+)\s"), 0),
    tmp_time_thisyear = if(tmp_syslog_ts != null and tmp_syslog_ts != "", parse_timestamp("%Y %b %e %H:%M:%S", concat(tmp_year, " ", tmp_syslog_ts)), null)

| alter
    _wsa_http_method = arrayindex(regextract(to_string(arrayindex(tmp_parts, 5)), "^(GET|POST|CONNECT|HEAD|PUT|DELETE)$"), 0),
    _wsa_decision = arrayindex(split(to_string(tmp_acl_tag), "-"), 0),
    tmp_time_lastyear = if(tmp_time_thisyear != null and timestamp_diff(tmp_time_thisyear, current_time(), "MILLISECOND") > 0, parse_timestamp("%Y %b %e %H:%M:%S", concat(to_string(subtract(to_integer(tmp_year), 1)), " ", tmp_syslog_ts)), null)

| alter
    _time = coalesce(tmp_time_lastyear, tmp_time_thisyear)

| fields -tmp_wsa_log, -tmp_syslog_ts, -tmp_year, -tmp_parts, -tmp_acl_tag, -tmp_time_thisyear, -tmp_time_lastyear;
