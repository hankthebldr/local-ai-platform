// Mimecast Secure Email Gateway -- Parsing rule (anchor extraction)
// Dataset: mimecast_siem_raw
// Vendor:  Mimecast | Product: Secure Email Gateway
//
// Eighth worked example of the ANCHOR pattern described in
// PRIVATE_DOCS/anchor_field_design.md. Mimecast SIEM events arrive
// as top-level JSON columns (the XSIAM ingest pipeline pre-flattens
// the SIEM v2 event-collector payload, so `_raw_log` is empty on
// this dataset). Two universal mail-flow triage axes are pulled out
// here so analyst searches against `mimecast_siem_raw` filter on
// indexed columns instead of paying for `coalesce()` chains over
// raw vendor columns on every row, every query, every time.
//
// Anchors written by this parser:
//   1. `_event_type` -- ~6 closed values from the SIEM v2 vocabulary:
//                       receipt, process, delivery, url_protect,
//                       attachment_protect, journal. This is already
//                       the data-model rule's per-shape discriminator
//                       (every per-event-shape filter starts with
//                       `eventType = "..."`), so lifting it into a
//                       parser-stamped column converts that filter
//                       from a column read on the raw vendor field
//                       into a column read on a stamped anchor.
//                       Lifted from the top-level `eventType` column.
//   2. `_outcome`    -- ~6 closed values: Allow, Hold, Block, Bounce,
//                       Defer, Reject. The universal mail-flow triage
//                       answer to "did this mail get through?". The
//                       vendor splits the same concept across three
//                       columns depending on event shape -- `action`
//                       (process events), `status` (receipt events),
//                       `deliveryStatus` (delivery events) -- so the
//                       anchor is a `coalesce()` over all three
//                       computed once at ingest. Without this anchor
//                       every "show me only blocked mail" search has
//                       to re-evaluate the same coalesce on every row.
//
// `_direction` (inbound / outbound) was considered as a third anchor
// and deferred: it is correlated with `_event_type` (only `receipt`
// and `delivery` rows have a direction) and the marginal selectivity
// over the existing two anchors is small. The "two anchors per
// dataset is the sweet spot" discipline from
// `PRIVATE_DOCS/anchor_field_design.md` applies.
//
// PAYLOAD SHAPE -- pattern D
// --------------------------
// `_raw_log` is null on this dataset; every vendor field is its own
// top-level column carried through by the XSIAM connector. The
// structural pre-filter `eventType != null` mirrors the data-model
// rule's own filter: every real Mimecast SIEM event carries a
// non-null `eventType`, and rows without one are not Mimecast SIEM
// events. `no_hit = keep` ensures the rare row that fails the
// pre-filter still lands in the dataset so the data-model rule can
// deal with it; the parser just declines to stamp the anchors or
// `_time`.
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
//   _event_type = coalesce(_event_type, eventType)
//   _outcome    = coalesce(_outcome, action, status, deliveryStatus)
//
// Both anchors are then sunk into XDM via `coalesce()` arms (not
// `concat()` arguments) so the analyser does not raise ERR-025 on
// either intermediate. `_event_type` feeds `xdm.event.original_event_type`
// (winning over the raw `eventType` column when present), and
// `_outcome` feeds `xdm.event.outcome_reason` as a back-stop
// alongside the more specific free-text reasons (`blockReason`,
// `holdReason`, `rejectionType`, `rejectionInfo`).
//
// TIMESTAMP HANDLING
// ------------------
// Mimecast SIEM v2 emits an event timestamp as an ISO-8601 string in
// the `Datetime` column. Older feeds also surfaced epoch milliseconds
// in `timestamp`; the parser tries the ISO form first and falls back
// to the epoch form, leaving `_time` NULL when neither is present
// (Cortex then uses `_insert_time` automatically). No format-string
// gymnastics or year-boundary reconstruction is required because
// both forms are absolute.
//
// Documentation: documentation.md (in this pack)
//
// SPDX-FileCopyrightText: GoCortexIO
// SPDX-License-Identifier: AGPL-3.0-or-later

[INGEST: vendor = "mimecast", product = "secure_email_gateway", target_dataset = "mimecast_siem_raw", no_hit = keep]

filter
    eventType != null

| alter
    _event_type = eventType,
    _outcome = coalesce(action, status, deliveryStatus),
    tmp_iso_ts = Datetime,
    tmp_epoch_ts = to_string(timestamp)

| alter
    _time = coalesce(
        parse_timestamp("%Y-%m-%dT%H:%M:%E*S%Ez", tmp_iso_ts),
        parse_timestamp("%Y-%m-%dT%H:%M:%E*SZ", tmp_iso_ts),
        to_timestamp(to_integer(tmp_epoch_ts), "MILLIS"))

| fields -tmp_iso_ts, -tmp_epoch_ts;
