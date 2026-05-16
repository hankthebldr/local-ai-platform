// EfficientIP DDI -- Parsing rule (anchor extraction)
// Dataset: efficientip_raw
// Vendor:  EfficientIP | Product: SOLIDserver DDI
//
// This parser is the first worked example of the ANCHOR pattern
// described in PRIVATE_DOCS/anchor_field_design.md. It pulls two
// small, high-selectivity discriminators out of `_raw_log` once at
// ingest so that downstream analyst searches against `efficientip_raw`
// can filter on indexed columns instead of regex-extracting them on
// every row, every query, every time.
//
// Anchors written by this parser:
//   1. `_syslog_proc`     -- the four-way daemon discriminator,
//                            one of {named, dhcpd, sshd, sudo}.
//                            Every per-daemon search uses this.
//   2. `_syslog_priority` -- the integer 0-191 from the syslog
//                            <PRI> header. Drives severity /
//                            facility filtering without the
//                            analyst having to think about how to
//                            extract it.
//
// No XDM mappings live in this rule -- all heavy lifting stays in
// the data-model rule (`datamodel.xql` in this pack). The parser
// only has two jobs: write the two anchor columns and stamp `_time`
// from the syslog header (required for every parsing rule -- see
// PRIVATE_DOCS/parsing_rule_building_guide.md, "Step 4: Validate").
//
// RELATIONSHIP TO datamodel.xql
// -----------------------------
// The shared `[RULE: efficientip_syslog_header]` block in
// `datamodel.xql` reads both anchor columns via the keep-in-both
// `coalesce(<parser column>, <regex over _raw_log>)` convention
// described in `PRIVATE_DOCS/anchor_field_design.md` (adopted in
// Task #100):
//   - Parser-stamped rows benefit from the indexed column: the
//     coalesce short-circuits to one column read instead of
//     running the regex.
//   - Rows ingested BEFORE this parser shipped -- and any
//     replayed sample data or backfills -- still model
//     identically, because the same regex the data-model rule
//     has always run is the coalesce fallback.
//
// The parser is therefore purely additive. The performance win
// extends to both interactive analyst queries against the raw
// dataset (`dataset = efficientip_raw | filter
// _syslog_proc = "named"`) and to the data-model rule itself on
// parser-stamped rows.
//
// See `PRIVATE_DOCS/anchor_field_design.md` for the underlying
// concept and why three or more anchors per dataset is almost
// always wrong.
//
// ENVELOPE SHAPES
// ---------------
// EfficientIP appliances ship two envelope shapes:
//   1. RFC 3164:           <PRI>MMM DD HH:MM:SS [HOST] daemon[PID]: BODY
//   2. RFC 5424-in-kernel: <PRI>MMM DD HH:MM:SS kernel: ISO_TS HOST daemon PID - - BODY
// Each anchor below has a primary regex for the RFC 3164 shape and
// (where relevant) a `coalesce` fallback for the RFC 5424-in-kernel
// shape so a single anchor value feeds both envelopes.
//
// The allow-list filter at the head of the rule keeps the parser
// off lines that are not from one of the four supported daemons
// (FreeBSD `devd[]`, internal `ipmserver[]` RPC, raw `kernel:` ipfw
// lines, etc.). `no_hit=keep` ensures those filtered rows still
// land in `efficientip_raw` so the data-model rule can deal with
// them; the parser just declines to stamp the anchors or `_time`.
//
// TIMESTAMP HANDLING
// ------------------
// RFC 3164 syslog timestamps do not include a year; the year is
// derived from `_insert_time` and the year-boundary edge case (a
// log emitted in late December but ingested in early January) is
// handled by the same idiom the canonical Cisco ISE parser uses
// in `PRIVATE_DOCS/all_parsing_rules.txt:231-247`: if the
// reconstructed timestamp lands in the future, roll the year back
// by one. INFO-005 fires on this rule as an acknowledgement that
// year-boundary heuristics are inherently approximate; the
// alternative (no `_time`) is worse.
//
// Documentation: documentation.md (in this pack)
//
// SPDX-FileCopyrightText: GoCortexIO
// SPDX-License-Identifier: AGPL-3.0-or-later

[INGEST: vendor = "efficientip", product = "ddi", target_dataset = "efficientip_raw", no_hit = keep]

filter
    _raw_log != null
    and _raw_log ~= "(\s(named|dhcpd|sshd|sudo)\[\d+\]:|\skernel:\s+\S+\s+\S+\s+(named|dhcpd|sshd|sudo)\s+\d+\s+-\s+-\s)"

| alter
    _syslog_priority = to_integer(arrayindex(regextract(_raw_log, "^<(\d{1,3})>"), 0)),
    _syslog_proc = coalesce(
        arrayindex(regextract(_raw_log, "\s(named|dhcpd|sshd|sudo)\[\d+\]:"), 0),
        arrayindex(regextract(_raw_log, "\skernel:\s+\S+\s+\S+\s+(named|dhcpd|sshd|sudo)\s+\d+\s+-\s+-"), 0)),
    tmp_syslog_ts = arrayindex(regextract(_raw_log, "^<\d{1,3}>(\w{3}\s+\d{1,2}\s+\d{1,2}:\d{2}:\d{2})"), 0),
    tmp_year = format_timestamp("%Y", _insert_time)

| alter
    tmp_time_thisyear = if(tmp_syslog_ts != null and tmp_syslog_ts != "", parse_timestamp("%Y %b %e %H:%M:%S", concat(tmp_year, " ", tmp_syslog_ts)), null)

| alter
    tmp_time_lastyear = if(tmp_time_thisyear != null and timestamp_diff(tmp_time_thisyear, current_time(), "MILLISECOND") > 0, parse_timestamp("%Y %b %e %H:%M:%S", concat(to_string(subtract(to_integer(tmp_year), 1)), " ", tmp_syslog_ts)), null)

| alter
    _time = coalesce(tmp_time_lastyear, tmp_time_thisyear)

| fields -tmp_syslog_ts, -tmp_year, -tmp_time_thisyear, -tmp_time_lastyear;
