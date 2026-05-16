// Apache Tomcat (GoCortex Broken Bank) -- Parsing rule
// Dataset: apache_tomcat_raw
// Vendor:  Apache | Product: Tomcat
//
// Tomcat ships native Apache "combined" access log lines from the
// Broken Bank exploit container, one POST body per request. The
// wire format is:
//
//   %h %l %u %t "%r" %>s %b "%{Referer}i" "%{User-Agent}i"
//
// Reference: attached_assets/Pasted--GoCortex-Broken-Ban-...txt
// (Stream 1 of 4, "tomcat_access").
//
// The parser regex-extracts all nine combined-log fields from
// `_raw_log`. Five of those nine are stamped as anchor columns
// (`_client_ip`, `_request_method`, `_status_code`,
// `_request_uri`, `_user_agent`) so interactive analyst
// searches against `apache_tomcat_raw` can filter on indexed
// columns instead of running the same combined-log regex on
// every row, every query. The remaining four (remote_logname,
// remote_user, referer, response_bytes) are extracted as
// non-anchor parser columns (`_remote_logname`, `_remote_user`,
// `_referer`, `_response_bytes`) so the data-model rule can
// read them without re-parsing `_raw_log`.
//
// `"-"` is collapsed to NULL for `_remote_logname`,
// `_remote_user`, `_referer`, and `_response_bytes` per the
// OpenAPI schema notes -- those four CLF fields use the
// literal "-" sentinel for "no value".
//
// No XDM mappings live in this rule. All XDM lifting lives in
// `datamodel.xql`.
//
// RELATIONSHIP TO datamodel.xql
// -----------------------------
// `datamodel.xql` implements the keep-in-both anchor pattern
// from `PRIVATE_DOCS/anchor_field_design.md` (Task #100): each
// XDM mapping reads `coalesce(<parser column>, <regextract over
// _raw_log>)` so newly-ingested rows are served by the cheap
// anchor read while legacy / replayed rows that pre-date this
// parser still produce XDM output via the in-model regex
// fallback. The fallback patterns mirror the parser regexes
// here, with the literal-quote bytes written as `\x22` (regex
// hex-escape) instead of `\"` to avoid an analyser false
// positive in `collectStageStatements` -- the wire-format
// match is identical (Cortex regex evaluates `\x22` as the
// `"` character).
//
// TIMESTAMP HANDLING
// ------------------
// Apache CLF carries a full year + zone offset
// (DD/Mon/YYYY:HH:MM:SS +ZZZZ) so no year-boundary reconstruction
// is required (compare with the EfficientIP syslog parser which
// has to derive the year from `_insert_time`).
//
// Documentation: documentation.md (in this pack)

[INGEST: vendor = "apache", product = "tomcat", target_dataset = "apache_tomcat_raw", no_hit = keep]

filter
    _raw_log != null
    and _raw_log ~= "^\S+\s+\S+\s+\S+\s+\[[^\]]+\]\s+\""

| alter
    tmp_remote_logname = arrayindex(regextract(_raw_log, "^\S+\s+(\S+)\s"), 0),
    tmp_remote_user = arrayindex(regextract(_raw_log, "^\S+\s+\S+\s+(\S+)\s+\["), 0),
    tmp_referer = arrayindex(regextract(_raw_log, "\"\s+\d{3}\s+(?:\d+|-)\s+\"([^\"]*)\""), 0),
    tmp_response_bytes = arrayindex(regextract(_raw_log, "\"\s+\d{3}\s+(\d+|-)\s+\""), 0),
    tmp_clf_ts = arrayindex(regextract(_raw_log, "\[([^\]]+)\]"), 0)

| alter
    _client_ip = arrayindex(regextract(_raw_log, "^(\S+)\s"), 0),
    _request_method = arrayindex(regextract(_raw_log, "\"([A-Z]+)\s+\S+\s+HTTP/"), 0),
    _request_uri = arrayindex(regextract(_raw_log, "\"[A-Z]+\s+(\S+)\s+HTTP/"), 0),
    _status_code = to_integer(arrayindex(regextract(_raw_log, "\"\s+(\d{3})\s+(?:\d+|-)\s+\""), 0)),
    _user_agent = arrayindex(regextract(_raw_log, "\"\s+\d{3}\s+(?:\d+|-)\s+\"[^\"]*\"\s+\"([^\"]*)\"\s*$"), 0),
    _remote_logname = if(tmp_remote_logname = "-", null, tmp_remote_logname),
    _remote_user = if(tmp_remote_user = "-", null, tmp_remote_user),
    _referer = if(tmp_referer = "-" or tmp_referer = "", null, tmp_referer),
    _response_bytes = if(tmp_response_bytes = "-" or tmp_response_bytes = null, null, to_integer(tmp_response_bytes)),
    _time = if(tmp_clf_ts != null and tmp_clf_ts != "", parse_timestamp("%d/%b/%Y:%H:%M:%S %z", tmp_clf_ts), null)

| fields -tmp_remote_logname, -tmp_remote_user, -tmp_referer, -tmp_response_bytes, -tmp_clf_ts;
