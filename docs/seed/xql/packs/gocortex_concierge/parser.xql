// GoCortex Concierge -- Parsing rule (anchor extraction)
// Dataset: gocortex_concierge_raw
// Vendor:  GoCortex | Product: Concierge
//
// Mars Banking Initiative Concierge chatbot events. The Concierge
// is an intentionally vulnerable in-app LLM assistant exposed at
// `/concierge` with a chat sink at `/concierge/chat` and two
// indirect-injection sinks at `/concierge/load_url` and
// `/concierge/load_text`. One compact JSON object per event.
//
// Reference: attached_assets/Pasted--GoCortex-Broken-Ban-...txt
// (Stream 4 of 4, "netbank_concierge").
//
// Three discriminated event_type variants share a common envelope:
//   - "prompt"          : inbound user message to /concierge/chat
//   - "response"        : Concierge model output for /concierge/chat
//   - "context_loaded"  : a /load_url or /load_text upload entered
//                          the Concierge context window
//
// Anchors written by this parser:
//   1. `_event_type`     -- closed enum {prompt, response,
//                            context_loaded}. Discriminator for the
//                            datamodel's per-variant if-chains;
//                            also the primary detection-rule pivot.
//   2. `_session_id`     -- 32-char lowercase hex from
//                            `uuid4().hex`. Stable across all
//                            Concierge turns from one browser
//                            session. A spike of distinct
//                            session_ids reusing the same
//                            canonical injection trigger is a
//                            campaign signal.
//   3. `_turn_id`        -- 32-char lowercase hex per event. The
//                            "prompt" + "response" pair for one
//                            /chat HTTP request share the same
//                            turn_id, so detection rules can
//                            correlate the user's payload with the
//                            model's leaked output without joining
//                            on session + timestamp windows.
//   4. `_response_path`  -- response code-path tag (response events
//                            only; null on prompt / context_loaded).
//                            Two values are leak-bearing
//                            ("llm-bypass leak" and
//                            "llm+leak augmented"); the others
//                            ("intent", "llm", "fallback",
//                            "fallback after error") are benign.
//                            Anchored so prompt-injection alerts
//                            do not have to re-parse the JSON.
//   5. `_source_ip`      -- offender IP. Producer writes literal
//                            "unknown" when Flask cannot determine
//                            `request.remote_addr`; collapsed to
//                            null here so XDM `source.ipv4` does
//                            not ingest the sentinel string.
//   6. `_request_path`   -- closed enum {/concierge/chat,
//                            /concierge/load_url,
//                            /concierge/load_text}. Mirrors which
//                            sink fired so analysts can pivot
//                            without an `event_type` join.
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
// parser does not anchor (`user_agent`, `model_name`,
// `prompt_text`, `response_text`, `document_label`, `source_url`,
// `body_length`, `body_preview`) are still pulled at model time
// via `json_extract_scalar`. Legacy / replayed rows that pre-date
// this parser are still modelled correctly: the keep-in-both
// `coalesce` reaches the `json_extract_scalar` fallback when
// the anchor column is NULL, so the datamodel produces XDM
// output regardless of whether the parser has run on a given
// row.
//
// Documentation: documentation.md (in this pack)

[INGEST: vendor = "gocortex", product = "concierge", target_dataset = "gocortex_concierge_raw", no_hit = keep]

filter
    _raw_log != null
    and _raw_log ~= "(?i)\"product\":\\s*\"Concierge\""

| alter
    tmp_source_ip = json_extract_scalar(_raw_log, "$.source_ip"),
    tmp_event_ts = json_extract_scalar(_raw_log, "$.timestamp")

| alter
    _event_type = json_extract_scalar(_raw_log, "$.event_type"),
    _session_id = json_extract_scalar(_raw_log, "$.session_id"),
    _turn_id = json_extract_scalar(_raw_log, "$.turn_id"),
    _response_path = json_extract_scalar(_raw_log, "$.response_path"),
    _source_ip = if(tmp_source_ip != null and tmp_source_ip != "unknown", tmp_source_ip),
    _request_path = json_extract_scalar(_raw_log, "$.request_path"),
    _time = if(tmp_event_ts != null and tmp_event_ts != "", parse_timestamp("%Y-%m-%dT%H:%M:%E*S%Ez", tmp_event_ts), null)

| fields -tmp_source_ip, -tmp_event_ts;
