// Trend Micro Vision One -- Detections XDM Data Model Rule
// Dataset: trend_micro_vision_one_gc_raw
// Vendor: Trend Micro | Product: Vision One
//
// Maps Trend Micro Vision One detection events (the canonical
// `source = "workbenchAlert"` value, plus the legacy `"detections"`
// alias seen in earlier ingest) to the Cortex XDM schema. Endpoint
// malware detections from Server & Workload Protection, Apex One,
// and other connected products. The two source values are treated
// as synonyms; the filter accepts either.
//
// Documentation: trend_micro_vision_one_detections_xdm_model_rule_documentation.md
//
// SPDX-FileCopyrightText: GoCortexIO
// SPDX-License-Identifier: AGPL-3.0-or-later

[MODEL: dataset = trend_micro_vision_one_gc_raw]
filter
    source in ("workbenchAlert", "detections")

// -- Stage 1: Extract core detection fields from detail{} ------------------
| alter
    detection_uuid = uuid,
    detection_event_name = detail -> eventName,
    detection_severity = to_integer(detail -> severity),
    detection_mal_name = detail -> malName,
    detection_mal_type = detail -> malType,
    detection_rule_id = detail -> ruleIdStr,
    detection_product_name = coalesce(detail -> pname, detail -> mpname),
    detection_product_version = detail -> mpver,
    detection_pattern_version = detail -> patVer,
    detection_filter_risk_level = detail -> filterRiskLevel,
    detection_engine_operation = detail -> engineOperation

// -- Stage 1.5: Anchor keep-in-both (Task #111) ----------------------------
// `_source` and `_severity_band` are stamped at ingest by the shared
// parser at PRIVATE_DOCS/packs/trend_micro_vision_one_detections/parser.xql
// (which serves the trend_micro_vision_one_gc_raw target_dataset for
// both Vision One MODEL packs). Per anchor_field_design.md every
// anchor consumed here is re-derived defensively so legacy and
// replayed rows still model correctly. The pack's `_event_category`
// anchor is endpoint-activity-only and is not consumed here.
| alter
    _source = coalesce(_source, source),
    _severity_band = coalesce(_severity_band, if(
        detection_filter_risk_level = "critical", "CRITICAL",
        detection_filter_risk_level = "high", "HIGH",
        detection_filter_risk_level = "medium", "MEDIUM",
        detection_filter_risk_level = "low", "LOW"))

// -- Stage 2: Extract endpoint and network fields --------------------------
| alter
    endpoint_guid = detail -> endpointGUID,
    endpoint_hostname = coalesce(detail -> endpointHostName, detail -> interestedHost),
    endpoint_ip_array = detail -> endpointIp[],
    endpoint_mac = detail -> endpointMacAddress,
    endpoint_device_guid = detail -> mDeviceGUID,
    source_port = to_integer(detail -> spt),
    dest_port = to_integer(detail -> dpt),
    dest_host = detail -> dhost,
    network_app = detail -> app,
    network_app_group = detail -> appGroup,
    network_url = detail -> request,
    network_http_referer = detail -> httpReferer,
    network_user_agent = detail -> requestClientApplication

// -- Stage 3: Extract file/object fields -----------------------------------
| alter
    object_file_name = coalesce(detail -> objectFileName, detail -> objectName),
    object_file_path = detail -> objectFilePath,
    object_file_hash_sha256 = detail -> objectFileHashSha256,
    object_file_hash_md5 = detail -> objectFileHashMd5,
    object_file_size = to_integer(detail -> objectFileSize),
    file_path_name = detail -> filePathName,
    file_path = detail -> filePath

// -- Stage 4: Extract process fields from detail and processChainInfo ------
| alter
    process_image_path = coalesce(detail -> processImagePath, detail -> processFilePath),
    process_pid = to_integer(detail -> processPid),
    process_name = coalesce(detail -> processName, detail -> deviceProcessName),
    process_cmd = detail -> processCmd,
    process_hash_sha256 = detail -> processFileHashSha256,
    process_hash_md5 = detail -> processFileHashMd5,
    process_signer_str = detail -> processSigner,
    process_chain_raw = detail -> processChainInfo[]

// -- Stage 5: Parse processChainInfo[0] for initiator process details ------
| alter
    process_chain_first = arrayindex(process_chain_raw, 0)
| alter
    chain_process_name = if(process_chain_first != null, json_extract_scalar(to_string(process_chain_first), "$.process_name")),
    chain_process_cmd = if(process_chain_first != null, json_extract_scalar(to_string(process_chain_first), "$.process_cmd")),
    chain_process_path = if(process_chain_first != null, json_extract_scalar(to_string(process_chain_first), "$.process_file_path")),
    chain_process_sha256 = if(process_chain_first != null, json_extract_scalar(to_string(process_chain_first), "$.process_file_hash_sha256")),
    chain_process_md5 = if(process_chain_first != null, json_extract_scalar(to_string(process_chain_first), "$.process_file_hash_md5")),
    chain_process_user = if(process_chain_first != null, json_extract_scalar(to_string(process_chain_first), "$.process_user")),
    chain_process_user_domain = if(process_chain_first != null, json_extract_scalar(to_string(process_chain_first), "$.process_user_domain")),
    chain_process_signer = if(process_chain_first != null, json_extract_scalar(to_string(process_chain_first), "$.process_signer")),
    chain_process_pid = if(process_chain_first != null, to_integer(json_extract_scalar(to_string(process_chain_first), "$.process_pid"))),
    chain_process_file_size = if(process_chain_first != null, to_integer(json_extract_scalar(to_string(process_chain_first), "$.process_file_size"))),
    chain_integrity_level = if(process_chain_first != null, to_integer(json_extract_scalar(to_string(process_chain_first), "$.integrity_level")))

// -- Stage 6: Extract MITRE ATT&CK metadata from filters[] ----------------
| alter
    detection_filters = filters -> []
| alter
    filter_names = arraystring(arraymap(detection_filters, json_extract_scalar("@element", "$.name")), ", "),
    filter_descriptions = arraystring(arraymap(detection_filters, json_extract_scalar("@element", "$.description")), ", "),
    mitre_tactic_ids = arraydistinct(arraymap(detection_filters, json_extract_scalar("@element", "$.mitreTacticIds")))

// -- Stage 7: Build composite action result string -------------------------
| alter
    action_summary = if(
        detail -> secondAct != null and detail -> secondAct != "",
        concat(coalesce(detail -> firstAct, ""), " -> ", coalesce(detail -> secondAct, ""), " (", coalesce(detail -> secondActResult, ""), ")"),
        coalesce(detail -> firstActResult, arraystring(detail -> actResult[], ", ")))

// -- Stage 8: Resolve effective process fields (prefer detail over chain[0])
| alter
    effective_process_name = coalesce(process_name, chain_process_name),
    effective_process_cmd = coalesce(process_cmd, chain_process_cmd),
    effective_process_path = coalesce(process_image_path, chain_process_path),
    effective_process_sha256 = coalesce(process_hash_sha256, chain_process_sha256),
    effective_process_md5 = coalesce(process_hash_md5, chain_process_md5),
    effective_process_pid = coalesce(process_pid, chain_process_pid),
    effective_process_signer = coalesce(process_signer_str, chain_process_signer),
    effective_process_user = if(chain_process_user != null and chain_process_user != "", chain_process_user),
    effective_process_user_domain = if(chain_process_user_domain != null and chain_process_user_domain != "", chain_process_user_domain),
    effective_process_file_size = chain_process_file_size,
    effective_integrity_level = chain_integrity_level

// -- Stage 9: Resolve effective IP addresses --------------------------------
| alter
    effective_source_ipv4 = arrayindex(regextract(coalesce(
        arraystring(endpoint_ip_array, ","),
        arraystring(detail -> interestedIp[], ","),
        arraystring(detail -> src[], ",")), "\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}"), 0),
    effective_target_ipv4 = arrayindex(regextract(
        arraystring(detail -> dst[], ","), "\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}"), 0)

// -- Stage 10: Map XDM fields ----------------------------------------------
| alter
    // XDM Observer fields -- xdm.observer.*
    xdm.observer.vendor = "Trend Micro",
    xdm.observer.product = "Vision One",
    xdm.observer.type = detection_product_name,
    xdm.observer.version = detection_product_version,
    xdm.observer.content_version = detection_pattern_version,
    xdm.observer.unique_identifier = endpoint_device_guid,
    xdm.observer.action = action_summary,

    // XDM Event fields -- xdm.event.*
    xdm.event.id = detection_uuid,
    xdm.event.type = "ALERT",
    xdm.event.original_event_type = _source,
    xdm.event.description = detection_event_name,
    xdm.event.operation_sub_type = detection_engine_operation,
    xdm.event.log_level = if(
        detection_severity = 1, XDM_CONST.LOG_LEVEL_INFORMATIONAL,
        detection_severity = 2, XDM_CONST.LOG_LEVEL_NOTICE,
        detection_severity = 3, XDM_CONST.LOG_LEVEL_WARNING,
        detection_severity = 4, XDM_CONST.LOG_LEVEL_ERROR,
        detection_severity >= 5, XDM_CONST.LOG_LEVEL_CRITICAL,
        XDM_CONST.LOG_LEVEL_INFORMATIONAL),
    xdm.event.outcome = if(
        action_summary contains "denied" or action_summary contains "Block" or action_summary contains "Quarantine" or action_summary contains "Delete" or action_summary contains "Clean", XDM_CONST.OUTCOME_SUCCESS,
        action_summary contains "Pass" or action_summary contains "passed", XDM_CONST.OUTCOME_PARTIAL,
        XDM_CONST.OUTCOME_UNKNOWN),
    xdm.event.outcome_reason = action_summary,

    // XDM Alert fields -- xdm.alert.*
    xdm.alert.original_alert_id = detection_uuid,
    xdm.alert.name = filter_names,
    xdm.alert.description = filter_descriptions,
    xdm.alert.severity = coalesce(
        if(_severity_band = "CRITICAL", "Critical",
           _severity_band = "HIGH", "High",
           _severity_band = "MEDIUM", "Medium",
           _severity_band = "LOW", "Low"),
        if(detection_filter_risk_level = "info", "Informational",
           detection_filter_risk_level != null, detection_filter_risk_level)),
    xdm.alert.category = detection_event_name,
    xdm.alert.subcategory = detection_mal_type,
    xdm.alert.original_threat_name = detection_mal_name,
    xdm.alert.original_threat_id = detection_rule_id,
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

    // XDM Source fields -- xdm.source.* (process/user that triggered detection)
    xdm.source.ipv4 = effective_source_ipv4,
    xdm.source.port = source_port,
    xdm.source.user.username = effective_process_user,
    xdm.source.user.domain = effective_process_user_domain,
    xdm.source.user.identifier = detail -> senderGUID,
    xdm.source.user_agent = network_user_agent,
    xdm.source.host.hostname = endpoint_hostname,
    xdm.source.host.device_id = endpoint_guid,
    xdm.source.host.ipv4_addresses = endpoint_ip_array,
    xdm.source.host.mac_addresses = if(endpoint_mac != null, arraycreate(endpoint_mac)),
    xdm.source.process.name = effective_process_name,
    xdm.source.process.pid = effective_process_pid,
    xdm.source.process.command_line = effective_process_cmd,
    xdm.source.process.executable.path = effective_process_path,
    xdm.source.process.executable.sha256 = effective_process_sha256,
    xdm.source.process.executable.md5 = effective_process_md5,
    xdm.source.process.executable.signer = effective_process_signer,
    xdm.source.process.executable.size = effective_process_file_size,
    xdm.source.process.integrity_level = effective_integrity_level,

    // XDM Target fields -- xdm.target.* (the detected file/object)
    xdm.target.ipv4 = effective_target_ipv4,
    xdm.target.port = dest_port,
    xdm.target.host.hostname = dest_host,
    xdm.target.file.filename = object_file_name,
    xdm.target.file.path = coalesce(object_file_path, file_path_name),
    xdm.target.file.directory = file_path,
    xdm.target.file.sha256 = object_file_hash_sha256,
    xdm.target.file.md5 = object_file_hash_md5,
    xdm.target.file.size = object_file_size,

    // XDM Network fields -- xdm.network.*
    xdm.network.application_protocol = network_app,
    xdm.network.application_protocol_category = network_app_group,
    xdm.network.http.url = network_url,
    xdm.network.http.referrer = network_http_referer,
    xdm.session_context_id = detection_uuid;
