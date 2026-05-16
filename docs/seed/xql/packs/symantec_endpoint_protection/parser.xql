// Symantec Endpoint Protection -- Parsing rule (anchor extraction)
// Dataset: symantec_ep_raw
// Vendor:  Symantec | Product: Endpoint Protection
//
// Stamps two anchor columns and the canonical `_time` for SEP Manager
// syslog payloads. See PRIVATE_DOCS/anchor_field_design.md for the
// anchor pattern and PRIVATE_DOCS/cortex_xsiam_authoring_rules.md
// (rules 21-30) for the keep-in-both convention.
//
// Anchors written by this parser:
//   1. `_sep_category`  -- ten-way SEP event-family discriminator,
//                          one of {AntiVirus, IPS, DeviceControl,
//                          ApplicationControl, Auth, Policy, Tamper,
//                          System, Firewall, BehaviorMonitoring}.
//                          Drives every per-family analyst search.
//                          Finer-grained than the legacy `_subtype`
//                          discriminator in datamodel.xql (which fans
//                          out only on the five sub-shapes RISK / IPS
//                          / BEHAVIOR / TRAFFIC / SYSTEM); the parser
//                          anchor splits System-shape events into
//                          DeviceControl / ApplicationControl / Auth
//                          / Policy / Tamper / System on the same
//                          column so analysts do not have to regex
//                          `_raw_log` for those sub-families.
//   2. `_severity`      -- SEP-native severity enum, one of
//                          {Info, Warning, Major, Critical}. Sourced
//                          from the SEP `Severity:` token when the
//                          forwarder emits it; otherwise mapped from
//                          the numeric `Sensitivity:` 1-9 ladder
//                          (1-3 -> Info, 4-5 -> Warning, 6-7 -> Major,
//                          8-9 -> Critical). The MODEL keeps a
//                          separate banded ladder (`_severity_band`,
//                          five-bucket Critical / High / Medium / Low
//                          / Informational) for backward compatibility
//                          with existing `xdm.alert.severity`
//                          dashboards; the parser anchor is a thinner,
//                          coarser-bucket SEP-native enum that fits
//                          cleanly into a column index.
//
// RELATIONSHIP TO datamodel.xql
// -----------------------------
// `datamodel.xql` reads both anchors via the keep-in-both
// `coalesce(<column-from-parser>, <derivation-from-_raw_log>)`
// convention. Rows ingested BEFORE this parser shipped, replayed
// sample data and backfills all model identically because the
// data-model rule independently derives the same values from
// `_raw_log` when the parser-stamped column is NULL. The parser
// adds a column lookup on stamped rows; the cost on un-stamped rows
// is exactly the regex chain the data-model rule has always run.
//
// CATEGORY DISCRIMINATOR ORDERING
// -------------------------------
// The if-chain ordering is significant -- earlier rows win:
//   1. AntiVirus is matched on the explicit `Potential risk found` /
//      `Virus found` markers before any other check so signed-binary
//      detections that happen to mention "Application" do not slip
//      to ApplicationControl.
//   2. IPS is matched on the unique `Intrusion URL:` token.
//   3. Tamper / DeviceControl / ApplicationControl come next because
//      they share `Action Type:` / `Rule:` markers with BEHAVIOR /
//      TRAFFIC respectively, and the more specific token wins.
//   4. Auth / Policy come before BehaviorMonitoring / Firewall on
//      the same reasoning -- a SEP audit event with a Rule: clause
//      should still be tagged as Policy / Auth.
//   5. BehaviorMonitoring vs Firewall is the legacy BEHAVIOR-vs-
//      TRAFFIC split (`Action Type:` distinguishes BEHAVIOR).
//   6. System catches the SEP Manager audit envelope last.
//
// SEVERITY DISCRIMINATOR
// ----------------------
// SEP forwarders emit a string `Severity:` token in some shapes
// (typically firewall / IPS) and a numeric `Sensitivity:` token in
// the RISK shape. The anchor prefers the native string when present,
// then maps the numeric ladder. Both are extracted into `tmp_*`
// non-anchor temps so the anchor body itself does not reference
// another anchor (avoids INFO-007 anchor-on-anchor).
//
// TIMESTAMP HANDLING
// ------------------
// SEP syslog uses RFC 3164 timestamps with no year. The year is
// derived from `_insert_time` and rolled back by one when the
// reconstructed timestamp is in the future (see the canonical Cisco
// ISE idiom in PRIVATE_DOCS/all_parsing_rules.txt). INFO-005 fires
// on this rule as an acknowledgement that year-boundary heuristics
// are inherently approximate; the alternative (no `_time`) is worse.
//
// Documentation: documentation.md (in this pack)
//
// SPDX-FileCopyrightText: GoCortexIO
// SPDX-License-Identifier: AGPL-3.0-or-later

[INGEST: vendor = "symantec", product = "endpoint_protection", target_dataset = "symantec_ep_raw", no_hit = keep]

filter
    _raw_log != null
    and _raw_log ~= "SymantecServer:"

| alter
    tmp_syslog_ts = arrayindex(regextract(_raw_log, "^<\d{1,3}>(\w{3}\s+\d{1,2}\s+\d{1,2}:\d{2}:\d{2})"), 0),
    tmp_year = format_timestamp("%Y", _insert_time),
    tmp_severity_native = arrayindex(regextract(_raw_log, "Severity:\s+(Info|Warning|Major|Critical)\b"), 0),
    tmp_sensitivity = arrayindex(regextract(_raw_log, "Sensitivity:\s+(\d)"), 0)

| alter
    _sep_category = if(
        _raw_log ~= "SymantecServer:\s+(?:Potential risk found|Virus found),",                "AntiVirus",
        _raw_log ~= ",Intrusion URL:",                                                        "IPS",
        _raw_log ~= "(?i)Tamper\s+Protection|Self-?Protection",                               "Tamper",
        _raw_log ~= "(?i)Device\s+Control",                                                   "DeviceControl",
        _raw_log ~= "(?i)Application\s+Control",                                              "ApplicationControl",
        _raw_log ~= "(?i)\b(Logon|Logoff|Authentication\s+(?:succeeded|failed))\b",           "Auth",
        _raw_log ~= "(?i)Policy\s+(?:has\s+been|applied|update|change)",                      "Policy",
        _raw_log ~= ",Action Type:",                                                          "BehaviorMonitoring",
        _raw_log ~= ",Rule:\s",                                                               "Firewall",
        _raw_log ~= "SymantecServer:\s+Site:\s",                                              "System"),
    _severity = coalesce(
        tmp_severity_native,
        if(
            tmp_sensitivity ~= "^[89]$",  "Critical",
            tmp_sensitivity ~= "^[67]$",  "Major",
            tmp_sensitivity ~= "^[45]$",  "Warning",
            tmp_sensitivity ~= "^[1-3]$", "Info"))

| alter
    tmp_time_thisyear = if(tmp_syslog_ts != null and tmp_syslog_ts != "", parse_timestamp("%Y %b %e %H:%M:%S", concat(tmp_year, " ", tmp_syslog_ts)), null)

| alter
    tmp_time_lastyear = if(tmp_time_thisyear != null and timestamp_diff(tmp_time_thisyear, current_time(), "MILLISECOND") > 0, parse_timestamp("%Y %b %e %H:%M:%S", concat(to_string(subtract(to_integer(tmp_year), 1)), " ", tmp_syslog_ts)), null)

| alter
    _time = coalesce(tmp_time_lastyear, tmp_time_thisyear)

| fields -tmp_syslog_ts, -tmp_year, -tmp_severity_native, -tmp_sensitivity, -tmp_time_thisyear, -tmp_time_lastyear;
