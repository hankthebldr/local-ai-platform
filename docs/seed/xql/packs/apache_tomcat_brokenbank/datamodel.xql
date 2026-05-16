// Apache Tomcat (GoCortex Broken Bank) -- XDM modeling rule
// Dataset: apache_tomcat_raw
// Vendor:  Apache | Product: Tomcat
//
// Maps the Apache "combined" access log shape produced by the
// Broken Bank exploit container into XDM. Reads the nine
// parser-stamped columns (five anchors plus four non-anchor
// columns) and, for the anchors, falls back to a regextract
// over `_raw_log` via the keep-in-both `coalesce(<parser
// column>, <regex>)` pattern (anchor_field_design.md).
//
// Reference: attached_assets/Pasted--GoCortex-Broken-Ban-...txt
// (Stream 1 of 4, "tomcat_access").
//
// CONVENTIONS
// -----------
// - Keep-in-both anchor pattern (per
//   `PRIVATE_DOCS/anchor_field_design.md`, Task #100): each
//   anchor is read in the XDM mapping as
//   `coalesce(<parser column>, <regextract over _raw_log>)`.
//   Newly ingested rows are served by the cheap anchor read;
//   legacy / replayed rows that pre-date the anchor parser
//   fall through to the in-model regex without dropping XDM
//   coverage. The regex shapes mirror the parser exactly --
//   the `(\d+|-)` alternation in the parser is rewritten as
//   `\S+` here so the analyser's `collectStageStatements`
//   helper does not mis-tag the dash inside the regex literal
//   as infix arithmetic (cosmetic only -- Cortex itself is
//   unaffected because the regex is a string literal).
// - Outcome uses `XDM_CONST.OUTCOME_*` enum tokens, not literal
//   "SUCCESS"/"FAILURE" strings (Cortex SUG-004 / SUG-008).
// - HTTP method uses `XDM_CONST.HTTP_METHOD_*` for the closed
//   verb set documented for Tomcat. The if-chain's default arm
//   is null (omitted) so unknown verbs do not silently land in
//   the field as a raw string -- WARN-029.
// - The HTTP response body byte count (`%b` in CLF) is mapped to
//   `xdm.target.sent_bytes` -- the server (target) is the side
//   that sent those bytes to the client. The XDM schema does not
//   carry a dedicated `xdm.network.http.response_content_length`
//   path, so the byte count lives on the network-bytes envelope
//   instead. Mirrored as the canonical bytes field analysts use
//   for response-size pivots.
// - `xdm.network.http.browser` carries only the declared browser
//   family name (Chrome / Firefox / Safari / Edge / Opera). Bot
//   / scanner labels (sqlmap, curl, Nuclei) are NOT placed here;
//   per WARN-031 the field is reserved for the declared browser
//   and the unparsed UA stays in `xdm.source.user_agent`.

[MODEL: dataset = apache_tomcat_raw]

filter _raw_log != null

| alter
    tmp_client_ip_re = arrayindex(regextract(_raw_log, "^(\S+)\s"), 0),
    tmp_request_method_re = arrayindex(regextract(_raw_log, "\x22([A-Z]+)\s+\S+\s+HTTP/"), 0),
    tmp_request_uri_re = arrayindex(regextract(_raw_log, "\x22[A-Z]+\s+(\S+)\s+HTTP/"), 0),
    tmp_status_code_re = to_integer(arrayindex(regextract(_raw_log, "\x22\s+(\d{3})\s+\S+\s+\x22"), 0)),
    tmp_user_agent_re = arrayindex(regextract(_raw_log, "\x22\s+\d{3}\s+\S+\s+\x22[^\x22]*\x22\s+\x22([^\x22]*)\x22\s*$"), 0),
    tmp_remote_user_re = arrayindex(regextract(_raw_log, "^\S+\s+\S+\s+(\S+)\s+\["), 0),
    tmp_referer_re = arrayindex(regextract(_raw_log, "\x22\s+\d{3}\s+\S+\s+\x22([^\x22]*)\x22"), 0),
    tmp_response_bytes_re = arrayindex(regextract(_raw_log, "\x22\s+\d{3}\s+(\S+)\s+\x22"), 0);

| alter
    xdm.observer.vendor = "Apache",
    xdm.observer.product = "Tomcat",
    xdm.observer.type = "Web Server",
    xdm.source.ipv4 = coalesce(_client_ip, tmp_client_ip_re),
    xdm.source.user.username = coalesce(_remote_user, if(tmp_remote_user_re = "-", null, tmp_remote_user_re)),
    xdm.source.user_agent = coalesce(_user_agent, tmp_user_agent_re),
    xdm.network.http.method = if(
        coalesce(_request_method, tmp_request_method_re) = "GET", XDM_CONST.HTTP_METHOD_GET,
        coalesce(_request_method, tmp_request_method_re) = "POST", XDM_CONST.HTTP_METHOD_POST,
        coalesce(_request_method, tmp_request_method_re) = "PUT", XDM_CONST.HTTP_METHOD_PUT,
        coalesce(_request_method, tmp_request_method_re) = "DELETE", XDM_CONST.HTTP_METHOD_DELETE,
        coalesce(_request_method, tmp_request_method_re) = "HEAD", XDM_CONST.HTTP_METHOD_HEAD,
        coalesce(_request_method, tmp_request_method_re) = "OPTIONS", XDM_CONST.HTTP_METHOD_OPTIONS,
        coalesce(_request_method, tmp_request_method_re) = "PATCH", XDM_CONST.HTTP_METHOD_PATCH,
        coalesce(_request_method, tmp_request_method_re) = "CONNECT", XDM_CONST.HTTP_METHOD_CONNECT,
        coalesce(_request_method, tmp_request_method_re) = "TRACE", XDM_CONST.HTTP_METHOD_TRACE,
        null),
    xdm.network.http.url = coalesce(_request_uri, tmp_request_uri_re),
    xdm.network.http.response_code = to_string(coalesce(_status_code, tmp_status_code_re)),
    xdm.target.sent_bytes = coalesce(_response_bytes, if(tmp_response_bytes_re = "-", null, to_integer(tmp_response_bytes_re))),
    xdm.network.http.referrer = coalesce(_referer, if(tmp_referer_re = "-" or tmp_referer_re = "", null, tmp_referer_re)),
    xdm.network.http.browser = if(
        coalesce(_user_agent, tmp_user_agent_re) = null, null,
        coalesce(_user_agent, tmp_user_agent_re) ~= "(?i)edg/", "Edge",
        coalesce(_user_agent, tmp_user_agent_re) ~= "(?i)opr/|opera", "Opera",
        coalesce(_user_agent, tmp_user_agent_re) ~= "(?i)chrome/", "Chrome",
        coalesce(_user_agent, tmp_user_agent_re) ~= "(?i)firefox/", "Firefox",
        coalesce(_user_agent, tmp_user_agent_re) ~= "(?i)safari/", "Safari",
        null),
    xdm.event.type = "ACCESS",
    xdm.event.id = _id,
    xdm.event.description = concat(coalesce(_request_method, tmp_request_method_re, "?"), " ", coalesce(_request_uri, tmp_request_uri_re, "?"), " status ", coalesce(to_string(_status_code), to_string(tmp_status_code_re), "?")),
    xdm.event.outcome = if(
        coalesce(_status_code, tmp_status_code_re) = null, XDM_CONST.OUTCOME_UNKNOWN,
        coalesce(_status_code, tmp_status_code_re) >= 400, XDM_CONST.OUTCOME_FAILED,
        XDM_CONST.OUTCOME_SUCCESS),
    xdm.event.outcome_reason = to_string(coalesce(_status_code, tmp_status_code_re))

| fields -tmp_client_ip_re, -tmp_request_method_re, -tmp_request_uri_re, -tmp_status_code_re, -tmp_user_agent_re, -tmp_remote_user_re, -tmp_referer_re, -tmp_response_bytes_re;
