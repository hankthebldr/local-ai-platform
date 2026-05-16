// Cisco Web Security Appliance (WSA) -- XDM Data Model Rule
// Dataset: cisco_websecurityappliance_raw
// Vendor: Cisco | Product: Secure Web Appliance
//
// Maps Cisco WSA forward-proxy access log entries (Squid-style,
// space-delimited, syslog-wrapped) to the Cortex XDM schema. Each
// log entry records a single HTTP transaction together with the
// proxy's caching, scanning, and policy decisions.
//
// Documentation: cisco_wsa_access_log_xdm_model_rule_documentation.md
//
// SPDX-FileCopyrightText: GoCortexIO
// SPDX-License-Identifier: AGPL-3.0-or-later

[MODEL: dataset = cisco_websecurityappliance_raw]

// -- Stage 1: Strip syslog wrapper and extract the WSA log portion ----------
alter
    _wsa_log = arrayindex(regextract(_raw_log, "Info:\s+(.+)$"), 0),
    _syslog_fqdn = arrayindex(regextract(_raw_log, ">\w+\s+\d+\s+[\d:]+\s+(\S+)\s+accesslogs"), 0)

// -- Stage 2: Split positional fields from the WSA log ----------------------
| alter
    _parts = split(_wsa_log, " ")
| alter
    _elapsed_ms = arrayindex(_parts, 1),
    _client_ip = arrayindex(_parts, 2),
    _result_status = arrayindex(_parts, 3),
    _sc_bytes = arrayindex(_parts, 4),
    // Keep-in-both anchor: parser.xql stamps `_wsa_http_method` at
    // ingest from the same positional split. Parser-stamped rows
    // short-circuit through the column read; legacy / replayed /
    // backfilled rows fall through to the position-5 split.
    _http_method = coalesce(_wsa_http_method, arrayindex(_parts, 5)),
    _url = arrayindex(_parts, 6),
    _user_raw = arrayindex(_parts, 7),
    _hierarchy_raw = arrayindex(_parts, 8),
    _mime_type = arrayindex(_parts, 9)

// -- Stage 3: Decompose composite fields ------------------------------------
// Split result/status, hierarchy/peer, and clean the username.
// Extract ACL decision tag and URL hostname/port from the raw values.
| alter
    _cache_result = arrayindex(split(to_string(_result_status), "/"), 0),
    _http_status_str = arrayindex(split(to_string(_result_status), "/"), 1),
    _peer_host = arrayindex(split(to_string(_hierarchy_raw), "/"), 1),
    _user_username = if(
        _user_raw != "-" and _user_raw != null,
        arrayindex(regextract(to_string(_user_raw), "\\\\([^\"]+)"), 0),
        null),
    _user_domain = if(
        _user_raw != "-" and _user_raw != null,
        arrayindex(regextract(to_string(_user_raw), "\"?([^\\\\\"]+)\\\\"), 0),
        null),
    _url_host = coalesce(
        arrayindex(regextract(to_string(_url), "://([^:/]+)"), 0),
        arrayindex(regextract(to_string(_url), "^([^:/]+)"), 0)),
    _url_port_str = coalesce(
        arrayindex(regextract(to_string(_url), "://[^:/]+:(\d+)"), 0),
        arrayindex(regextract(to_string(_url), "^[^:/]+:(\d+)"), 0)),
    _acl_tag = arrayindex(regextract(_wsa_log, "ERR:\d+\s+(\S+)\s"), 0),
    _syslog_short = arrayindex(split(to_string(_syslog_fqdn), "."), 0)

// -- Stage 3.5: Anchor keep-in-both for the W3C ACL decision tag ------------
// Parser.xql stamps `_wsa_decision` (the first hyphen-component of the
// policy decision string) at ingest. The MODEL re-derives the same value
// by splitting `_acl_tag` on "-" and taking the first element so legacy /
// replayed / backfilled rows continue to behave identically. Defined in
// its own alter stage so `xdm.event.outcome` (Stage 4) can reference it
// without triggering ERR-024 (sibling-temp-in-same-alter).
| alter
    wsa_acl_decision = coalesce(_wsa_decision, arrayindex(split(to_string(_acl_tag), "-"), 0))

// -- Stage 4: Map to XDM fields ---------------------------------------------
| alter
    // Observer -- the WSA appliance that generated this log entry
    xdm.observer.vendor = "Cisco",
    xdm.observer.product = "Secure Web Appliance",
    xdm.observer.name = _syslog_fqdn,

    // Event -- network transaction metadata
    xdm.event.type = "NETWORK",
    xdm.event.description = concat(
        _http_method, " ", _url,
        " | ", _result_status,
        " | Client: ", _client_ip,
        if(_user_username != null, concat(" | User: ", _user_username), ""),
        if(_peer_host != null and _peer_host != "-", concat(" | Upstream: ", _peer_host), "")),
    xdm.event.duration = to_integer(to_number(_elapsed_ms)),
    xdm.event.outcome = if(
        _cache_result = "TCP_MISS" or _cache_result = "TCP_HIT" or _cache_result = "TCP_MEM_HIT" or _cache_result = "TCP_REFRESH_HIT" or _cache_result = "TCP_IMS_HIT" or _cache_result = "TCP_CLIENT_REFRESH_MISS", XDM_CONST.OUTCOME_SUCCESS,
        _cache_result = "TCP_DENIED", XDM_CONST.OUTCOME_FAILED,
        _cache_result = "NONE", XDM_CONST.OUTCOME_FAILED,
        // Defensive fallback via the W3C ACL decision anchor so blocked /
        // allowed / monitored / redirected requests still land in the right
        // outcome bucket when the cache-result code is an unfamiliar token.
        wsa_acl_decision ~= "^BLOCK_", XDM_CONST.OUTCOME_FAILED,
        wsa_acl_decision ~= "^ALLOW_", XDM_CONST.OUTCOME_SUCCESS,
        wsa_acl_decision ~= "^MONITOR", XDM_CONST.OUTCOME_SUCCESS,
        wsa_acl_decision = "REDIRECT", XDM_CONST.OUTCOME_SUCCESS,
        XDM_CONST.OUTCOME_UNKNOWN),
    xdm.event.outcome_reason = _result_status,

    // Source -- the client that made the request through the proxy
    xdm.source.ipv4 = _client_ip,
    xdm.source.user.username = _user_username,
    xdm.source.user.domain = _user_domain,

    // Target -- the upstream destination server
    xdm.target.host.hostname = if(_peer_host != "-" and _peer_host != null, _peer_host, null),
    xdm.target.url = _url,
    xdm.target.port = if(_url_port_str != null, to_integer(to_number(_url_port_str)), null),
    xdm.target.sent_bytes = to_integer(to_number(_sc_bytes)),

    // Network -- HTTP transaction details
    xdm.network.http.method = _http_method,
    xdm.network.http.response_code = _http_status_str,
    xdm.network.http.content_type = if(_mime_type != "-" and _mime_type != null, _mime_type, null),
    xdm.network.http.url = _url,
    xdm.network.http.domain = _url_host,
    xdm.network.rule = _acl_tag,

    // Intermediate -- the proxy appliance (same device as the observer)
    xdm.intermediate.host.hostname = _syslog_short,
    xdm.intermediate.host.fqdn = _syslog_fqdn;
