// Trend Micro Vision One -- Endpoint Activity XDM Data Model Rule
// Dataset: trend_micro_vision_one_gc_raw
// Vendor: Trend Micro | Product: Vision One
//
// Maps Trend Micro Vision One endpoint activity events
// (source = "endpointActivityData") to the Cortex XDM schema. Covers
// process, file, network, DNS, registry, and account events from XES.
//
// Documentation: trend_micro_vision_one_endpoint_activity_xdm_model_rule_documentation.md
//
// SPDX-FileCopyrightText: GoCortexIO
// SPDX-License-Identifier: AGPL-3.0-or-later

[MODEL: dataset = trend_micro_vision_one_gc_raw]
filter
    source = "endpointActivityData"

// -- Stage 1: Extract core event identity fields from detail{} ----------------
| alter
    detection_uuid = uuid,
    event_id = to_integer(detail -> eventId),
    filter_risk_level = detail -> filterRiskLevel,
    product_name = detail -> pname,
    product_version = detail -> pver,
    product_code = detail -> productCode

// -- Stage 1.5: Anchor keep-in-both (Task #111) ------------------------------
// `_source` and `_event_category` are stamped at ingest by the
// shared parser at
// PRIVATE_DOCS/packs/trend_micro_vision_one_detections/parser.xql
// (which serves the trend_micro_vision_one_gc_raw target_dataset
// for both Vision One MODEL packs). Per anchor_field_design.md
// every anchor consumed here is re-derived defensively so legacy
// and replayed rows still model correctly. The parser also stamps
// `_severity_band`; this MODEL deliberately does NOT consume it
// (per Task #111 scope) -- endpoint-activity severity continues to
// flow from `detail.filterRiskLevel` directly. Only the detections
// MODEL consumes `_severity_band`.
| alter
    _source = coalesce(_source, source),
    _event_category = coalesce(_event_category, if(
        event_id = 1, "process",
        event_id = 2, "file",
        event_id = 3, "network",
        event_id = 4, "dns",
        event_id = 5, "registry",
        event_id = 6, "account"))

// -- Stage 2: Extract endpoint host identity fields ---------------------------
| alter
    endpoint_guid = detail -> endpointGuid,
    endpoint_hostname = coalesce(detail -> endpointHostName, detail -> hostName),
    endpoint_ip_raw = detail -> endpointIp[],
    endpoint_mac_raw = detail -> endpointMacAddress[],
    os_name = detail -> osName,
    os_description = detail -> osDescription

// -- Stage 3: Extract object (target) process fields --------------------------
| alter
    object_name = detail -> objectName,
    object_cmd = detail -> objectCmd,
    object_pid = to_integer(detail -> objectPid),
    object_user = detail -> objectUser,
    object_file_path = detail -> objectFilePath,
    object_hash_sha256 = detail -> objectFileHashSha256,
    object_hash_md5 = detail -> objectFileHashMd5,
    object_ip = detail -> objectIp,
    object_port = to_integer(detail -> objectPort),
    object_hostname = detail -> objectHostName

// -- Stage 4: Extract source (launching) process fields -----------------------
| alter
    process_name = detail -> processName,
    process_cmd = detail -> processCmd,
    process_pid = to_integer(detail -> processPid),
    process_user = detail -> processUser,
    process_file_path = detail -> processFilePath,
    process_hash_sha256 = detail -> processFileHashSha256,
    process_hash_md5 = detail -> processFileHashMd5

// -- Stage 5: Extract user and domain metadata --------------------------------
| alter
    logon_user_raw = detail -> logonUser[],
    user_domain_raw = detail -> userDomain[]
| alter
    logon_user = arrayindex(logon_user_raw, 0),
    user_domain = arrayindex(user_domain_raw, 0)

// -- Stage 7: Extract MITRE ATT&CK and filter metadata from filters[] --------
| alter
    detection_filters = filters -> []
| alter
    filter_names = if(detection_filters != null, arraystring(arraymap(detection_filters, json_extract_scalar("@element", "$.name")), ", ")),
    filter_descriptions = if(detection_filters != null, arraystring(arraymap(detection_filters, json_extract_scalar("@element", "$.description")), ", ")),
    mitre_tactic_ids = if(detection_filters != null, arraydistinct(arraymap(detection_filters, json_extract_scalar("@element", "$.mitreTacticIds")))),
    first_filter_name = if(detection_filters != null, json_extract_scalar(to_string(arrayindex(detection_filters, 0)), "$.name"))

// -- Stage 8: Build human-readable event operation type (eventId/eventSubId)
| alter
    _event_sub_id = to_integer(detail -> eventSubId)
| alter
    event_category = if(
        event_id = 1, "PROCESS",
        event_id = 2, "FILE",
        event_id = 3, "CONNECTION",
        event_id = 4, "DNS",
        event_id = 5, "REGISTRY",
        event_id = 6, "ACCOUNT",
        event_id = 7, "INTERNET",
        event_id = 8, "MODIFIED_PROCESS",
        event_id = 9, "WINDOWS_HOOK",
        event_id = 10, "WINDOWS_EVENT",
        event_id = 11, "AMSI",
        event_id = 12, "WMI",
        event_id = 13, "MEMORY",
        event_id = 14, "BM",
        to_string(event_id)),
    event_action = if(
        _event_sub_id = 0, "NONE",
        _event_sub_id = 1, "PROCESS_OPEN",
        _event_sub_id = 2, "PROCESS_CREATE",
        _event_sub_id = 3, "PROCESS_TERMINATE",
        _event_sub_id = 4, "PROCESS_LOAD_IMAGE",
        _event_sub_id = 5, "PROCESS_EXECUTE",
        _event_sub_id = 6, "PROCESS_CONNECT",
        _event_sub_id = 7, "PROCESS_TRACME",
        _event_sub_id = 101, "FILE_CREATE",
        _event_sub_id = 102, "FILE_OPEN",
        _event_sub_id = 103, "FILE_DELETE",
        _event_sub_id = 104, "FILE_SET_SECURITY",
        _event_sub_id = 105, "FILE_COPY",
        _event_sub_id = 106, "FILE_MOVE",
        _event_sub_id = 107, "FILE_CLOSE",
        _event_sub_id = 108, "FILE_MODIFY_TIMESTAMP",
        _event_sub_id = 109, "FILE_MODIFY",
        _event_sub_id = 201, "CONNECTION_CONNECT",
        _event_sub_id = 202, "CONNECTION_LISTEN",
        _event_sub_id = 203, "CONNECTION_INBOUND",
        _event_sub_id = 204, "CONNECTION_OUTBOUND",
        _event_sub_id = 301, "DNS_QUERY",
        _event_sub_id = 401, "REGISTRY_CREATE",
        _event_sub_id = 402, "REGISTRY_SET",
        _event_sub_id = 403, "REGISTRY_DELETE",
        _event_sub_id = 404, "REGISTRY_RENAME",
        _event_sub_id = 501, "ACCOUNT_ADD",
        _event_sub_id = 502, "ACCOUNT_DELETE",
        _event_sub_id = 503, "ACCOUNT_IMPERSONATE",
        _event_sub_id = 504, "ACCOUNT_MODIFY",
        _event_sub_id = 601, "INTERNET_OPEN",
        _event_sub_id = 602, "INTERNET_CONNECT",
        _event_sub_id = 603, "INTERNET_DOWNLOAD",
        _event_sub_id = 701, "REMOTETHREAD_CREATE",
        _event_sub_id = 702, "WRITE_MEMORY",
        _event_sub_id = 703, "WRITE_PROCESS",
        _event_sub_id = 704, "READ_PROCESS",
        _event_sub_id = 705, "WRITE_PROCESS_NAME",
        _event_sub_id = 801, "WINDOWS_HOOK_SET",
        _event_sub_id = 901, "AMSI_EXECUTE",
        _event_sub_id = 1001, "MEMORY_MODIFY",
        _event_sub_id = 1002, "MEMORY_MODIFY_PERMISSION",
        _event_sub_id = 1003, "MEMORY_READ",
        _event_sub_id = 1101, "BM_INVOKE",
        _event_sub_id = 1102, "BM_INVOKE_API",
        to_string(_event_sub_id))
| alter
    operation_type = concat(event_category, " / ", event_action)

// -- Stage 9: Extract XSAE tags for alert subcategory ------------------------
| alter
    detail_tags = detail -> tags[]
| alter
    xsae_tags = if(detail_tags != null, arraystring(arrayfilter(detail_tags, "@element" contains "XSAE"), ", "))

// -- Stage 10: Separate IPv4 and IPv6 from endpoint IP array ------------------
| alter
    endpoint_ipv4_array = if(endpoint_ip_raw != null, arrayfilter(endpoint_ip_raw, "@element" ~= "^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$")),
    endpoint_ipv6_array = if(endpoint_ip_raw != null, arrayfilter(endpoint_ip_raw, "@element" contains ":"))
| alter
    source_ipv4 = arrayindex(endpoint_ipv4_array, 0),
    source_port = to_integer(detail -> spt),
    dest_ipv4_raw = detail -> dst,
    dest_port = to_integer(detail -> dpt),
    request_url = detail -> request

// -- Stage 11: Map XDM fields -------------------------------------------------
| alter
    // XDM Observer fields -- xdm.observer.*
    xdm.observer.vendor = "Trend Micro",
    xdm.observer.product = "Vision One",
    xdm.observer.type = product_name,
    xdm.observer.version = product_version,
    xdm.observer.action = filter_risk_level,

    // XDM Event fields -- xdm.event.*
    xdm.event.id = detection_uuid,
    xdm.event.type = "ENDPOINT_ACTIVITY",
    xdm.event.original_event_type = _source,
    xdm.event.description = first_filter_name,
    xdm.event.operation_sub_type = operation_type,
    xdm.event.log_level = if(
        filter_risk_level = "info", XDM_CONST.LOG_LEVEL_INFORMATIONAL,
        filter_risk_level = "low", XDM_CONST.LOG_LEVEL_NOTICE,
        filter_risk_level = "medium", XDM_CONST.LOG_LEVEL_WARNING,
        filter_risk_level = "high", XDM_CONST.LOG_LEVEL_ERROR,
        filter_risk_level = "critical", XDM_CONST.LOG_LEVEL_CRITICAL,
        XDM_CONST.LOG_LEVEL_INFORMATIONAL),

    // XDM Alert fields -- xdm.alert.*
    xdm.alert.original_alert_id = detection_uuid,
    xdm.alert.name = filter_names,
    xdm.alert.description = filter_descriptions,
    xdm.alert.severity = if(
        filter_risk_level = "critical", "Critical",
        filter_risk_level = "high", "High",
        filter_risk_level = "medium", "Medium",
        filter_risk_level = "low", "Low",
        filter_risk_level = "info", "Informational",
        filter_risk_level != null, filter_risk_level),
    xdm.alert.subcategory = coalesce(xsae_tags, _event_category),
    xdm.alert.mitre_tactics = arraymap(mitre_tactic_ids,
        if("@element" ~= "TA0009", XDM_CONST.MITRE_TACTIC_COLLECTION,
        "@element" ~= "TA0011", XDM_CONST.MITRE_TACTIC_COMMAND_AND_CONTROL,
        "@element" ~= "TA0006", XDM_CONST.MITRE_TACTIC_CREDENTIAL_ACCESS,
        "@element" ~= "TA0005", XDM_CONST.MITRE_TACTIC_DEFENSE_EVASION,
        "@element" ~= "TA0007", XDM_CONST.MITRE_TACTIC_DISCOVERY,
        "@element" ~= "TA0002", XDM_CONST.MITRE_TACTIC_EXECUTION,
        "@element" ~= "TA0010", XDM_CONST.MITRE_TACTIC_EXFILTRATION,
        "@element" ~= "TA0040", XDM_CONST.MITRE_TACTIC_IMPACT,
        "@element" ~= "TA0001", XDM_CONST.MITRE_TACTIC_INITIAL_ACCESS,
        "@element" ~= "TA0008", XDM_CONST.MITRE_TACTIC_LATERAL_MOVEMENT,
        "@element" ~= "TA0003", XDM_CONST.MITRE_TACTIC_PERSISTENCE,
        "@element" ~= "TA0004", XDM_CONST.MITRE_TACTIC_PRIVILEGE_ESCALATION,
        "@element" ~= "TA0043", XDM_CONST.MITRE_TACTIC_RECONNAISSANCE,
        "@element" ~= "TA0042", XDM_CONST.MITRE_TACTIC_RESOURCE_DEVELOPMENT,
        "@element")),

    // XDM Source fields -- xdm.source.* (launching process and endpoint host)
    xdm.source.ipv4 = source_ipv4,
    xdm.source.port = source_port,
    xdm.source.application.name = product_code,
    xdm.source.user.username = coalesce(process_user, logon_user),
    xdm.source.user.domain = if(user_domain != null and user_domain != "", user_domain),
    xdm.source.user.user_type = if(logon_user != null and logon_user = "root", "root", logon_user != null, "standard"),
    xdm.source.host.hostname = endpoint_hostname,
    xdm.source.host.device_id = endpoint_guid,
    xdm.source.host.ipv4_addresses = if(endpoint_ipv4_array != null and array_length(endpoint_ipv4_array) > 0, endpoint_ipv4_array),
    xdm.source.host.ipv6_addresses = if(endpoint_ipv6_array != null and array_length(endpoint_ipv6_array) > 0, endpoint_ipv6_array),
    xdm.source.host.mac_addresses = if(endpoint_mac_raw != null and array_length(endpoint_mac_raw) > 0, endpoint_mac_raw),
    xdm.source.host.os = os_description,
    xdm.source.host.os_family = if(
        os_name = "Linux", XDM_CONST.OS_FAMILY_LINUX,
        os_name = "Windows", XDM_CONST.OS_FAMILY_WINDOWS,
        os_name = "macOS" or os_name = "Mac", XDM_CONST.OS_FAMILY_MACOS),
    xdm.source.process.name = process_name,
    xdm.source.process.pid = process_pid,
    xdm.source.process.command_line = process_cmd,
    xdm.source.process.executable.path = process_file_path,
    xdm.source.process.executable.sha256 = process_hash_sha256,
    xdm.source.process.executable.md5 = process_hash_md5,

    // XDM Target fields -- xdm.target.* (the object: child process/file/resource)
    xdm.target.ipv4 = coalesce(dest_ipv4_raw, object_ip),
    xdm.target.port = coalesce(dest_port, object_port),
    xdm.target.host.hostname = object_hostname,
    xdm.target.process.name = object_name,
    xdm.target.process.pid = object_pid,
    xdm.target.process.command_line = object_cmd,
    xdm.target.process.executable.path = object_file_path,
    xdm.target.process.executable.sha256 = object_hash_sha256,
    xdm.target.process.executable.md5 = object_hash_md5,
    xdm.target.user.username = object_user,

    // XDM Network fields -- xdm.network.*
    xdm.network.http.url = request_url,
    xdm.network.dns.dns_question.name = if(event_id = 4, object_name);
