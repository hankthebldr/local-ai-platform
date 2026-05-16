// GoCortex BBWAF -- XDM modeling rule
// Dataset: gocortex_bbwaf_raw
// Vendor:  GoCortex | Product: BBWAF
//
// Maps the BBWAF JSON record into XDM. Reads the four anchor
// columns stamped by the parser
// (`_source_ip`, `_vulnerability`, `_endpoint`, `_request_method`)
// via the keep-in-both `coalesce(<parser column>, <json_extract
// over _raw_log>)` shape so legacy rows that pre-date the
// anchor parser still land in XDM. Pulls the remaining JSON
// fields (user_agent, query_string, payload, severity, action,
// event_id, request_path) from `_raw_log` directly.
//
// Reference: attached_assets/Pasted--GoCortex-Broken-Ban-...txt
// (Stream 2 of 4, "netbank_application").
//
// CONVENTIONS
// -----------
// - Every BBWAF record represents a request that hit a known-
//   vulnerable endpoint -- the WAF has identified the request as
//   matching one of the 36 vulnerability classes. Outcome is
//   modelled as `XDM_CONST.OUTCOME_FAILED` (the security control
//   raised an alert), not the application's HTTP status (the
//   underlying request often still returned 200).
// - HTTP method uses `XDM_CONST.HTTP_METHOD_*` for the closed
//   verb set documented in the OpenAPI schema. The if-chain's
//   default arm is null (omitted) so unknown verbs do not
//   silently land as raw strings -- WARN-029.
// - `"unknown"` is collapsed to NULL for `_source_ip` and
//   `user_agent` so XDM identity columns do not ingest the
//   sentinel string.
// - `xdm.alert.category` is mapped through an exhaustive if-chain
//   over the closed 36-value `vulnerability` enum to the nearest
//   `XDM_CONST.THREAT_CATEGORY_*` tokens (the existing XDM threat
//   taxonomy used across packs). The original vulnerability
//   string is mirrored into `xdm.alert.original_threat_name` so
//   the source label is never lost when the taxonomy mapping
//   collapses two enum values into the same XDM constant.
// - `xdm.event.description` carries the producer-truncated
//   `_payload` (already capped at 1000 chars).
// - The raw `query_string` is appended to `xdm.network.http.url`
//   when present (no dedicated `xdm.network.http.url_query` path
//   exists in the XDM schema -- the task spec referenced it but
//   the schema only carries the unified `url` field).
// - All `tmp_*` intermediates are stripped at the end (INFO-006).

[MODEL: dataset = gocortex_bbwaf_raw]

filter _raw_log != null

| alter
    tmp_user_agent_raw = json_extract_scalar(_raw_log, "$.user_agent"),
    tmp_request_path = json_extract_scalar(_raw_log, "$.request_path"),
    tmp_query_string = json_extract_scalar(_raw_log, "$.query_string"),
    tmp_payload = json_extract_scalar(_raw_log, "$.payload"),
    tmp_severity = json_extract_scalar(_raw_log, "$.severity"),
    tmp_action = json_extract_scalar(_raw_log, "$.action"),
    tmp_event_id = json_extract_scalar(_raw_log, "$.event_id"),
    tmp_source_ip_raw = coalesce(_source_ip, json_extract_scalar(_raw_log, "$.source_ip")),
    tmp_vulnerability = coalesce(_vulnerability, json_extract_scalar(_raw_log, "$.vulnerability")),
    tmp_endpoint = coalesce(_endpoint, json_extract_scalar(_raw_log, "$.endpoint")),
    tmp_method = coalesce(_request_method, json_extract_scalar(_raw_log, "$.request_method"))

| alter
    tmp_source_ip = if(tmp_source_ip_raw != null and tmp_source_ip_raw != "unknown", tmp_source_ip_raw),
    tmp_user_agent = if(tmp_user_agent_raw != null and tmp_user_agent_raw != "unknown", tmp_user_agent_raw)

| alter
    xdm.observer.vendor = "GoCortex",
    xdm.observer.product = "BBWAF",
    xdm.observer.type = "Web Application Firewall",
    xdm.source.ipv4 = tmp_source_ip,
    xdm.source.user_agent = tmp_user_agent,
    xdm.network.http.method = if(
        tmp_method = "GET", XDM_CONST.HTTP_METHOD_GET,
        tmp_method = "POST", XDM_CONST.HTTP_METHOD_POST,
        tmp_method = "PUT", XDM_CONST.HTTP_METHOD_PUT,
        tmp_method = "DELETE", XDM_CONST.HTTP_METHOD_DELETE,
        tmp_method = "HEAD", XDM_CONST.HTTP_METHOD_HEAD,
        tmp_method = "OPTIONS", XDM_CONST.HTTP_METHOD_OPTIONS,
        tmp_method = "PATCH", XDM_CONST.HTTP_METHOD_PATCH,
        null),
    xdm.network.http.url = if(tmp_query_string != null and tmp_query_string != "", concat(coalesce(tmp_endpoint, tmp_request_path, ""), "?", tmp_query_string), coalesce(tmp_endpoint, tmp_request_path)),
    xdm.target.resource.name = tmp_endpoint,
    xdm.event.type = "SECURITY_DETECTION",
    xdm.event.id = coalesce(tmp_event_id, _id),
    xdm.event.outcome = XDM_CONST.OUTCOME_FAILED,
    xdm.event.description = tmp_payload,
    xdm.alert.name = tmp_vulnerability,
    xdm.alert.original_threat_name = tmp_vulnerability,
    xdm.alert.original_alert_id = tmp_event_id,
    xdm.alert.severity = tmp_severity,
    xdm.alert.category = if(
        tmp_vulnerability = "SQL_INJECTION", XDM_CONST.THREAT_CATEGORY_SQL_INJECTION,
        tmp_vulnerability = "NOSQL_INJECTION", XDM_CONST.THREAT_CATEGORY_SQL_INJECTION,
        tmp_vulnerability = "LDAP_INJECTION", XDM_CONST.THREAT_CATEGORY_CODE_EXECUTION,
        tmp_vulnerability = "CODE_INJECTION", XDM_CONST.THREAT_CATEGORY_CODE_EXECUTION,
        tmp_vulnerability = "TEMPLATE_INJECTION", XDM_CONST.THREAT_CATEGORY_CODE_EXECUTION,
        tmp_vulnerability = "LOG_INJECTION", XDM_CONST.THREAT_CATEGORY_CODE_EXECUTION,
        tmp_vulnerability = "INSECURE_DESERIALIZATION", XDM_CONST.THREAT_CATEGORY_CODE_EXECUTION,
        tmp_vulnerability = "CROSS_SITE_SCRIPTING", XDM_CONST.THREAT_CATEGORY_CODE_EXECUTION,
        tmp_vulnerability = "HTTP_HEADER_INJECTION", XDM_CONST.THREAT_CATEGORY_PROTOCOL_ANOMALY,
        tmp_vulnerability = "XML_EXTERNAL_ENTITY", XDM_CONST.THREAT_CATEGORY_INFO_LEAK,
        tmp_vulnerability = "PATH_TRAVERSAL", XDM_CONST.THREAT_CATEGORY_INFO_LEAK,
        tmp_vulnerability = "INFORMATION_DISCLOSURE", XDM_CONST.THREAT_CATEGORY_INFO_LEAK,
        tmp_vulnerability = "IMPROPER_ERROR_HANDLING", XDM_CONST.THREAT_CATEGORY_INFO_LEAK,
        tmp_vulnerability = "IMPROPER_OUTPUT_NEUTRALISATION", XDM_CONST.THREAT_CATEGORY_INFO_LEAK,
        tmp_vulnerability = "NULL_POINTER_ACCESS", XDM_CONST.THREAT_CATEGORY_INFO_LEAK,
        tmp_vulnerability = "SERVER_SIDE_REQUEST_FORGERY", XDM_CONST.THREAT_CATEGORY_PROTOCOL_ANOMALY,
        tmp_vulnerability = "JWT_VERIFICATION_BYPASS", XDM_CONST.THREAT_CATEGORY_INSECURE_CREDENTIALS,
        tmp_vulnerability = "BROKEN_ACCESS_CONTROL", XDM_CONST.THREAT_CATEGORY_INSECURE_CREDENTIALS,
        tmp_vulnerability = "AUTHORISATION_BYPASS", XDM_CONST.THREAT_CATEGORY_INSECURE_CREDENTIALS,
        tmp_vulnerability = "ANONYMOUS_BINDING", XDM_CONST.THREAT_CATEGORY_INSECURE_CREDENTIALS,
        tmp_vulnerability = "CSRF_DISABLED", XDM_CONST.THREAT_CATEGORY_INSECURE_CREDENTIALS,
        tmp_vulnerability = "CLEARTEXT_CREDENTIALS", XDM_CONST.THREAT_CATEGORY_INSECURE_CREDENTIALS,
        tmp_vulnerability = "HARDCODED_CREDENTIALS", XDM_CONST.THREAT_CATEGORY_INSECURE_CREDENTIALS,
        tmp_vulnerability = "WEAK_CRYPTOGRAPHY", XDM_CONST.THREAT_CATEGORY_INSECURE_CREDENTIALS,
        tmp_vulnerability = "WEAK_TLS_CONFIGURATION", XDM_CONST.THREAT_CATEGORY_INSECURE_CREDENTIALS,
        tmp_vulnerability = "WEAK_KEY_EXCHANGE", XDM_CONST.THREAT_CATEGORY_INSECURE_CREDENTIALS,
        tmp_vulnerability = "WEAK_RANDOM_GENERATION", XDM_CONST.THREAT_CATEGORY_INSECURE_CREDENTIALS,
        tmp_vulnerability = "UNAUTHENTICATED_KEY_EXCHANGE", XDM_CONST.THREAT_CATEGORY_INSECURE_CREDENTIALS,
        tmp_vulnerability = "CLEARTEXT_TRANSMISSION", XDM_CONST.THREAT_CATEGORY_PROTOCOL_ANOMALY,
        tmp_vulnerability = "UNENCRYPTED_CONNECTION", XDM_CONST.THREAT_CATEGORY_PROTOCOL_ANOMALY,
        tmp_vulnerability = "INSECURE_CONFIGURATION", XDM_CONST.THREAT_CATEGORY_INSECURE_CREDENTIALS,
        tmp_vulnerability = "INSECURE_FILE_PERMISSIONS", XDM_CONST.THREAT_CATEGORY_INSECURE_CREDENTIALS,
        tmp_vulnerability = "INSECURE_MODEL_DOWNLOAD", XDM_CONST.THREAT_CATEGORY_DOWNLOADER,
        tmp_vulnerability = "INSECURE_MODEL_LOADING", XDM_CONST.THREAT_CATEGORY_CODE_EXECUTION,
        tmp_vulnerability = "INSECURE_MODEL_SECURITY", XDM_CONST.THREAT_CATEGORY_INSECURE_CREDENTIALS,
        tmp_vulnerability = "RESOURCE_EXHAUSTION", XDM_CONST.THREAT_CATEGORY_DOS,
        null),
    xdm.event.outcome_reason = tmp_action

| fields -tmp_source_ip_raw, -tmp_source_ip, -tmp_user_agent_raw, -tmp_user_agent, -tmp_vulnerability, -tmp_endpoint, -tmp_method, -tmp_request_path, -tmp_query_string, -tmp_payload, -tmp_severity, -tmp_action, -tmp_event_id;
