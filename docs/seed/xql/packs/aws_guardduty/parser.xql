// AWS GuardDuty -- Parsing rule (anchor extraction)
// Dataset: aws_guardduty_generic_alert_raw
// Vendor:  Amazon | Product: GuardDuty
//
// Second worked example of the ANCHOR pattern described in
// PRIVATE_DOCS/anchor_field_design.md. GuardDuty findings fan out
// behind a single dataset across eight families: six carry a
// well-formed Service.Action.ActionType (AWS_API_CALL,
// NETWORK_CONNECTION, DNS_REQUEST, KUBERNETES_API_CALL, PORT_PROBE,
// RDS_LOGIN_ATTEMPT) and two actionless families are derived from
// the finding Type prefix or the Service.FeatureName
// (AttackSequence, MalwareProtection). Without the anchor, every
// interactive search has to re-derive this discriminator from the
// JSON payload on every row.
//
// Anchors written by this parser:
//   1. `_action_type`   -- 8-value finding-shape discriminator,
//                          one of {AWS_API_CALL, NETWORK_CONNECTION,
//                          DNS_REQUEST, KUBERNETES_API_CALL,
//                          PORT_PROBE, RDS_LOGIN_ATTEMPT,
//                          AttackSequence, MalwareProtection}.
//                          Drives every per-action search and
//                          feeds the per-shape branching in
//                          datamodel.xql.
//   2. `_severity_band` -- 3-value bucket from the numeric
//                          Severity float (1.0-8.9), one of
//                          {LOW (1.0-3.9), MEDIUM (4.0-6.9),
//                          HIGH (7.0-8.9)}. Findings at >=9.0
//                          (the Critical band introduced in 2024)
//                          are intentionally left without a band
//                          so analysts see a NULL on that slice
//                          rather than a misleading bucket. The
//                          numeric Severity stays the canonical
//                          source for `xdm.alert.severity` in
//                          datamodel.xql; this anchor exists for
//                          interactive triage queries.
//
// All extractions use defensive PascalCase + camelCase coalesces:
// the XSIAM JSON parser path determines the casing, and the same
// dataset can carry both shapes simultaneously after a vendor
// upgrade. This matches the convention the existing data-model
// rule has used since the first GuardDuty exercise.
//
// No XDM mappings live in this rule -- all heavy lifting stays in
// `datamodel.xql` in this pack. The parser only writes the two
// anchor columns and stamps `_time` from the GuardDuty
// `UpdatedAt`/`CreatedAt` ISO-8601 timestamp.
//
// RELATIONSHIP TO datamodel.xql
// -----------------------------
// `datamodel.xql` derives `service_action_type` via
// `coalesce(_action_type, <PascalCase/camelCase coalesce>,
// <Type/FeatureName fallbacks>)` -- the keep-in-both convention
// from `PRIVATE_DOCS/anchor_field_design.md`. Rows ingested before
// this parser shipped, replayed sample data, and backfills all
// continue to model identically because the data-model rule still
// performs the same extraction it has always performed when the
// anchor column is NULL. Parser-stamped rows pay one column read
// and a `coalesce` short-circuit instead of the JSON-path lookup.
//
// `_severity_band` is mirrored in the MODEL via the same
// keep-in-both convention: `datamodel.xql` derives
// `finding_severity_band = coalesce(_severity_band,
// <numeric Severity bucketing if-chain>)` and consumes it as a
// defensive fallback inside `xdm.alert.severity` so the bucket
// still drives the XDM enum if numeric `Severity` extraction
// ever fails. Parser-stamped rows short-circuit through the
// column read; legacy / replayed / backfilled rows fall through
// to the same bucketing logic the parser applies. Note the
// asymmetry: `xdm.alert.severity` carries a four-band vocabulary
// including `Critical` (driven directly off the numeric float),
// while `_severity_band` is intentionally three-band and leaves
// findings with `Severity >= 9.0` NULL so analysts see "no
// bucket" rather than a misleading one. Example analyst query:
// `dataset = aws_guardduty_generic_alert_raw | filter
// _severity_band = "HIGH"`.
//
// TIMESTAMP HANDLING
// ------------------
// GuardDuty findings carry full ISO-8601 timestamps in
// `UpdatedAt` and `CreatedAt` (string), so no year-boundary
// reconstruction is required (compare with the EfficientIP
// parser, which has to derive the year from `_insert_time`).
// The `coalesce` over two timestamp formats handles both the
// `...Z` and `...+00:00` zone suffixes the GuardDuty API can
// emit; if both fail, `_time` stays NULL and the row falls back
// to the platform default (typically `_insert_time`).
//
// Documentation: documentation.md (in this pack)
//
// SPDX-FileCopyrightText: GoCortexIO
// SPDX-License-Identifier: AGPL-3.0-or-later

[INGEST: vendor = "amazon", product = "guardduty", target_dataset = "aws_guardduty_generic_alert_raw", no_hit = keep]

filter
    _raw_log != null
    and _raw_log ~= "(?i)\"severity\""

| alter
    tmp_action_type_raw = coalesce(
        json_extract_scalar(_raw_log, "$.Service.Action.ActionType"),
        json_extract_scalar(_raw_log, "$.service.action.actionType")),
    tmp_feature_name = coalesce(
        json_extract_scalar(_raw_log, "$.Service.FeatureName"),
        json_extract_scalar(_raw_log, "$.service.featureName")),
    tmp_finding_type = coalesce(
        json_extract_scalar(_raw_log, "$.Type"),
        json_extract_scalar(_raw_log, "$.type")),
    tmp_severity = to_float(coalesce(
        json_extract_scalar(_raw_log, "$.Severity"),
        json_extract_scalar(_raw_log, "$.severity"))),
    tmp_event_ts = coalesce(
        json_extract_scalar(_raw_log, "$.UpdatedAt"),
        json_extract_scalar(_raw_log, "$.updatedAt"),
        json_extract_scalar(_raw_log, "$.CreatedAt"),
        json_extract_scalar(_raw_log, "$.createdAt"))

| alter
    _action_type = coalesce(
        tmp_action_type_raw,
        if(tmp_finding_type ~= "^AttackSequence", "AttackSequence"),
        if(tmp_feature_name ~= "(?i)Malware", "MalwareProtection")),
    _severity_band = if(
        tmp_severity < 4.0, "LOW",
        tmp_severity < 7.0, "MEDIUM",
        tmp_severity < 9.0, "HIGH"),
    _time = coalesce(
        parse_timestamp("%Y-%m-%dT%H:%M:%E*S%Ez", tmp_event_ts),
        parse_timestamp("%Y-%m-%dT%H:%M:%E*SZ", tmp_event_ts))

| fields -tmp_action_type_raw, -tmp_feature_name, -tmp_finding_type, -tmp_severity, -tmp_event_ts;
