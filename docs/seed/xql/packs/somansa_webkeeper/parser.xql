// Somansa WebKeeper -- Parsing rule (anchor extraction)
// Dataset: somansa_webkeeper_raw
// Vendor:  Somansa | Product: WebKeeper
//
// Ninth worked example of the ANCHOR pattern described in
// PRIVATE_DOCS/anchor_field_design.md. WebKeeper sends three
// structurally distinct payload shapes (PROXY-A, PROXY-B, SYSTEM)
// behind a single `pssv_sensor[PID]:` syslog envelope and the
// existing data-model rule already discriminates between them as
// the very first thing it does. Lifting that 3-value discriminator
// into a parser-stamped column means every analyst search against
// `somansa_webkeeper_raw` filters on an indexed column instead of
// re-running the same pair of regex tests against `_raw_log` on
// every row, every query, every time.
//
// Anchors written by this parser:
//   1. `_payload_shape` -- 3 closed values (PROXY_A, PROXY_B,
//                          SYSTEM). The smallest possible useful
//                          vocabulary for an anchor and the
//                          textbook fan-out discriminator from the
//                          design note. Lifted from the structural
//                          markers inside the WebKeeper payload --
//                          `@#Loading-Success` for SYSTEM, then a
//                          multi-scheme `,scheme://` URL marker for
//                          PROXY_B (matches HTTP/HTTPS, FTP/FTPS,
//                          WebSocket and Gopher case-insensitively
//                          per the existing data-model rule), then
//                          PROXY_A as the default. The marker
//                          regexes are byte-for-byte identical to
//                          the data-model rule's Stage 2 logic so
//                          the keep-in-both `coalesce()` reduces to
//                          a column read on parser-stamped rows.
//
//   2. `_proxy_action`  -- ~5 closed values (Allow, Block, Warn,
//                          Bypass, Quarantine). Lifted verbatim
//                          from CSV position 1 of the proxy payload
//                          (the action verb that drives every
//                          OUTCOME / log_level decision in the
//                          data-model rule). Deliberately NULL on
//                          SYSTEM rows -- a SYSTEM event has no
//                          proxy action, and an analyst running
//                          `_proxy_action = "Block"` is by intent
//                          excluding system housekeeping rows. The
//                          alternative (stamping a literal "SYSTEM"
//                          here) was rejected because it would
//                          conflate "the action is SYSTEM" with
//                          "no action present".
//
// No XDM mappings live in this rule -- all heavy lifting stays in
// `datamodel.xql` in this pack. The parser only writes the two
// anchor columns and `_time`.
//
// PAYLOAD SHAPES
// --------------
// All three shapes ride the same syslog envelope:
//   <PRI>MMM DD HH:MM:SS <host> pssv_sensor[<pid>]: <PAYLOAD>
//
//   PROXY-A : [ts],ACTION,policy,user_id,src_ip,dst_ip,category,sub
//   PROXY-B : [ts],ACTION,policy,user_id,src_ip,dst_ip,domain,url,category
//   SYSTEM  : [ts]@#Loading-Success(<token>)
//
// The pre-filter accepts only `pssv_sensor[<pid>]:` lines (the
// only WebKeeper sensor process) and `no_hit = keep` ensures any
// stray non-WebKeeper line that lands on the same input still
// reaches `somansa_webkeeper_raw` so the data-model rule can
// decide what to do with it; the parser just declines to stamp
// the anchors or `_time` for those.
//
// RELATIONSHIP TO datamodel.xql
// -----------------------------
// `datamodel.xql` reads both anchors via the keep-in-both
// convention from `PRIVATE_DOCS/anchor_field_design.md`:
//
//   _payload_shape = coalesce(_payload_shape, <same shape regex over _payload>)
//   _proxy_action  = coalesce(_proxy_action,
//                             if(_payload_shape != "SYSTEM",
//                                arrayindex(_csv_parts, 1),
//                                null))
//
// The `_proxy_action` fallback explicitly returns NULL on SYSTEM
// rows so that the legacy / replayed / backfilled fall-through
// path matches the parser's null-on-SYSTEM convention -- there is
// no spurious non-null `_proxy_action` on a system row even when
// the parser column is absent.
//
// Both anchors are sunk into XDM via `coalesce()` arms or via
// `if(_payload_shape = ...)` per-shape gates (not via `concat()`
// arguments) so the analyser does not raise ERR-025 on either
// intermediate.
//
// TIMESTAMP HANDLING
// ------------------
// RFC 3164 syslog timestamps do not include a year; the year is
// derived from `_insert_time` and the year-boundary edge case (a
// log emitted in late December but ingested in early January) is
// handled by the same idiom the EfficientIP DDI parser uses: if
// the reconstructed timestamp lands in the future, roll the year
// back by one. INFO-005 fires on this rule as an acknowledgement
// that year-boundary heuristics are inherently approximate; the
// alternative (no `_time`) is worse.
//
// Documentation: documentation.md (in this pack)
//
// SPDX-FileCopyrightText: GoCortexIO
// SPDX-License-Identifier: AGPL-3.0-or-later

[INGEST: vendor = "somansa", product = "webkeeper", target_dataset = "somansa_webkeeper_raw", no_hit = keep]

filter
    _raw_log != null
    and _raw_log ~= "pssv_sensor\[\d+\]:"

| alter
    tmp_payload = arrayindex(regextract(_raw_log, "pssv_sensor\[\d+\]:\s+(.+)$"), 0),
    tmp_syslog_ts = arrayindex(regextract(_raw_log, "^<\d{1,3}>(\w{3}\s+\d{1,2}\s+\d{1,2}:\d{2}:\d{2})"), 0),
    tmp_year = format_timestamp("%Y", _insert_time)

| alter
    _payload_shape = if(
        tmp_payload ~= "@#Loading-Success", "SYSTEM",
        tmp_payload ~= ",(?i)(?:https?|ftps?|wss?|gopher):[/][/]", "PROXY_B",
        "PROXY_A"),
    _proxy_action = if(
        tmp_payload ~= "@#Loading-Success",
        null,
        arrayindex(split(to_string(tmp_payload), ","), 1))

| alter
    tmp_time_thisyear = if(tmp_syslog_ts != null and tmp_syslog_ts != "", parse_timestamp("%Y %b %e %H:%M:%S", concat(tmp_year, " ", tmp_syslog_ts)), null)

| alter
    tmp_time_lastyear = if(tmp_time_thisyear != null and timestamp_diff(tmp_time_thisyear, current_time(), "MILLISECOND") > 0, parse_timestamp("%Y %b %e %H:%M:%S", concat(to_string(subtract(to_integer(tmp_year), 1)), " ", tmp_syslog_ts)), null)

| alter
    _time = coalesce(tmp_time_lastyear, tmp_time_thisyear)

| fields -tmp_payload, -tmp_syslog_ts, -tmp_year, -tmp_time_thisyear, -tmp_time_lastyear;
