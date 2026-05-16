// ExtraHop RevealX -- Parsing rule (anchor extraction)
// Dataset: extrahop_revealx_raw
// Vendor:  ExtraHop | Product: RevealX
//
// Fourth worked example of the ANCHOR pattern described in
// PRIVATE_DOCS/anchor_field_design.md, and the FIRST pack to ship
// an array-typed anchor (`_detection_category`). RevealX detection
// rows arrive with `_raw_log = null` (Pattern D in the offline
// knowledge file): the XSIAM ingest pipeline pre-parses the API
// payload into top-level columns plus several nested columns.
// The PARSER stage and the DATAMODEL stage see DIFFERENT shapes
// of the same nested columns -- this is the central doctrine for
// this pack and the source of every save-time error so far:
//
//   - PARSER stage runs against the raw ingest payload while the
//     nested fields are still native types from the JSON parser.
//     `categories`, `participants`, `mitre_tactics` and
//     `mitre_techniques` are all native Arrays at this point.
//     A `-> []` JSON-array cast on any of them is rejected by the
//     ingest validator with "Error in json_extract_array, <col>
//     field. Expected string, received an array".
//   - DATAMODEL stage runs against the persisted dataset, where
//     complex columns get serialised to JSON strings on write.
//     The same four columns arrive as JSON strings, and a bare
//     reference to any of them in an array function is rejected
//     with "Field <col> for function arraymap is invalid.
//     Expected array but received string". They MUST be cast
//     with `-> []` before any array-function call there.
//
// `_detection_category` therefore reads `categories` as a bare
// column reference here (the cast belongs in datamodel.xql, not
// here). The `_risk_band` anchor only touches the numeric
// `risk_score` column and is unaffected by the nested-column
// shape mismatch. `properties` is the only nested column that
// arrives as a typed Object in BOTH stages, read with the scalar
// `->` field accessor downstream. The two anchors below are
// derived from these pre-parsed columns rather than from
// `_raw_log`.
//
// Anchors written by this parser:
//   1. `_detection_category` -- ARRAY anchor. A single RevealX
//                               detection can be tagged with
//                               multiple categories (e.g. both
//                               `lateral_movement` and
//                               `command_and_control`); collapsing
//                               to the first one would silently
//                               drop the secondary tags from
//                               column-equality searches. Stored
//                               as the parsed `categories[]` array
//                               itself; analyst queries use
//                               `arraycontains(_detection_category,
//                               "lateral_movement")` rather than
//                               `_detection_category = "..."`.
//                               Closed vocabulary of ~10 values:
//                               `lateral_movement`,
//                               `command_and_control`,
//                               `exploitation`, `reconnaissance`,
//                               `actions_on_objective`,
//                               `hardening`, `caution`, `database`,
//                               `network_infrastructure`, `unknown`.
//   2. `_risk_band`          -- 3-value bucket from the numeric
//                               `risk_score` (0-99), one of
//                               {LOW (<30), MEDIUM (30-69),
//                               HIGH (>=70)}. Raw `risk_score`
//                               would be too high cardinality to
//                               be a useful indexed column;
//                               banding to three values gives
//                               analysts a clean "show me only
//                               high-risk detections" filter
//                               without forcing them to remember
//                               the threshold.
//
// ARRAY-TYPED ANCHOR -- DOCTRINE DEVIATION
// ----------------------------------------
// `PRIVATE_DOCS/anchor_field_design.md` describes anchors as
// "small, high-selectivity discriminators" and the three previous
// worked examples (EfficientIP DDI, AWS GuardDuty, Cisco WSA) all
// stamp scalar columns. RevealX is the first pack where the
// natural discriminator is an ARRAY: a detection can legitimately
// belong to several MITRE-aligned categories at once, and any
// scalar projection (first element, joined string, hashed bag)
// would either drop information or break column-equality. The
// trade-off is paid in two places:
//   - Storage: the column is wider than a scalar would be (still
//     small in practice -- at most a handful of short strings per
//     row), but bigger than a single byte.
//   - Query syntax: analysts use `arraycontains(_detection_category,
//     "...")` rather than `_detection_category = "..."`. Cortex
//     still pushes the predicate down to the indexed column.
// Both costs are small relative to the alternative (analysts
// re-deriving the array from the `categories` column on
// every query). The doctrine is explicitly extended here: array
// anchors ARE allowed when the underlying discriminator is
// genuinely multi-valued. They remain rare; do not reach for an
// array anchor when a scalar will do.
//
// `_risk_band` is a conventional scalar anchor and follows the
// same shape as `_severity_band` in the AWS GuardDuty parser.
//
// No XDM mappings live in this rule -- all heavy lifting stays
// in `datamodel.xql` in this pack. The parser only writes the
// two anchor columns and stamps `_time`.
//
// RELATIONSHIP TO datamodel.xql
// -----------------------------
// `datamodel.xql` does NOT read either anchor. Cortex compiles a
// data model rule against the dataset schema before any row runs,
// so a bare reference to a column absent from the schema (i.e. on
// tenants whose RevealX data was ingested before this parser
// shipped) fails to save with "unknown field" even when wrapped
// in `coalesce()`. The data model rule therefore derives
// `_categories_arr` from the raw `categories` column directly and
// derives `risk_band` from the numeric `risk_score` directly via
// the same 3-value bucket this parser uses. The two anchors below
// remain useful for analyst-side XQL on enriched rows (see the
// `arraycontains(_detection_category, "...")` / `_risk_band =
// "HIGH"` examples in documentation.md). The MODEL itself drives
// `xdm.alert.severity` off the four-band `_severity` derivation
// (Critical/High/Medium/Low) -- `risk_band` exists for
// interactive triage symmetry with this parser column and as a
// defensive fallback in `xdm.event.description`.
//
// CONTENT-GUARD PRE-FILTER
// ------------------------
// `_raw_log` is null on this dataset, so the EfficientIP /
// GuardDuty idiom of (raw-log not-null AND raw-log regex-match)
// does not apply. The pre-filter instead checks structural
// markers: a RevealX detection always carries an `id` and at
// least one of `risk_score` / `categories`. Rows missing both
// are not RevealX detections and the parser declines to stamp
// the anchors (or `_time`). `no_hit = keep` ensures the rows
// still land in `extrahop_revealx_raw` so the data-model rule
// can deal with them.
//
// TIMESTAMP HANDLING
// ------------------
// RevealX ships epoch-millisecond integers in `start_time` and
// `end_time`. `_time` is set from `start_time` (the moment the
// detection began); the `end_time` is folded into
// `xdm.event.duration` in the MODEL via `subtract()`. No
// year-boundary reconstruction is required (compare with the
// EfficientIP parser, which has to derive the year from
// `_insert_time`).
//
// Documentation: documentation.md (in this pack)
//
// SPDX-FileCopyrightText: GoCortexIO
// SPDX-License-Identifier: AGPL-3.0-or-later

[INGEST: vendor = "extrahop", product = "revealx", target_dataset = "extrahop_revealx_raw", no_hit = keep]

filter
    id != null
    and (risk_score != null or categories != null)

| alter
    _detection_category = categories,
    _risk_band = if(
        risk_score >= 70, "HIGH",
        risk_score >= 30, "MEDIUM",
        risk_score != null, "LOW"),
    _time = to_timestamp(start_time, "MILLIS");
