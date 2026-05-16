// GoCortex Concierge -- XDM modeling rule
// Dataset: gocortex_concierge_raw
// Vendor:  GoCortex | Product: Concierge
//
// Maps Mars Banking Initiative Concierge events into XDM. Reads
// the six anchor columns stamped by the parser
// (`_event_type`, `_session_id`, `_turn_id`, `_response_path`,
// `_source_ip`, `_request_path`) via the keep-in-both
// `coalesce(<parser column>, <json_extract over _raw_log>)` shape
// so legacy rows that pre-date the anchor parser still land in
// XDM. Pulls the remaining JSON fields (user_agent, model_name,
// prompt_text, response_text, document_label, source_url,
// body_length, body_preview) from `_raw_log` directly.
//
// Reference: attached_assets/Pasted--GoCortex-Broken-Ban-...txt
// (Stream 4 of 4, "netbank_concierge").
//
// CONVENTIONS
// -----------
// - The wire payload carries three discriminated event_type
//   variants: "prompt", "response", "context_loaded". The model
//   uses if-chains keyed on `tmp_event_type` so per-variant
//   fields (`prompt_text`, `response_text`, `body_preview`,
//   `document_label`, `source_url`, `body_length`) only land in
//   XDM on the variants that actually carry them. Cross-variant
//   leakage would corrupt detection-rule pivots.
// - `xdm.event.type` carries a literal string per variant
//   (`GENAI_PROMPT`, `GENAI_RESPONSE`, `GENAI_CONTEXT_LOADED`)
//   rather than an XDM_CONST enum -- the XDM_CONST.EVENT_TYPE
//   table has no GenAI taxonomy yet and the literal string keeps
//   the producer's intent visible in the field.
// - `xdm.session_context_id` carries the producer's `session_id`
//   so detection authors can correlate every Concierge turn from
//   one browser session without joining on a timestamp window. A
//   spike of distinct session_ids reusing the same canonical
//   injection trigger is a campaign signal.
// - `xdm.event.id` carries `turn_id` so the prompt + response
//   pair from a single /chat HTTP request collapse to the same
//   event id; correlation is index-friendly without a window
//   join. Falls back to `_id` when the producer omitted turn_id.
// - `xdm.event.outcome` is set on response events only:
//   `OUTCOME_FAILED` when the response_path is leak-bearing
//   ("llm-bypass leak" or "llm+leak augmented"); `OUTCOME_SUCCESS`
//   on the benign paths ("intent", "llm", "fallback",
//   "fallback after error"). Prompt and context_loaded events
//   have no inherent outcome -- left null.
// - `xdm.alert.severity` is a literal string ("High" /
//   "Informational") because the XDM schema declares
//   `alert.severity` as a free-form String -- there is no
//   `XDM_CONST.SEVERITY_LEVEL_*` enum in the engine's
//   schema-of-record. "High" is reserved for the two leak-bearing
//   response_path values; everything else is left null so
//   detection rules can light up cleanly on `severity = "High"`.
// - `xdm.alert.subcategory` mirrors the producer's
//   `response_path` verbatim on response events. Detection
//   authors filter on the two leak-bearing values directly.
// - `xdm.alert.original_alert_id` is set to `turn_id` on leak
//   responses so `alert.severity` has its companion identifier
//   (WARN-032). The producer has no separate alert id concept;
//   the turn_id is the natural pivot because the matching
//   prompt event for the same /chat HTTP request also carries
//   it (different event_type, same turn_id).
// - `xdm.target.application.name` carries `model_name` so the
//   LLM (the side the user is talking to) is the modelled target
//   application. `target.application.publisher` is stamped
//   "GoCortex" so the Concierge build line surfaces in target
//   pivots without a join.
// - `xdm.target.url` is set on context_loaded events that came
//   from `/concierge/load_url` and carries the raw `source_url`
//   field (the route fetched it with no SSRF guard, so the URL
//   is itself an attacker-controlled IOC).
// - `xdm.target.resource.name` carries `document_label` on
//   context_loaded events (URL for /load_url, user-supplied
//   label for /load_text); analysts pivot on the label without
//   re-parsing the JSON.
// - `xdm.target.sent_bytes` carries `body_length` -- the count
//   of bytes the producer fed into the Concierge context window
//   AFTER the route's own truncation (8000 chars for /load_url,
//   16000 for /load_text). Note this is NOT the length of
//   `body_preview` (which the producer caps at 1000 chars).
// - `xdm.event.description` is event-type-conditional:
//   `prompt_text` on prompt events, `response_text` on response
//   events, `body_preview` on context_loaded events. The
//   producer truncates `body_preview` to 1000 chars; prompt /
//   response strings are untruncated. Detection rules grep on
//   the description directly.
// - `"unknown"` is collapsed to NULL for source_ip and user_agent
//   so XDM identity columns do not ingest the sentinel string.
// - `xdm.network.http.method` is hard-coded to
//   `XDM_CONST.HTTP_METHOD_POST` because the producer guarantees
//   every Concierge sink is POST-only; no need to re-derive it.
// - All `tmp_*` intermediates are stripped at the end (INFO-006).

[MODEL: dataset = gocortex_concierge_raw]

filter _raw_log != null

| alter
    tmp_event_type = coalesce(_event_type, json_extract_scalar(_raw_log, "$.event_type")),
    tmp_session_id = coalesce(_session_id, json_extract_scalar(_raw_log, "$.session_id")),
    tmp_turn_id = coalesce(_turn_id, json_extract_scalar(_raw_log, "$.turn_id")),
    tmp_response_path = coalesce(_response_path, json_extract_scalar(_raw_log, "$.response_path")),
    tmp_source_ip_raw = coalesce(_source_ip, json_extract_scalar(_raw_log, "$.source_ip")),
    tmp_request_path = coalesce(_request_path, json_extract_scalar(_raw_log, "$.request_path")),
    tmp_user_agent_raw = json_extract_scalar(_raw_log, "$.user_agent"),
    tmp_model_name = json_extract_scalar(_raw_log, "$.model_name"),
    tmp_prompt_text = json_extract_scalar(_raw_log, "$.prompt_text"),
    tmp_response_text = json_extract_scalar(_raw_log, "$.response_text"),
    tmp_document_label = json_extract_scalar(_raw_log, "$.document_label"),
    tmp_source_url = json_extract_scalar(_raw_log, "$.source_url"),
    tmp_body_length_raw = json_extract_scalar(_raw_log, "$.body_length"),
    tmp_body_preview = json_extract_scalar(_raw_log, "$.body_preview")

| alter
    tmp_source_ip = if(tmp_source_ip_raw != null and tmp_source_ip_raw != "unknown", tmp_source_ip_raw),
    tmp_user_agent = if(tmp_user_agent_raw != null and tmp_user_agent_raw != "unknown", tmp_user_agent_raw),
    tmp_body_length = if(tmp_body_length_raw != null and tmp_body_length_raw != "", to_integer(tmp_body_length_raw), null),
    tmp_is_leak = if(tmp_response_path = "llm-bypass leak", true, tmp_response_path = "llm+leak augmented", true, false)

| alter
    xdm.observer.vendor = "GoCortex",
    xdm.observer.product = "Concierge",
    xdm.observer.type = "Chatbot Application",
    xdm.source.ipv4 = tmp_source_ip,
    xdm.source.user_agent = tmp_user_agent,
    xdm.network.http.method = XDM_CONST.HTTP_METHOD_POST,
    xdm.network.http.url = tmp_request_path,
    xdm.session_context_id = tmp_session_id,
    xdm.event.id = coalesce(tmp_turn_id, _id),
    xdm.event.type = if(
        tmp_event_type = "prompt", "GENAI_PROMPT",
        tmp_event_type = "response", "GENAI_RESPONSE",
        tmp_event_type = "context_loaded", "GENAI_CONTEXT_LOADED",
        null),
    xdm.event.outcome = if(
        tmp_event_type = "response" and tmp_is_leak = true, XDM_CONST.OUTCOME_FAILED,
        tmp_event_type = "response", XDM_CONST.OUTCOME_SUCCESS,
        null),
    xdm.event.description = if(
        tmp_event_type = "prompt", tmp_prompt_text,
        tmp_event_type = "response", tmp_response_text,
        tmp_event_type = "context_loaded", tmp_body_preview,
        null),
    xdm.target.application.name = tmp_model_name,
    xdm.target.application.publisher = "GoCortex",
    xdm.target.resource.name = if(tmp_event_type = "context_loaded", tmp_document_label, null),
    xdm.target.url = if(tmp_event_type = "context_loaded", tmp_source_url, null),
    xdm.target.sent_bytes = if(tmp_event_type = "context_loaded", tmp_body_length, null),
    xdm.alert.subcategory = if(tmp_event_type = "response", tmp_response_path, null),
    xdm.alert.severity = if(tmp_event_type = "response" and tmp_is_leak = true, "High", null),
    xdm.alert.original_alert_id = if(tmp_event_type = "response" and tmp_is_leak = true, coalesce(tmp_turn_id, _id), null)

| fields -tmp_event_type, -tmp_session_id, -tmp_turn_id, -tmp_response_path, -tmp_source_ip_raw, -tmp_source_ip, -tmp_request_path, -tmp_user_agent_raw, -tmp_user_agent, -tmp_model_name, -tmp_prompt_text, -tmp_response_text, -tmp_document_label, -tmp_source_url, -tmp_body_length_raw, -tmp_body_length, -tmp_body_preview, -tmp_is_leak;
