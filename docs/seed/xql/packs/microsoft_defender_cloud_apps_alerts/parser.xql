// Microsoft Defender for Cloud Apps Alerts -- Parsing rule (anchor extraction)
// Dataset: microsoftcloudappsecurity_generic_alert_raw
// Vendor:  Microsoft | Product: Defender for Cloud Apps (formerly MCAS)
//
// Seventh worked example of the ANCHOR pattern described in
// PRIVATE_DOCS/anchor_field_design.md. The XSIAM ingest pipeline
// pre-flattens MDCA alert documents into top-level columns
// (`policy{}`, `account[]`, `ip[]`, `country[]`, `service[]`,
// `policyRule[]`, plus scalar fields like `title`, `severity`,
// `severityValue`, `resolutionStatusValue`, `stories[]`, `intent[]`).
// This parser pre-extracts the two universal triage axes -- policy
// type and severity band -- so analyst searches over
// `microsoftcloudappsecurity_generic_alert_raw` filter on indexed
// columns instead of running `json_extract_scalar()` over the
// `policy` JSON column on every row, every query, every time.
//
// Anchors written by this parser:
//   1. `_policy_type`   -- ~8 closed values from the vendor taxonomy:
//                          AnomalyDetectionPolicy, PolicyRuleAlerts,
//                          ThreatProtection, MalwareProtection,
//                          DataLossPrevention, AccessPolicy,
//                          SessionPolicy, OAUTH_APP_PERMISSION.
//                          Drives alert-family branching ("show me only
//                          the DLP alerts", "show me only the Threat
//                          Protection alerts"). Lifted from
//                          `policy.policyType`.
//   2. `_severity_band` -- 3 closed string values: LOW, MEDIUM, HIGH.
//                          MDCA emits severity as a string enum at the
//                          top level so no bucketing is required; the
//                          band anchor is a straight pull from the
//                          `severity` field. Drives the universal
//                          severity filter without forcing analysts to
//                          remember the integer 0/1/2/3 ->
//                          Low/Medium/High/Informational mapping that
//                          `severityValue` carries.
//
// Note: `severityValue = 3` (Informational) has no `severity` enum
// counterpart on this dataset, so `_severity_band` is intentionally
// NULL on Informational rows (that is, only LOW/MEDIUM/HIGH are
// emitted). Analysts who need Informational coverage continue to read
// `severityValue` directly.
//
// PAYLOAD SHAPE -- pattern D
// --------------------------
// `_raw_log` is null on this dataset; the XSIAM connector pre-flattens
// each entity class into its own top-level column (carried as JSON
// strings for the object-shaped fields). The structural pre-filter
// `title != null` mirrors the data-model rule's own filter: every
// real MDCA alert carries a non-null `title`, and rows without one
// are not alerts. `no_hit = keep` ensures the rare row that fails
// the pre-filter still lands in the dataset so the data-model rule
// can deal with it; the parser just declines to stamp the anchors
// or `_time`.
//
// No XDM mappings live in this rule -- all heavy lifting stays in
// `datamodel.xql` in this pack. The parser only writes the two
// anchor columns plus `_time`.
//
// RELATIONSHIP TO datamodel.xql
// -----------------------------
// `datamodel.xql` reads both anchors via the keep-in-both convention
// from `PRIVATE_DOCS/anchor_field_design.md`:
//
//   _policy_type   = coalesce(_policy_type,
//                              json_extract_scalar(to_string(policy),
//                                                  "$.policyType"))
//   _severity_band = coalesce(_severity_band, severity)
//
// Both anchors are then sunk into XDM via `coalesce()` arms:
// `_policy_type` feeds `xdm.alert.subcategory` (winning over the
// vendor's free-text `policy.label` when present), and
// `_severity_band` feeds `xdm.alert.severity` (winning over the
// integer-decoded `_severity_label` when present). Using them as
// coalesce arms (not concat() arguments) means the analyser does
// not raise ERR-025 for either intermediate.
//
// TIMESTAMP HANDLING
// ------------------
// The vendor sends an event timestamp as Unix epoch milliseconds.
// In the redacted ingest sample the field surfaces both as the
// top-level `timestamp` column and inside the `_alert_data` mirror
// object, so the parser tries both before falling back to leaving
// `_time` NULL (Cortex then uses `_insert_time` automatically).
// No format-string parsing or year-boundary reconstruction is
// required because the value is already absolute.
//
// Documentation: documentation.md (in this pack)
//
// SPDX-FileCopyrightText: GoCortexIO
// SPDX-License-Identifier: AGPL-3.0-or-later

[INGEST: vendor = "microsoft", product = "cloud_app_security", target_dataset = "microsoftcloudappsecurity_generic_alert_raw", no_hit = keep]

filter
    title != null

| alter
    _policy_type = json_extract_scalar(to_string(policy), "$.policyType"),
    _severity_band = severity,
    tmp_event_ts = coalesce(
        to_string(timestamp),
        json_extract_scalar(to_string(_alert_data), "$.timestamp"))

| alter
    _time = to_timestamp(to_integer(tmp_event_ts), "MILLIS")

| fields -tmp_event_ts;
