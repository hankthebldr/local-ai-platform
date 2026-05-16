// Somansa WebKeeper -- XDM Data Model Rule
// Dataset: somansa_webkeeper_raw
// Vendor: Somansa | Product: WebKeeper
//
// Maps Somansa WebKeeper (Korean forward web proxy / URL filter)
// syslog records to the Cortex XDM schema. Three structural shapes
// are routed (PROXY-A, PROXY-B, SYSTEM); the WebKeeper sensor wraps
// each record in a syslog prefix from the pssv_sensor process.
//
// Documentation: somansa_webkeeper_xdm_model_rule_documentation.md
//
// SPDX-FileCopyrightText: GoCortexIO
// SPDX-License-Identifier: AGPL-3.0-or-later

[MODEL: dataset = somansa_webkeeper_raw]

// -- Stage 1: Strip syslog wrapper and extract the WebKeeper payload -------
alter
    _payload = arrayindex(regextract(_raw_log, "pssv_sensor\[\d+\]:\s+(.+)$"), 0),
    _syslog_host = arrayindex(regextract(_raw_log, ">\w+\s+\d+\s+[\d:]+\s+(\S+)\s+pssv_sensor"), 0)

// -- Stage 2: Discriminate the structural shape -----------------------------
// Priority: SYSTEM marker, then PROXY_B URL marker, then PROXY_A default.
// Scheme alternation accepts https?, ftps?, wss?, gopher case-insensitively.
//
// Keep-in-both anchor: `parser.xql` stamps `_payload_shape` at ingest
// from byte-for-byte the same shape regex below. Parser-stamped rows
// short-circuit through the column read; legacy / replayed /
// backfilled rows fall through to the same derivation. Vocabulary is
// 3 closed values (PROXY_A, PROXY_B, SYSTEM) -- the textbook anchor
// per `PRIVATE_DOCS/anchor_field_design.md`. _payload_shape feeds
// every per-shape gate downstream, so it is amply XDM-reachable.
| alter
    _payload_shape = coalesce(
        _payload_shape,
        if(
            _payload ~= "@#Loading-Success", "SYSTEM",
            _payload ~= ",(?i)(?:https?|ftps?|wss?|gopher):[/][/]", "PROXY_B",
            "PROXY_A"))

// -- Stage 3: Split the payload into its CSV positions ----------------------
| alter
    _csv_parts = split(to_string(_payload), ",")

// -- Stage 4: Extract per-position raw fields and the SYSTEM token ---------
// Keep-in-both anchor: `parser.xql` stamps `_proxy_action` at ingest
// (verbatim CSV position 1, NULL on SYSTEM rows by convention).
// Parser-stamped rows short-circuit through the column read; legacy
// rows fall through to the same `if(... != "SYSTEM", arrayindex(...),
// null)` derivation so SYSTEM rows stay null in either path -- there
// is no spurious non-null `_proxy_action` on a system row even when
// the parser column is absent. Vocabulary: ~5 closed values (Allow,
// Block, Warn, Bypass, Quarantine).
| alter
    _proxy_action = coalesce(
        _proxy_action,
        if(_payload_shape != "SYSTEM", arrayindex(_csv_parts, 1), null)),
    _policy = arrayindex(_csv_parts, 2),
    _user_id_raw = arrayindex(_csv_parts, 3),
    _src_ip_raw = arrayindex(_csv_parts, 4),
    _dst_ip_raw = arrayindex(_csv_parts, 5),
    _proxy_b_domain = arrayindex(_csv_parts, 6),
    _proxy_b_url = arrayindex(_csv_parts, 7)

// -- Stage 5: Decompose the URL host and normalise raw fields --------------
// _url_host: PROXY-B URL host, tolerates bracketed IPv6 and user:pass@.
// _action_upper: upper-cased verb for the verb map. _user_id: "-"/empty -> null.
| alter
    _url_host = if(
        _payload_shape = "PROXY_B" and _proxy_b_url != null,
        arrayindex(regextract(to_string(_proxy_b_url), ":[/][/](?:[^@/]+@)?(\[[^\]]+\]|[^:/]+)"), 0),
        null),
    _action_upper = if(_proxy_action != null, uppercase(to_string(_proxy_action)), null),
    _user_id = if(_user_id_raw = "-" or _user_id_raw = "" or _user_id_raw = null, null, _user_id_raw)

// -- Stage 6: Strip brackets from a captured IPv6 URL host -----------------
| alter
    _url_host_clean = if(
        _url_host != null and _url_host ~= "^\[.*\]$",
        replex(replex(to_string(_url_host), "^\[", ""), "\]$", ""),
        _url_host)

// -- Stage 7: Map to XDM fields --------------------------------------------
// All shape-specific assignments are gated on _payload_shape; SYSTEM rows leave
// every source / target / network field null.
| alter
    // Observer -- the WebKeeper sensor (same identity for all shapes)
    xdm.observer.vendor = "Somansa",
    xdm.observer.product = "WebKeeper",
    xdm.observer.name = _syslog_host,

    // Event -- type, outcome, log level, and the human-readable summary
    xdm.event.type = if(
        _payload_shape = "SYSTEM", "STATUS",
        "NETWORK"),
    xdm.event.outcome = if(
        _payload_shape = "SYSTEM", XDM_CONST.OUTCOME_SUCCESS,
        _action_upper = "ACCEPT" or _action_upper = "PERMIT" or _action_upper = "ALLOW", XDM_CONST.OUTCOME_SUCCESS,
        _action_upper = "REJECT" or _action_upper = "BLOCK" or _action_upper = "DENY" or _action_upper = "DROP", XDM_CONST.OUTCOME_FAILED,
        _action_upper = "MONITOR" or _action_upper = "LOG" or _action_upper = "OBSERVE", XDM_CONST.OUTCOME_PARTIAL,
        _action_upper = "WARN" or _action_upper = "COACH" or _action_upper = "OVERRIDE" or _action_upper = "BYPASS" or _action_upper = "REDIRECT", XDM_CONST.OUTCOME_PARTIAL,
        XDM_CONST.OUTCOME_UNKNOWN),
    xdm.event.outcome_reason = if(
        _payload_shape = "SYSTEM", "Loading-Success",
        _proxy_action),
    xdm.event.log_level = if(
        _payload_shape = "SYSTEM", XDM_CONST.LOG_LEVEL_INFORMATIONAL,
        _action_upper = "ACCEPT" or _action_upper = "PERMIT" or _action_upper = "ALLOW", XDM_CONST.LOG_LEVEL_INFORMATIONAL,
        _action_upper = "REJECT" or _action_upper = "BLOCK" or _action_upper = "DENY" or _action_upper = "DROP", XDM_CONST.LOG_LEVEL_WARNING,
        _action_upper = "MONITOR" or _action_upper = "LOG" or _action_upper = "OBSERVE", XDM_CONST.LOG_LEVEL_NOTICE,
        _action_upper = "WARN" or _action_upper = "COACH" or _action_upper = "OVERRIDE" or _action_upper = "BYPASS" or _action_upper = "REDIRECT", XDM_CONST.LOG_LEVEL_NOTICE,
        XDM_CONST.LOG_LEVEL_INFORMATIONAL),
    xdm.event.description = if(
        _payload_shape = "SYSTEM",
            concat(
                "Loading-Success: ",
                coalesce(arrayindex(regextract(to_string(_payload), "@#Loading-Success\(([^)]+)\)"), 0), "unknown")),
        _payload_shape = "PROXY_B",
            concat(
                to_string(_proxy_action),
                " ", coalesce(to_string(_src_ip_raw), "-"),
                " -> ", coalesce(to_string(_dst_ip_raw), "-"),
                if(_proxy_b_domain != null, concat(" (", to_string(_proxy_b_domain), ")"), ""),
                if(_user_id != null, concat(" | User: ", to_string(_user_id)), ""),
                if(_policy != null, concat(" | Policy: ", to_string(_policy)), ""),
                if(arrayindex(_csv_parts, 8) != null and arrayindex(_csv_parts, 8) != "-" and arrayindex(_csv_parts, 8) != "",
                    concat(" | Category: ", to_string(arrayindex(_csv_parts, 8))), "")),
        // PROXY_A
        concat(
            to_string(_proxy_action),
            " ", coalesce(to_string(_src_ip_raw), "-"),
            " -> ", coalesce(to_string(_dst_ip_raw), "-"),
            if(_user_id != null, concat(" | User: ", to_string(_user_id)), ""),
            if(_policy != null, concat(" | Policy: ", to_string(_policy)), ""),
            if(arrayindex(_csv_parts, 6) != null and arrayindex(_csv_parts, 6) != "-" and arrayindex(_csv_parts, 6) != "",
                concat(" | Category: ", to_string(arrayindex(_csv_parts, 6))), ""),
            if(arrayindex(_csv_parts, 7) != null and arrayindex(_csv_parts, 7) != "-" and arrayindex(_csv_parts, 7) != "",
                concat(" | Sub: ", to_string(arrayindex(_csv_parts, 7))), ""))),

    // Source -- the client behind the proxy (PROXY shapes only)
    xdm.source.ipv4 = if(
        _payload_shape != "SYSTEM" and _src_ip_raw ~= "^\d{1,3}(?:\.\d{1,3}){3}$",
        to_string(_src_ip_raw),
        null),
    xdm.source.ipv6 = if(
        _payload_shape != "SYSTEM" and _src_ip_raw != null and not (_src_ip_raw ~= "^\d{1,3}(?:\.\d{1,3}){3}$") and _src_ip_raw ~= "^[0-9A-Fa-f:]+(?:%[A-Za-z0-9]+)?$",
        to_string(_src_ip_raw),
        null),
    xdm.source.user.username = if(_payload_shape != "SYSTEM", _user_id, null),

    // Target -- the upstream destination (PROXY shapes only)
    xdm.target.ipv4 = if(
        _payload_shape != "SYSTEM" and _dst_ip_raw ~= "^\d{1,3}(?:\.\d{1,3}){3}$",
        to_string(_dst_ip_raw),
        null),
    xdm.target.ipv6 = if(
        _payload_shape != "SYSTEM" and _dst_ip_raw != null and not (_dst_ip_raw ~= "^\d{1,3}(?:\.\d{1,3}){3}$") and _dst_ip_raw ~= "^[0-9A-Fa-f:]+(?:%[A-Za-z0-9]+)?$",
        to_string(_dst_ip_raw),
        null),
    xdm.target.host.hostname = if(_payload_shape = "PROXY_B", _proxy_b_domain, null),
    xdm.target.url = if(_payload_shape = "PROXY_B", _proxy_b_url, null),

    // Network -- HTTP-specific mirrors plus the policy rule (PROXY shapes)
    xdm.network.http.url = if(_payload_shape = "PROXY_B", _proxy_b_url, null),
    xdm.network.http.domain = if(_payload_shape = "PROXY_B", _url_host_clean, null),
    xdm.network.rule = if(_payload_shape != "SYSTEM", _policy, null);
