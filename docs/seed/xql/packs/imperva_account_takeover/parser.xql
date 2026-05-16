// Imperva Account Takeover Protection -- Parsing rule (anchor extraction)
// Dataset: imperva_accounttakeover_raw
// Vendor:  Imperva | Product: Account Takeover Protection
//
// Fifth worked example of the ANCHOR pattern described in
// PRIVATE_DOCS/anchor_field_design.md, and the simplest pack in the
// sprint: both anchors are already the underscore names the data-model
// rule has always used, so the parser just stamps them at ingest and
// the MODEL gains a one-token coalesce around each.
//
// Anchors written by this parser:
//   1. `_event_type`  -- ~6 closed values: LOGIN_FAILURE, LOGIN_SUCCESS,
//                        ACCOUNT_TAKEOVER, SUSPICIOUS_LOGIN,
//                        MFA_CHALLENGE, MFA_SUCCESS. Drives every
//                        per-event-type branching path the data-model
//                        rule already runs and is the universal
//                        analyst filter for "show me only the takeover
//                        attempts" / "show me only failed logins".
//   2. `_risk_level`  -- 4 closed values (vendor lowercase): low,
//                        medium, high, critical. Universal triage
//                        filter; tiny vocabulary. The MODEL already
//                        compares against the lowercase form when
//                        normalising to xdm.alert.severity, so the
//                        parser stamps the raw vendor value verbatim
//                        (no case-folding) to keep both code paths
//                        identical.
//
// PAYLOAD SHAPE -- pattern D
// --------------------------
// `_raw_log` is null on this dataset; the XSIAM JSON parser pre-flattens
// the payload into three top-level columns: `client{}`, `event{}`, and
// `imperva{}`, all carried as JSON strings. Both anchors live inside
// `imperva` and are extracted with the same `json_extract_scalar(
// to_string(imperva), "$.<field>")` shape the MODEL has used since
// Task #58.
//
// CONTENT-GUARD PRE-FILTER
// ------------------------
// `_raw_log != null` is unusable on a Pattern-D dataset. The pre-filter
// instead checks the structural marker `imperva != null`: every real
// ATO event carries the `imperva{}` object, and rows without it are
// not ATO events. `no_hit = keep` ensures the rare row that fails the
// pre-filter still lands in the dataset so the data-model rule can
// see it.
//
// No XDM mappings live in this rule -- all heavy lifting stays in
// `datamodel.xql` in this pack. The parser only writes the two
// anchor columns and stamps `_time` from the payload's event
// timestamp when one is present.
//
// RELATIONSHIP TO datamodel.xql
// -----------------------------
// `datamodel.xql` reads both anchors via the keep-in-both convention
// from `PRIVATE_DOCS/anchor_field_design.md`:
//
//   _event_type = coalesce(_event_type,
//                           json_extract_scalar(to_string(imperva),
//                                               "$.event_type"))
//   _risk_level = coalesce(_risk_level,
//                           json_extract_scalar(to_string(imperva),
//                                               "$.risk_level"))
//
// Rows ingested before this parser shipped, replayed sample data, and
// backfills all model identically because the data-model rule still
// runs the same `json_extract_scalar()` extraction it has always run
// when the anchor column is NULL. Parser-stamped rows pay one column
// read and a `coalesce` short-circuit instead of the JSON-path lookup.
//
// TIMESTAMP HANDLING
// ------------------
// Imperva ATO events do not consistently carry a payload-level event
// timestamp -- when present the field is one of `event.timestamp` /
// `imperva.timestamp` and is an ISO-8601 string. The parser tries
// both before falling back to leaving `_time` NULL (Cortex then uses
// `_insert_time` automatically). No year-boundary reconstruction is
// required because every candidate timestamp shape is fully
// qualified.
//
// Documentation: documentation.md (in this pack)
//
// SPDX-FileCopyrightText: GoCortexIO
// SPDX-License-Identifier: AGPL-3.0-or-later

[INGEST: vendor = "imperva", product = "accounttakeover", target_dataset = "imperva_accounttakeover_raw", no_hit = keep]

filter
    imperva != null

| alter
    _event_type = json_extract_scalar(to_string(imperva), "$.event_type"),
    _risk_level = json_extract_scalar(to_string(imperva), "$.risk_level"),
    tmp_event_ts = coalesce(
        json_extract_scalar(to_string(event), "$.timestamp"),
        json_extract_scalar(to_string(imperva), "$.timestamp"))

| alter
    _time = coalesce(
        parse_timestamp("%Y-%m-%dT%H:%M:%E*S%Ez", tmp_event_ts),
        parse_timestamp("%Y-%m-%dT%H:%M:%E*SZ", tmp_event_ts))

| fields -tmp_event_ts;
