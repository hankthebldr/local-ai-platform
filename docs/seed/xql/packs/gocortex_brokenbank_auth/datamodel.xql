// GoCortex BrokenBank Auth -- XDM modeling rule
// Dataset: gocortex_brokenbank_raw
// Vendor:  GoCortex | Product: BrokenBank
//
// Maps NetBank authentication events into XDM. Reads the six
// anchor columns stamped by the parser
// (`_username`, `_status`, `_source_ip`, `_country`, `_device_type`,
// `_simulated`) via the keep-in-both `coalesce(<parser column>,
// <json_extract over _raw_log>)` shape so legacy rows that
// pre-date the anchor parser still land in XDM. Pulls the
// remaining JSON fields (user_agent, failure_reason, event_id)
// from `_raw_log` directly.
//
// Reference: attached_assets/Pasted--GoCortex-Broken-Ban-...txt
// (Stream 3 of 4, "netbank_auth").
//
// CONVENTIONS
// -----------
// - Outcome uses `XDM_CONST.OUTCOME_*` enum tokens, not literal
//   strings (SUG-004 / SUG-008).
// - `"unknown"` is collapsed to NULL for source_ip and user_agent
//   so XDM identity columns do not ingest the sentinel string.
// - `_simulated = true` rows come from the Faker-driven background
//   generator. The flag is mirrored as a tag in `xdm.event.tags`
//   only when true: a NULL or false `_simulated` leaves the tag
//   list NULL so detection authors filter synthetic noise out
//   with a tag membership check (the documented hook). No "real"
//   counter-tag is emitted -- absence of "simulated" is the
//   signal -- and the outer null guard keeps WARN-036 clean.
// - `_device_type` is a producer-side classification (closed
//   enum: mobile / tablet / desktop / unknown) of the User-Agent
//   shape. It is mirrored exhaustively into
//   `xdm.source.host.device_category` via an if-chain so unknown
//   values land as null instead of as a raw string -- WARN-029.
//   Detection / classification labels are NOT placed in
//   `xdm.network.http.browser` (per WARN-031 that field is
//   reserved for the declared browser name).
// - Country is auto-enriched by Cortex when populated -- the
//   auth pack writes the producer-stamped ISO-3166-1 alpha-2
//   code into `xdm.source.location.country` (the XDM schema does
//   not carry a dedicated `country_code` path; the country field
//   accepts either the alpha-2 code or the long form name).
// - All `tmp_*` intermediates are stripped at the end (INFO-006).

[MODEL: dataset = gocortex_brokenbank_raw]

filter _raw_log != null

| alter
    tmp_user_agent_raw = json_extract_scalar(_raw_log, "$.user_agent"),
    tmp_failure_reason = json_extract_scalar(_raw_log, "$.failure_reason"),
    tmp_event_id = json_extract_scalar(_raw_log, "$.event_id"),
    tmp_username = coalesce(_username, json_extract_scalar(_raw_log, "$.username")),
    tmp_status = coalesce(_status, json_extract_scalar(_raw_log, "$.status")),
    tmp_source_ip_raw = coalesce(_source_ip, json_extract_scalar(_raw_log, "$.source_ip")),
    tmp_country = coalesce(_country, json_extract_scalar(_raw_log, "$.country")),
    tmp_device_type = coalesce(_device_type, json_extract_scalar(_raw_log, "$.device_type")),
    tmp_simulated_raw = json_extract_scalar(_raw_log, "$.simulated")

| alter
    tmp_source_ip = if(tmp_source_ip_raw != null and tmp_source_ip_raw != "unknown", tmp_source_ip_raw),
    tmp_user_agent = if(tmp_user_agent_raw != null and tmp_user_agent_raw != "unknown", tmp_user_agent_raw),
    tmp_simulated = coalesce(_simulated, if(tmp_simulated_raw = "true", to_boolean("TRUE"), tmp_simulated_raw = "false", to_boolean("FALSE"), null))

| alter
    xdm.observer.vendor = "GoCortex",
    xdm.observer.product = "BrokenBank",
    xdm.observer.type = "Banking Application",
    xdm.source.user.username = tmp_username,
    xdm.source.ipv4 = tmp_source_ip,
    xdm.source.user_agent = tmp_user_agent,
    xdm.source.location.country = tmp_country,
    xdm.source.host.device_category = if(
        tmp_device_type = "mobile", "Mobile",
        tmp_device_type = "tablet", "Tablet",
        tmp_device_type = "desktop", "Personal Computer",
        tmp_device_type = "unknown", null,
        null),
    xdm.event.type = "AUTHENTICATION",
    xdm.event.id = coalesce(tmp_event_id, _id),
    xdm.event.outcome = if(
        tmp_status = "success", XDM_CONST.OUTCOME_SUCCESS,
        tmp_status = "failure", XDM_CONST.OUTCOME_FAILED,
        XDM_CONST.OUTCOME_UNKNOWN),
    xdm.event.outcome_reason = tmp_failure_reason,
    xdm.event.description = concat("Login ", coalesce(tmp_status, "?"), " for ", coalesce(tmp_username, "?")),
    xdm.event.tags = if(tmp_simulated = true, arraycreate("simulated"), null)

| fields -tmp_username, -tmp_status, -tmp_source_ip_raw, -tmp_source_ip, -tmp_country, -tmp_device_type, -tmp_simulated_raw, -tmp_simulated, -tmp_user_agent_raw, -tmp_user_agent, -tmp_failure_reason, -tmp_event_id;
