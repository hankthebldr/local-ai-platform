// Trend Micro Vision One -- Parsing rule (anchor extraction)
// Dataset: trend_micro_vision_one_gc_raw
// Vendor:  Trend Micro | Product: Vision One
//
// Shared parser for the two Vision One MODEL packs that both fan out
// of the same target_dataset:
//   - PRIVATE_DOCS/packs/trend_micro_vision_one_detections/
//   - PRIVATE_DOCS/packs/trend_micro_vision_one_endpoint_activity/
//
// The Vision One feed multiplexes several event families into one
// JSON-per-line dataset, discriminated by the top-level `source`
// field. Without anchors every analyst search has to walk the JSON
// document to discover which shape the row carries; with anchors the
// same query becomes a column-equality on indexed columns. See
// PRIVATE_DOCS/anchor_field_design.md for the underlying concept and
// why three or more anchors per dataset is almost always wrong.
//
// Anchors written by this parser:
//   1. _source         -- the event-family discriminator copied
//                         verbatim from the top-level `source` JSON
//                         field. Both MODELs filter on this. The
//                         canonical Vision One ath-* API vocabulary
//                         is "workbenchAlert" (workbench detections),
//                         "endpointActivityData" (XES activity feed),
//                         "messageActivityData", "networkActivityData",
//                         "containerActivityData". The legacy alias
//                         "detections" is also seen in earlier ingest
//                         and is treated as a synonym of
//                         "workbenchAlert" by the detections MODEL.
//                         The parser does not enumerate a closed
//                         vocabulary -- whatever the vendor emits is
//                         stamped through.
//   2. _severity_band  -- the upper-cased risk band lifted from
//                         detail.filterRiskLevel ("CRITICAL", "HIGH",
//                         "MEDIUM", "LOW"). Drives severity filters
//                         in both MODELs. NULL when filterRiskLevel
//                         is absent or "info" -- informational rows
//                         do not participate in band filtering.
//   3. _event_category -- six-value endpoint-activity sub-shape
//                         discriminator derived from
//                         detail.eventId (1=process, 2=file,
//                         3=network, 4=dns, 5=registry, 6=account).
//                         NULL on detection rows and on event ids
//                         outside the closed set (which are surfaced
//                         verbatim by the endpoint-activity MODEL
//                         via its own broader `event_category`
//                         derivation).
//
// Three anchors is at the upper end of the "two anchors is the sweet
// spot" guidance in anchor_field_design.md. The third
// (_event_category) is justified here because the
// endpoint-activity feed alone fans out into >=14 sub-shapes and the
// six-bucket discriminator is the single highest-leverage filter
// analysts run against that pack.
//
// RELATIONSHIP TO datamodel.xql
// -----------------------------
// Both MODELs follow the keep-in-both anchor convention from
// PRIVATE_DOCS/anchor_field_design.md: each anchor consumed by a
// MODEL is re-derived inside the MODEL via
// `coalesce(<parser-stamped column>, <expression over the raw row>)`.
// On parser-stamped rows the MODEL pays one column read and a
// `coalesce` short-circuit; on un-stamped rows (legacy ingest,
// replayed samples, backfills) the same expression the MODEL would
// have run anyway is evaluated. The MODELs therefore remain
// backfill-safe and the parser remains purely additive.
//
// TIMESTAMP HANDLING
// ------------------
// Vision One JSON carries the millisecond epoch event time in the
// top-level `eventTime` field. The parser stamps `_time` from it
// when the field is a numeric epoch; rows without a numeric
// eventTime fall through to Cortex's default `_insert_time`.
//
// INGEST GATE
// -----------
// The head filter requires `_raw_log` to contain a literal `"source"`
// JSON key so the parser does not run on rows that are not Vision
// One JSON. `no_hit = keep` ensures any row that fails the gate
// still lands in `trend_micro_vision_one_gc_raw` so the MODELs can
// fall back to their keep-in-both expressions over the raw row.
//
// Documentation: documentation.md (in each consuming pack)
//
// SPDX-FileCopyrightText: GoCortexIO
// SPDX-License-Identifier: AGPL-3.0-or-later

[INGEST: vendor = "trend_micro", product = "vision_one", target_dataset = "trend_micro_vision_one_gc_raw", no_hit = keep]

filter
    _raw_log != null
    and _raw_log ~= "\"source\""

| alter
    tmp_filter_risk = json_extract_scalar(_raw_log, "$.detail.filterRiskLevel"),
    tmp_event_id = to_integer(json_extract_scalar(_raw_log, "$.detail.eventId")),
    tmp_event_time = json_extract_scalar(_raw_log, "$.eventTime")

| alter
    _source = json_extract_scalar(_raw_log, "$.source"),
    _severity_band = if(
        tmp_filter_risk = "critical", "CRITICAL",
        tmp_filter_risk = "high", "HIGH",
        tmp_filter_risk = "medium", "MEDIUM",
        tmp_filter_risk = "low", "LOW"),
    _event_category = if(
        tmp_event_id = 1, "process",
        tmp_event_id = 2, "file",
        tmp_event_id = 3, "network",
        tmp_event_id = 4, "dns",
        tmp_event_id = 5, "registry",
        tmp_event_id = 6, "account"),
    _time = if(tmp_event_time ~= "^\d+$", to_timestamp(to_integer(tmp_event_time), "MILLI"))

| fields -tmp_filter_risk, -tmp_event_id, -tmp_event_time;
