// Imperva Audit Trail -- Parsing rule (anchor extraction)
// Dataset: imperva_audittrail_raw
// Vendor:  Imperva | Product: Cloud Application Security
//
// Sixth worked example of the ANCHOR pattern described in
// PRIVATE_DOCS/anchor_field_design.md. This pack pre-extracts a
// prefix-class discriminator and a small resource-type vocabulary
// out of the JSON-string `imperva` column so that interactive
// analyst searches against `imperva_audittrail_raw` filter on
// indexed columns instead of running `json_extract_scalar()` plus a
// `split()` on every row, every query, every time.
//
// Anchors written by this parser:
//   1. `_action_class`  -- ~7 closed values: SITE, USER, SSL, POLICY,
//                          LOGIN, ACCOUNT, SYSTEM. Derived by taking
//                          the first underscore-separated token of
//                          `imperva.audit_trail.event_action` (e.g.
//                          `SITE_REMOVE` -> `SITE`, `USER_LOGIN` ->
//                          `USER`). Matches the way analysts pivot on
//                          this dataset ("show me all the SSL ops")
//                          without forcing them to enumerate dozens of
//                          per-verb codes.
//   2. `_resource_type` -- ~8 closed values from the vendor's
//                          resource taxonomy: Site, User, Policy, SSL,
//                          Account, Rule, System (and NULL on
//                          system-initiated rows). Universal "what was
//                          touched" filter.
//
// PREFIX, NOT RAW VERB -- DELIBERATE CHOICE
// -----------------------------------------
// `event_action` itself runs to ~30-60 distinct verb codes (the full
// list is unpublished; only 267 `event_action_description` strings are
// documented). That is borderline too high cardinality for an anchor:
// each value would only narrow the firehose to ~1-3% of rows, and
// analysts would need to know the exact verb code spelling. The
// prefix collapses that into a 7-value class an analyst can type
// from memory; "give me all SSL ops" becomes
// `_action_class = "SSL"`. Drilling from class to verb stays in the
// query: filter on the SSL action_class then narrow by an SSL verb
// (for example the SSL_RENEW event_action).
//
// PAYLOAD SHAPE -- pattern D
// --------------------------
// `_raw_log` is null on this dataset; the XSIAM JSON parser
// pre-flattens the payload into top-level columns (`event{}`,
// `imperva{}`, `user{}`) carried as JSON strings. Both anchors live
// inside `imperva.audit_trail{}` and are extracted with the same
// `json_extract_scalar(to_string(imperva), "$.audit_trail.<field>")`
// shape the MODEL has used since Task #58.
//
// CONTENT-GUARD PRE-FILTER
// ------------------------
// `_raw_log != null` is unusable on a Pattern-D dataset. The pre-filter
// instead checks the structural marker `imperva != null`: every real
// audit-trail row carries the `imperva{}` object, and rows without it
// are not audit events. `no_hit = keep` ensures the rare row that
// fails the pre-filter still lands in the dataset so the data-model
// rule can see it.
//
// No XDM mappings live in this rule -- all heavy lifting stays in
// `datamodel.xql` in this pack. The parser only writes the two
// anchor columns plus `_time`.
//
// RELATIONSHIP TO datamodel.xql
// -----------------------------
// `datamodel.xql` reads both anchors via the keep-in-both convention
// from `PRIVATE_DOCS/anchor_field_design.md`. The `_action_class`
// fall-back must NOT just coalesce to the raw `event_action` -- the
// MODEL re-derives the prefix independently with the same
// `arrayindex(split(_event_action, "_"), 0)` expression so legacy and
// replayed rows behave identically:
//
//   _action_class  = coalesce(_action_class,
//                              arrayindex(split(_event_action, "_"), 0))
//   _resource_type = coalesce(_resource_type,
//                              json_extract_scalar(to_string(imperva),
//                                                  "$.audit_trail.resource_type"))
//
// TIMESTAMP HANDLING
// ------------------
// Imperva Audit Trail events do not consistently carry a payload-level
// event timestamp -- when present the field is one of `event.timestamp`
// or `imperva.audit_trail.timestamp` (ISO-8601). The parser tries
// both before falling back to leaving `_time` NULL (Cortex then uses
// `_insert_time` automatically). No year-boundary reconstruction is
// required because every candidate timestamp shape is fully qualified.
//
// Documentation: documentation.md (in this pack)
//
// SPDX-FileCopyrightText: GoCortexIO
// SPDX-License-Identifier: AGPL-3.0-or-later

[INGEST: vendor = "imperva", product = "audittrail", target_dataset = "imperva_audittrail_raw", no_hit = keep]

filter
    imperva != null

| alter
    tmp_event_action = json_extract_scalar(to_string(imperva), "$.audit_trail.event_action")

| alter
    _action_class = if(tmp_event_action != null, arrayindex(split(tmp_event_action, "_"), 0)),
    _resource_type = json_extract_scalar(to_string(imperva), "$.audit_trail.resource_type"),
    tmp_event_ts = coalesce(
        json_extract_scalar(to_string(event), "$.timestamp"),
        json_extract_scalar(to_string(imperva), "$.audit_trail.timestamp"))

| alter
    _time = coalesce(
        parse_timestamp("%Y-%m-%dT%H:%M:%E*S%Ez", tmp_event_ts),
        parse_timestamp("%Y-%m-%dT%H:%M:%E*SZ", tmp_event_ts))

| fields -tmp_event_action, -tmp_event_ts;
