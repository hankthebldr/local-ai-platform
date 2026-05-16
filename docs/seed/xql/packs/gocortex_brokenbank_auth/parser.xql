// GoCortex BrokenBank Auth -- Parsing rule (anchor extraction)
// Dataset: gocortex_brokenbank_raw
// Vendor:  GoCortex | Product: BrokenBank
//
// NetBank authentication events emitted by the Broken Bank login
// route (`app.py /login`) and by the Faker-driven background
// generator (`auth_traffic_generator.py`, ~4 events / minute). One
// compact JSON object per attempt.
//
// Reference: attached_assets/Pasted--GoCortex-Broken-Ban-...txt
// (Stream 3 of 4, "netbank_auth").
//
// Anchors written by this parser:
//   1. `_username`     -- the login identifier supplied by the
//                          client. High-cardinality but the primary
//                          pivot for authentication forensics.
//   2. `_status`       -- "success" or "failure" (closed enum).
//                          Drives outcome bucketing without
//                          re-parsing the JSON on every search.
//   3. `_source_ip`    -- the originating client IP (or NULL when
//                          Flask emitted the literal string
//                          "unknown").
//   4. `_country`      -- ISO-3166-1 alpha-2 country code from
//                          `log_shipping._detect_country()`.
//                          Currently hard-coded to "AU" by the
//                          producer; modelled as an anchor so a
//                          future GeoIP roll-out is a no-op for
//                          downstream queries.
//   5. `_device_type`  -- closed enum {mobile, tablet, desktop,
//                          unknown}. Derived from a User-Agent
//                          substring sniff; analysts filter on it
//                          to separate handset traffic from
//                          desktop sessions and to spot UA-less
//                          attacker tooling.
//   6. `_simulated`    -- boolean. true for synthetic background
//                          traffic from the Faker generator;
//                          false for real interactive logins.
//                          Detection rules typically filter on
//                          `_simulated = false` to exclude noise.
//
// `"unknown"` is collapsed to NULL for `_source_ip` so downstream
// XDM `xdm.source.ipv4` does not ingest the literal sentinel
// string. `user_agent` carries the same sentinel and is collapsed
// in the data-model rule for the same reason.
//
// No XDM mappings live in this rule. `_time` is stamped from the
// ISO-8601 `timestamp` field which always carries microsecond
// precision plus the `+00:00` suffix
// (`datetime.now(timezone.utc).isoformat()`).
//
// RELATIONSHIP TO datamodel.xql
// -----------------------------
// `datamodel.xql` reads the six anchor columns this parser
// stamps via the keep-in-both `coalesce(<parser column>, json_extract_scalar(_raw_log, ...))` pattern (anchor_field_design.md, Task #100) and does not
// re-extract them from `_raw_log`. Secondary fields that the
// parser does not anchor (`user_agent`, `failure_reason`,
// `event_id`) are still pulled at model time via
// `json_extract_scalar`. Legacy / replayed rows that pre-date
// this parser are still modelled correctly: the keep-in-both
// `coalesce` reaches the `json_extract_scalar` fallback when
// the anchor column is NULL, so the datamodel produces XDM
// output regardless of whether the parser has run on a given
// row.
//
// Documentation: documentation.md (in this pack)

[INGEST: vendor = "gocortex", product = "brokenbank", target_dataset = "gocortex_brokenbank_raw", no_hit = keep]

filter
    _raw_log != null
    and _raw_log ~= "(?i)\"event_type\":\\s*\"authentication\""

| alter
    tmp_source_ip = json_extract_scalar(_raw_log, "$.source_ip"),
    tmp_simulated = json_extract_scalar(_raw_log, "$.simulated"),
    tmp_event_ts = json_extract_scalar(_raw_log, "$.timestamp")

| alter
    _username = json_extract_scalar(_raw_log, "$.username"),
    _status = json_extract_scalar(_raw_log, "$.status"),
    _source_ip = if(tmp_source_ip != null and tmp_source_ip != "unknown", tmp_source_ip),
    _country = json_extract_scalar(_raw_log, "$.country"),
    _device_type = json_extract_scalar(_raw_log, "$.device_type"),
    _simulated = if(tmp_simulated = "true", to_boolean("TRUE"), tmp_simulated = "false", to_boolean("FALSE")),
    _time = if(tmp_event_ts != null and tmp_event_ts != "", parse_timestamp("%Y-%m-%dT%H:%M:%E*S%Ez", tmp_event_ts), null)

| fields -tmp_source_ip, -tmp_simulated, -tmp_event_ts;
