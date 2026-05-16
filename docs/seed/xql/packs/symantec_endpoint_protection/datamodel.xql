// Symantec Endpoint Protection -- XDM Data Model Rule
// Dataset: symantec_ep_raw
// Vendor: Symantec | Product: Endpoint Protection
//
// Maps Symantec Endpoint Protection (SEP) Manager-forwarded syslog events
// to the Cortex XDM schema. Five sub-types are routed in a single
// pipeline (RISK, IPS, BEHAVIOR, TRAFFIC, SYSTEM) using strict-order
// string discriminators on the comma-delimited payload.
//
// Documentation: symantec_endpoint_protection_xdm_model_rule_documentation.md
//
// SPDX-FileCopyrightText: GoCortexIO
// SPDX-License-Identifier: AGPL-3.0-or-later

[MODEL: dataset = symantec_ep_raw]

// -- Stage 1: Sub-type discriminator -------------------------------------
// Order matters: BEHAVIOR before TRAFFIC (both contain `Rule:`).
alter
    _subtype = if(
        _raw_log ~= "SymantecServer:\s+(?:Potential risk found|Virus found),",   "RISK",
        _raw_log ~= ",Intrusion URL:",                                           "IPS",
        _raw_log ~= ",Action Type:",                                             "BEHAVIOR",
        _raw_log ~= ",Rule:\s",                                                  "TRAFFIC",
        _raw_log ~= "SymantecServer:\s+Site:\s",                                 "SYSTEM",
        "UNKNOWN"),
    _risk_kind = if(
        _raw_log ~= "SymantecServer:\s+Potential risk found,",   "POTENTIAL",
        _raw_log ~= "SymantecServer:\s+Virus found,",            "VIRUS")

// -- Stage 2: Extract raw fields from _raw_log ---------------------------
// All extractions in parallel; no target references another sibling.
| alter
    // Cross-sub-type envelope fields ------------------------------------
    _syslog_host = arrayindex(regextract(_raw_log, ">\w+\s+\d+\s+[\d:]+\s+(\S+)\s+SymantecServer"), 0),
    _server_name = arrayindex(regextract(_raw_log, "Server Name:\s+([^,]+)"), 0),
    _user_name_kv = arrayindex(regextract(_raw_log, "User Name:\s+([^,]+)"), 0),
    // Tolerant Domain Name capture. The well-formed shape is
    _user_domain_kv = coalesce(
        arrayindex(regextract(_raw_log, "Domain Name:\s+([^,\s][^,]*?),"), 0),
        arrayindex(regextract(_raw_log, "Domain Name:\s*([^,\s][^,]*?)\s*Group Name:"), 0)),

    // RISK sub-type extractions -----------------------------------------
    _risk_computer = arrayindex(regextract(_raw_log, "Computer name:\s+([^,]+)"), 0),
    _risk_ip = arrayindex(regextract(_raw_log, "IP Address:\s+([^,]+)"), 0),
    _risk_detection_type = arrayindex(regextract(_raw_log, "Detection type:\s+([^,]+)"), 0),
    _risk_app_name = arrayindex(regextract(_raw_log, "Application name:\s+([^,]+)"), 0),
    _risk_app_type = arrayindex(regextract(_raw_log, "Application type:\s+([^,]+)"), 0),
    // Numeric Application type code (Virus-found shape): captured into
    _risk_app_type_code = arrayindex(regextract(_raw_log, "Application type:\s+(\d+)\s*,"), 0),
    _risk_app_hash = arrayindex(regextract(_raw_log, "Application hash:\s+([^,]+)"), 0),
    _risk_file_size = arrayindex(regextract(_raw_log, "File size \(bytes\):\s+(\d+)"), 0),
    _risk_sensitivity = arrayindex(regextract(_raw_log, "Sensitivity:\s+([^,]+)"), 0),
    _risk_name = arrayindex(regextract(_raw_log, "Risk name:\s+([^,]+)"), 0),
    _risk_category = arrayindex(regextract(_raw_log, "Category type:\s+([^,]+)"), 0),
    // Virus-found "Category set" (e.g. "Malware") -- coarser than
    // Category type and used by the categoriser as a higher-priority
    // textual signal than the numeric Application type code map.
    _risk_category_set = arrayindex(regextract(_raw_log, "Category set:\s+([^,]+)"), 0),
    _risk_source = arrayindex(regextract(_raw_log, ",Source:\s+([^,]+)"), 0),
    _risk_file_path = arrayindex(regextract(_raw_log, "File path:\s+([^,]+)"), 0),
    _risk_description = arrayindex(regextract(_raw_log, ",Description:\s+([^,]+)"), 0),
    _risk_actual_action = arrayindex(regextract(_raw_log, "Actual action:\s+([^,]+)"), 0),
    // Virus-found Requested / Secondary action verbs. Requested is
    _risk_requested_action = arrayindex(regextract(_raw_log, "Requested action:\s+([^,]+)"), 0),
    _risk_secondary_action = arrayindex(regextract(_raw_log, "Secondary action:\s+([^,]+)"), 0),
    _risk_group = arrayindex(regextract(_raw_log, "Group Name:\s+([^,]+)"), 0),
    _risk_src_host = arrayindex(regextract(_raw_log, "Source Computer Name:\s+([^,]+)"), 0),
    _risk_src_ip = arrayindex(regextract(_raw_log, "Source Computer IP:\s+([^,]+)"), 0),
    // Virus-found temporal fields (`%Y-%m-%d %H:%M:%S` form per the
    _risk_event_time = arrayindex(regextract(_raw_log, "Event time:\s+(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})"), 0),
    _risk_end_time = arrayindex(regextract(_raw_log, "End Time:\s+(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})"), 0),
    // Virus-found additional fields ------------------------------------
    _risk_disposition = arrayindex(regextract(_raw_log, "Disposition:\s+([^,]+)"), 0),
    _risk_occurrences = arrayindex(regextract(_raw_log, "Occurrences:\s+(\d+)"), 0),
    // Certificate fields. Only `_risk_cert_signer` has a canonical
    _risk_cert_issuer = arrayindex(regextract(_raw_log, "Certificate issuer:\s*([^,]+)"), 0),
    _risk_cert_signer = arrayindex(regextract(_raw_log, "Certificate signer:\s*([^,]+)"), 0),
    _risk_cert_thumbprint = arrayindex(regextract(_raw_log, "Certificate thumbprint:\s*([^,]+)"), 0),
    _risk_cert_serial = arrayindex(regextract(_raw_log, "Certificate serial number:\s*([^,]+)"), 0),
    _risk_signing_ts = arrayindex(regextract(_raw_log, "Signing timestamp:\s+(\d+)"), 0),

    // IPS / TRAFFIC shared extractions ----------------------------------
    _direction = arrayindex(regextract(_raw_log, "\b(Inbound|Outbound)\b"), 0),
    _local_host_name = arrayindex(regextract(_raw_log, "Local Host Name:\s+([^,]+)"), 0),
    _local_host_ip = arrayindex(regextract(_raw_log, "Local Host IP:\s+([^,]+)"), 0),
    _local_host_mac = arrayindex(regextract(_raw_log, "Local Host MAC:\s+([^,]+)"), 0),
    _local_port = arrayindex(regextract(_raw_log, "Local Port:\s+([^,]+)"), 0),
    _remote_host_name = arrayindex(regextract(_raw_log, "Remote Host Name:\s+([^,]+)"), 0),
    _remote_host_ip = arrayindex(regextract(_raw_log, "Remote Host IP:\s+([^,]+)"), 0),
    _remote_host_mac = arrayindex(regextract(_raw_log, "Remote Host MAC:\s+([^,]+)"), 0),
    _remote_port = arrayindex(regextract(_raw_log, "Remote Port:\s+([^,]+)"), 0),
    _net_proto = arrayindex(regextract(_raw_log, "\b(OTHERS|TCP|UDP|ICMP)\b"), 0),
    _net_app = arrayindex(regextract(_raw_log, "Application:\s*([^,]*)"), 0),
    _net_location = arrayindex(regextract(_raw_log, "Location:\s+([^,]+)"), 0),

    // IPS-specific ------------------------------------------------------
    _ips_event_desc = arrayindex(regextract(_raw_log, "Event Description:\s+([^,]+)"), 0),
    _ips_event_type = arrayindex(regextract(_raw_log, "Event Type:\s+([^,]+)"), 0),
    _ips_cids_id = arrayindex(regextract(_raw_log, "CIDS Signature ID:\s+([^,]+)"), 0),
    _ips_cids_str = arrayindex(regextract(_raw_log, "CIDS Signature string:\s+([^,]+)"), 0),
    _ips_url = arrayindex(regextract(_raw_log, "Intrusion URL:\s+([^,]+)"), 0),
    _ips_url_cat = arrayindex(regextract(_raw_log, "URL Category:\s+(.+?)$"), 0),
    _file_sha256 = arrayindex(regextract(_raw_log, "SHA-256:\s+([^,]+)"), 0),
    _file_md5 = arrayindex(regextract(_raw_log, "MD-5:\s+([^,]+)"), 0),

    // TRAFFIC-specific --------------------------------------------------
    _traffic_action = arrayindex(regextract(_raw_log, ",Action:\s+([^,]+)"), 0),
    _network_rule = arrayindex(regextract(_raw_log, "Rule:\s+([^,]+)"), 0),

    // IPS positional action token (4th field after Remote Host MAC).
    _ips_action = arrayindex(regextract(_raw_log, "Remote Host MAC:\s+[^,]*,[^,]*,[^,]*,([^,]+),"), 0),

    // BEHAVIOR-specific (positional after `SymantecServer:`) ------------
    _bhv_host = arrayindex(regextract(_raw_log, "SymantecServer:\s+([^,]+),"), 0),
    _bhv_ip = arrayindex(regextract(_raw_log, "SymantecServer:\s+[^,]+,([^,]+),"), 0),
    _bhv_cmdline = arrayindex(regextract(_raw_log, "SymantecServer:\s+[^,]+,[^,]+,[^,]+,([^,]+),"), 0),
    _bhv_event_desc = arrayindex(regextract(_raw_log, "SymantecServer:\s+[^,]+,[^,]+,[^,]+,[^,]+,([^,]+),"), 0),
    _bhv_pid = arrayindex(regextract(_raw_log, "Rule:\s+[^,]*,(\d+),"), 0),
    // Process name sits as the 2nd field after `Rule: <rule_name>`
    _bhv_proc_name = arrayindex(regextract(_raw_log, "Rule:\s+[^,]*,\d+,([^,]+)"), 0),
    _bhv_device_id = arrayindex(regextract(_raw_log, "Device ID:\s+([^,]+)"), 0),
    _bhv_action_type = arrayindex(regextract(_raw_log, "Action Type:\s+([^,]+)"), 0),

    // SYSTEM-specific positional tail (gated in Stage 6) ----------------
    _sys_message = arrayindex(regextract(_raw_log, "SymantecServer:\s+Site:\s+[^,]+,Server Name:\s+[^,]+,Domain Name:\s+[^,]+,([^,]+),"), 0),
    _sys_computer = arrayindex(regextract(_raw_log, "SymantecServer:\s+Site:\s+[^,]+,Server Name:\s+[^,]+,Domain Name:\s+[^,]+,[^,]+,([^,]+),"), 0),
    _sys_user = arrayindex(regextract(_raw_log, "SymantecServer:\s+Site:\s+[^,]+,Server Name:\s+[^,]+,Domain Name:\s+[^,]+,[^,]+,[^,]+,([^,]+),"), 0),
    _sys_user_domain = arrayindex(regextract(_raw_log, "SymantecServer:\s+Site:\s+[^,]+,Server Name:\s+[^,]+,Domain Name:\s+[^,]+,[^,]+,[^,]+,[^,]+,(\S+)\s*$"), 0),

    // MITRE token extraction. Subtype-gated to RISK and IPS only --
    _mitre_tactic_ids = if(
        _subtype = "RISK" or _subtype = "IPS",
        regextract(_raw_log, "(TA0\d{3})")),
    _mitre_technique_ids = if(
        _subtype = "RISK" or _subtype = "IPS",
        regextract(_raw_log, "\b(T\d{4}(?:\.\d{3})?)\b"))

// -- Stage 3: Leaf derivations from stage-2 outputs ----------------------
// Each target depends ONLY on stage-2 outputs (or vendor columns). No
// sibling references in this stage.
| alter
    // Object-type-gated IPv4 / IPv6 routing per IP source. Route by
    // character family: dotted-quad to v4, colon-bearing hex string to
    // v6. Replaces the legacy fixed-width 8-group IPv6 regex.
    _risk_ipv4 = if(_risk_ip ~= "^\d{1,3}(\.\d{1,3}){3}$", _risk_ip),
    _risk_ipv6 = if(_risk_ip ~= "^[0-9a-fA-F:]+$" and _risk_ip ~= ":", _risk_ip),
    _risk_src_ipv4 = if(_risk_src_ip ~= "^\d{1,3}(\.\d{1,3}){3}$", _risk_src_ip),
    _risk_src_ipv6 = if(_risk_src_ip ~= "^[0-9a-fA-F:]+$" and _risk_src_ip ~= ":", _risk_src_ip),
    _local_ipv4 = if(_local_host_ip ~= "^\d{1,3}(\.\d{1,3}){3}$", _local_host_ip),
    _local_ipv6 = if(_local_host_ip ~= "^[0-9a-fA-F:]+$" and _local_host_ip ~= ":", _local_host_ip),
    _remote_ipv4 = if(_remote_host_ip ~= "^\d{1,3}(\.\d{1,3}){3}$", _remote_host_ip),
    _remote_ipv6 = if(_remote_host_ip ~= "^[0-9a-fA-F:]+$" and _remote_host_ip ~= ":", _remote_host_ip),
    _bhv_ipv4 = if(_bhv_ip ~= "^\d{1,3}(\.\d{1,3}){3}$", _bhv_ip),
    _bhv_ipv6 = if(_bhv_ip ~= "^[0-9a-fA-F:]+$" and _bhv_ip ~= ":", _bhv_ip),

    // Banded severity from SEP Sensitivity (1..9 numeric ladder; the
    // five-bucket Critical / High / Medium / Low / Informational
    // vocabulary preserved here so existing dashboards reading
    // `xdm.alert.severity` continue to see the legacy values when the
    // parser anchor `_severity` (four-bucket SEP-native enum) is NULL.
    // The Stage 3.5 alter below stamps the four-bucket anchor; the
    // sink at the end of the rule prefers the anchor and falls back
    // to this banded ladder. See PRIVATE_DOCS/anchor_field_design.md.
    _severity_band = if(
        _subtype = "RISK" and _risk_sensitivity ~= "^[89]$", "Critical",
        _subtype = "RISK" and _risk_sensitivity ~= "^[67]$", "High",
        _subtype = "RISK" and _risk_sensitivity ~= "^[45]$", "Medium",
        _subtype = "RISK" and _risk_sensitivity ~= "^[1-3]$", "Low",
        _subtype = "RISK" and _risk_kind = "VIRUS" and (_risk_disposition ~= "(?i)^bad$" or _risk_name ~= "^WS\.Malware\.\d+$"), "High",
        _subtype = "RISK" and _risk_detection_type ~= "(?i)signature|antivirus|definition", "High",
        _subtype = "RISK" and _risk_detection_type ~= "(?i)heuristic|reputation|insight", "Medium",
        _subtype = "RISK", "Medium",
        _subtype = "IPS", "High",
        _subtype = "BEHAVIOR", "Medium",
        _subtype = "TRAFFIC", "Informational",
        _subtype = "SYSTEM", "Informational"),

    _log_level = if(
        _subtype = "RISK" and _risk_sensitivity ~= "^[89]$", XDM_CONST.LOG_LEVEL_CRITICAL,
        _subtype = "RISK" and _risk_sensitivity ~= "^[67]$", XDM_CONST.LOG_LEVEL_ERROR,
        _subtype = "RISK" and _risk_sensitivity ~= "^[45]$", XDM_CONST.LOG_LEVEL_WARNING,
        _subtype = "RISK" and _risk_sensitivity ~= "^[1-3]$", XDM_CONST.LOG_LEVEL_NOTICE,
        _subtype = "RISK" and _risk_kind = "VIRUS" and (_risk_disposition ~= "(?i)^bad$" or _risk_name ~= "^WS\.Malware\.\d+$"), XDM_CONST.LOG_LEVEL_ERROR,
        _subtype = "RISK", XDM_CONST.LOG_LEVEL_WARNING,
        _subtype = "IPS", XDM_CONST.LOG_LEVEL_ERROR,
        _subtype = "BEHAVIOR", XDM_CONST.LOG_LEVEL_WARNING,
        _subtype = "TRAFFIC", XDM_CONST.LOG_LEVEL_INFORMATIONAL,
        _subtype = "SYSTEM", XDM_CONST.LOG_LEVEL_INFORMATIONAL),

    // Threat category mapping (first matched constant wins; null when
    _category_const = if(
        _risk_app_type_code = "47", XDM_CONST.THREAT_CATEGORY_BACKDOOR,
        _risk_app_type_code = "48", XDM_CONST.THREAT_CATEGORY_BACKDOOR,
        _risk_app_type_code = "100", XDM_CONST.THREAT_CATEGORY_ADWARE,
        _risk_app_type_code = "104", XDM_CONST.THREAT_CATEGORY_SPYWARE,
        _risk_app_type_code = "124", XDM_CONST.THREAT_CATEGORY_BACKDOOR,
        _risk_app_type_code = "126", XDM_CONST.THREAT_CATEGORY_HACKTOOL,
        _risk_app_type_code = "127", XDM_CONST.THREAT_CATEGORY_BACKDOOR,
        _risk_app_type_code = "128", XDM_CONST.THREAT_CATEGORY_CRYPTOMINER,
        _risk_category_set ~= "(?i)malware", XDM_CONST.THREAT_CATEGORY_BACKDOOR,
        _risk_category_set ~= "(?i)spyware", XDM_CONST.THREAT_CATEGORY_SPYWARE,
        _risk_category_set ~= "(?i)adware", XDM_CONST.THREAT_CATEGORY_ADWARE,
        _risk_category_set ~= "(?i)hack\s?tool", XDM_CONST.THREAT_CATEGORY_HACKTOOL,
        _risk_app_type ~= "(?i)trojan|worm|backdoor", XDM_CONST.THREAT_CATEGORY_BACKDOOR,
        _risk_app_type ~= "(?i)spyware|stealer", XDM_CONST.THREAT_CATEGORY_SPYWARE,
        _risk_app_type ~= "(?i)cryptominer|coin\s?miner|miner", XDM_CONST.THREAT_CATEGORY_CRYPTOMINER,
        _risk_app_type ~= "(?i)hack\s?tool", XDM_CONST.THREAT_CATEGORY_HACKTOOL,
        _risk_app_type ~= "(?i)phish", XDM_CONST.THREAT_CATEGORY_PHISHING,
        _risk_app_type ~= "(?i)adware", XDM_CONST.THREAT_CATEGORY_ADWARE,
        _risk_category ~= "(?i)trojan|worm|backdoor", XDM_CONST.THREAT_CATEGORY_BACKDOOR,
        _risk_category ~= "(?i)spyware", XDM_CONST.THREAT_CATEGORY_SPYWARE,
        _risk_category ~= "(?i)cryptominer|miner", XDM_CONST.THREAT_CATEGORY_CRYPTOMINER,
        _risk_category ~= "(?i)brute", XDM_CONST.THREAT_CATEGORY_BRUTE_FORCE,
        _risk_category ~= "(?i)phish", XDM_CONST.THREAT_CATEGORY_PHISHING,
        _risk_category ~= "(?i)dos|ddos", XDM_CONST.THREAT_CATEGORY_DOS,
        _risk_category ~= "(?i)botnet", XDM_CONST.THREAT_CATEGORY_BOTNET,
        _ips_event_type ~= "(?i)brute", XDM_CONST.THREAT_CATEGORY_BRUTE_FORCE,
        _ips_event_type ~= "(?i)dos|ddos", XDM_CONST.THREAT_CATEGORY_DOS,
        _ips_event_type ~= "(?i)code|exploit", XDM_CONST.THREAT_CATEGORY_CODE_EXECUTION,
        _ips_event_type ~= "(?i)protocol", XDM_CONST.THREAT_CATEGORY_PROTOCOL_ANOMALY,
        _ips_url_cat ~= "(?i)phish", XDM_CONST.THREAT_CATEGORY_PHISHING,
        _ips_url_cat ~= "(?i)malware", XDM_CONST.THREAT_CATEGORY_BACKDOOR),

    // Outcome mapping. SEP "Actual action" values include "Quarantined",
    _outcome = if(
        _risk_actual_action ~= "(?i)quarantin|delet|clean|block|denied|removed|terminat", XDM_CONST.OUTCOME_SUCCESS,
        _risk_actual_action ~= "(?i)left\s+alone|no\s+action", XDM_CONST.OUTCOME_FAILED,
        _traffic_action ~= "(?i)block|denied|drop|reject|allow|permit|pass", XDM_CONST.OUTCOME_SUCCESS,
        _bhv_action_type ~= "(?i)block|denied|allow", XDM_CONST.OUTCOME_SUCCESS,
        _ips_action ~= "(?i)block|denied|drop|reject|terminat|allow|permit|pass", XDM_CONST.OUTCOME_SUCCESS,
        _subtype = "SYSTEM", XDM_CONST.OUTCOME_SUCCESS,
        XDM_CONST.OUTCOME_UNKNOWN),

    // Alert status: DONE when the observer took a containment action
    // (or for SYSTEM audit events which are intrinsically post-fact);
    // PENDING otherwise so analyst triage queues pick the alert up.
    _alert_status = if(
        _risk_actual_action ~= "(?i)quarantin|delet|clean|block|denied|removed|terminat", XDM_CONST.ALERT_STATUS_DONE,
        _traffic_action ~= "(?i)block|denied|drop|reject", XDM_CONST.ALERT_STATUS_DONE,
        _bhv_action_type ~= "(?i)block|denied", XDM_CONST.ALERT_STATUS_DONE,
        _ips_action ~= "(?i)block|denied|drop|reject|terminat", XDM_CONST.ALERT_STATUS_DONE,
        _subtype = "SYSTEM", XDM_CONST.ALERT_STATUS_DONE,
        XDM_CONST.ALERT_STATUS_PENDING),

    // Event-type strings (free-text per the Cortex schema; canonical
    // values listed in the schema guide).
    _event_type_str = if(
        _subtype = "RISK", "ALERT",
        _subtype = "IPS", "ALERT",
        _subtype = "BEHAVIOR", "ALERT",
        _subtype = "TRAFFIC", "NETWORK",
        _subtype = "SYSTEM", "AUDIT"),

    _original_event_type = if(
        _subtype = "RISK", "Potential risk found",
        _subtype = "IPS", "Intrusion",
        _subtype = "BEHAVIOR", "Behavioral Detection",
        _subtype = "TRAFFIC", "Network Traffic",
        _subtype = "SYSTEM", "System"),

    // MITRE constant arrays via arraymap + if-chain. Unmapped IDs -> null.
    _mitre_tactics_const = arraymap(_mitre_tactic_ids, if(
        "@element" = "TA0001", XDM_CONST.MITRE_TACTIC_INITIAL_ACCESS,
        "@element" = "TA0002", XDM_CONST.MITRE_TACTIC_EXECUTION,
        "@element" = "TA0003", XDM_CONST.MITRE_TACTIC_PERSISTENCE,
        "@element" = "TA0004", XDM_CONST.MITRE_TACTIC_PRIVILEGE_ESCALATION,
        "@element" = "TA0005", XDM_CONST.MITRE_TACTIC_DEFENSE_EVASION,
        "@element" = "TA0006", XDM_CONST.MITRE_TACTIC_CREDENTIAL_ACCESS,
        "@element" = "TA0007", XDM_CONST.MITRE_TACTIC_DISCOVERY,
        "@element" = "TA0008", XDM_CONST.MITRE_TACTIC_LATERAL_MOVEMENT,
        "@element" = "TA0009", XDM_CONST.MITRE_TACTIC_COLLECTION,
        "@element" = "TA0010", XDM_CONST.MITRE_TACTIC_EXFILTRATION,
        "@element" = "TA0011", XDM_CONST.MITRE_TACTIC_COMMAND_AND_CONTROL,
        "@element" = "TA0040", XDM_CONST.MITRE_TACTIC_IMPACT,
        "@element" = "TA0042", XDM_CONST.MITRE_TACTIC_RESOURCE_DEVELOPMENT,
        "@element" = "TA0043", XDM_CONST.MITRE_TACTIC_RECONNAISSANCE)),

    // Technique mapping table -- covers ATT&CK techniques observed in
    _mitre_techniques_const = arraymap(_mitre_technique_ids, if(
        "@element" = "T1027", XDM_CONST.MITRE_TECHNIQUE_OBFUSCATED_FILES_OR_INFORMATION,
        "@element" = "T1036", XDM_CONST.MITRE_TECHNIQUE_MASQUERADING,
        "@element" = "T1041", XDM_CONST.MITRE_TECHNIQUE_EXFILTRATION_OVER_C2_CHANNEL,
        "@element" = "T1048", XDM_CONST.MITRE_TECHNIQUE_EXFILTRATION_OVER_ALTERNATIVE_PROTOCOL,
        "@element" = "T1055", XDM_CONST.MITRE_TECHNIQUE_PROCESS_INJECTION,
        "@element" = "T1057", XDM_CONST.MITRE_TECHNIQUE_PROCESS_DISCOVERY,
        "@element" = "T1059", XDM_CONST.MITRE_TECHNIQUE_COMMAND_AND_SCRIPTING_INTERPRETER,
        "@element" = "T1068", XDM_CONST.MITRE_TECHNIQUE_EXPLOITATION_FOR_PRIVILEGE_ESCALATION,
        "@element" = "T1071", XDM_CONST.MITRE_TECHNIQUE_WEB_SERVICE,
        "@element" = "T1078", XDM_CONST.MITRE_TECHNIQUE_VALID_ACCOUNTS,
        "@element" = "T1082", XDM_CONST.MITRE_TECHNIQUE_SYSTEM_INFORMATION_DISCOVERY,
        "@element" = "T1083", XDM_CONST.MITRE_TECHNIQUE_FILE_AND_DIRECTORY_DISCOVERY,
        "@element" = "T1087", XDM_CONST.MITRE_TECHNIQUE_ACCOUNT_DISCOVERY,
        "@element" = "T1098", XDM_CONST.MITRE_TECHNIQUE_ACCOUNT_MANIPULATION,
        "@element" = "T1003", XDM_CONST.MITRE_TECHNIQUE_OS_CREDENTIAL_DUMPING,
        "@element" = "T1105", XDM_CONST.MITRE_TECHNIQUE_INGRESS_TOOL_TRANSFER,
        "@element" = "T1110", XDM_CONST.MITRE_TECHNIQUE_BRUTE_FORCE,
        "@element" = "T1112", XDM_CONST.MITRE_TECHNIQUE_MODIFY_REGISTRY,
        "@element" = "T1133", XDM_CONST.MITRE_TECHNIQUE_EXTERNAL_REMOTE_SERVICES,
        "@element" = "T1136", XDM_CONST.MITRE_TECHNIQUE_CREATE_ACCOUNT,
        "@element" = "T1140", XDM_CONST.MITRE_TECHNIQUE_DEOBFUSCATE_DECODE_FILES_OR_INFORMATION,
        "@element" = "T1190", XDM_CONST.MITRE_TECHNIQUE_EXPLOIT_PUBLIC_FACING_APPLICATION,
        "@element" = "T1203", XDM_CONST.MITRE_TECHNIQUE_EXPLOITATION_FOR_CLIENT_EXECUTION,
        "@element" = "T1210", XDM_CONST.MITRE_TECHNIQUE_EXPLOITATION_OF_REMOTE_SERVICES,
        "@element" = "T1486", XDM_CONST.MITRE_TECHNIQUE_DATA_ENCRYPTED_FOR_IMPACT,
        "@element" = "T1547", XDM_CONST.MITRE_TECHNIQUE_BOOT_OR_LOGON_AUTOSTART_EXECUTION,
        "@element" = "T1566", XDM_CONST.MITRE_TECHNIQUE_PHISHING)),

    // Stable per-event identifier for alert correlation. SEP syslog
    _alert_original_id = coalesce(
        arrayindex(regextract(_raw_log, "(?:Event Description ID|Event ID):\s+(\d+)"), 0),
        concat(
            coalesce(_subtype, "UNKNOWN"), "|",
            to_string(_insert_time), "|",
            coalesce(_risk_src_host, _risk_computer, _local_host_name, _remote_host_name, _bhv_host, _syslog_host, ""), "|",
            coalesce(_risk_name, _ips_cids_id, _ips_event_desc, _network_rule, _bhv_event_desc, "")))

// -- Stage 3.5: Anchor keep-in-both -------------------------------------
// `_sep_category` and `_severity` are stamped on every row by
// `parser.xql`. The data-model rule still independently derives both
// values from `_raw_log` so historical / backfill / replayed rows
// (which predate the parser and have the column NULL) model
// identically. See PRIVATE_DOCS/anchor_field_design.md and rules
// 21-30 in PRIVATE_DOCS/cortex_xsiam_authoring_rules.md.
| alter
    _sep_category = coalesce(_sep_category, if(
        _subtype = "RISK",                                                          "AntiVirus",
        _subtype = "IPS",                                                           "IPS",
        _raw_log ~= "(?i)Tamper\s+Protection|Self-?Protection",                     "Tamper",
        _raw_log ~= "(?i)Device\s+Control",                                         "DeviceControl",
        _raw_log ~= "(?i)Application\s+Control",                                    "ApplicationControl",
        _raw_log ~= "(?i)\b(Logon|Logoff|Authentication\s+(?:succeeded|failed))\b", "Auth",
        _raw_log ~= "(?i)Policy\s+(?:has\s+been|applied|update|change)",            "Policy",
        _subtype = "BEHAVIOR",                                                      "BehaviorMonitoring",
        _subtype = "TRAFFIC",                                                       "Firewall",
        _subtype = "SYSTEM",                                                        "System")),
    _severity = coalesce(
        _severity,
        arrayindex(regextract(_raw_log, "Severity:\s+(Info|Warning|Major|Critical)\b"), 0),
        if(
            _risk_sensitivity ~= "^[89]$",  "Critical",
            _risk_sensitivity ~= "^[67]$",  "Major",
            _risk_sensitivity ~= "^[45]$",  "Warning",
            _risk_sensitivity ~= "^[1-3]$", "Info"))

// -- Stage 4: Direction-aware network temps ------------------------------
// Resolve Local/Remote -> source/target using the Direction token.
| alter
    _net_src_ipv4 = if(_direction = "Inbound", _remote_ipv4, _local_ipv4),
    _net_src_ipv6 = if(_direction = "Inbound", _remote_ipv6, _local_ipv6),
    _net_src_host = if(_direction = "Inbound", _remote_host_name, _local_host_name),
    _net_src_mac = if(_direction = "Inbound", _remote_host_mac, _local_host_mac),
    _net_src_port = if(_direction = "Inbound", to_integer(_remote_port), to_integer(_local_port)),
    _net_tgt_ipv4 = if(_direction = "Inbound", _local_ipv4, _remote_ipv4),
    _net_tgt_ipv6 = if(_direction = "Inbound", _local_ipv6, _remote_ipv6),
    _net_tgt_host = if(_direction = "Inbound", _local_host_name, _remote_host_name),
    _net_tgt_mac = if(_direction = "Inbound", _local_host_mac, _remote_host_mac),
    _net_tgt_port = if(_direction = "Inbound", to_integer(_local_port), to_integer(_remote_port))

// -- Stage 5: Sub-type final picks ---------------------------------------
| alter
    // Source side ------------------------------------------------------
    _xdm_src_ipv4 = if(
        _subtype = "RISK", coalesce(_risk_src_ipv4, _risk_ipv4),
        _subtype = "IPS" or _subtype = "TRAFFIC", _net_src_ipv4,
        _subtype = "BEHAVIOR", _bhv_ipv4),
    _xdm_src_ipv6 = if(
        _subtype = "RISK", coalesce(_risk_src_ipv6, _risk_ipv6),
        _subtype = "IPS" or _subtype = "TRAFFIC", _net_src_ipv6,
        _subtype = "BEHAVIOR", _bhv_ipv6),
    // For RISK with no Source Computer fields, mirror the infected
    // computer into the source side (Section 9.9 one-sided detection).
    _xdm_src_host = if(
        _subtype = "RISK", coalesce(_risk_src_host, _risk_computer),
        _subtype = "IPS" or _subtype = "TRAFFIC", _net_src_host,
        _subtype = "BEHAVIOR", _bhv_host,
        _subtype = "SYSTEM", _server_name),
    _xdm_src_mac = if(_subtype = "IPS" or _subtype = "TRAFFIC", _net_src_mac),
    _xdm_src_port = if(_subtype = "IPS" or _subtype = "TRAFFIC", _net_src_port),
    _xdm_src_user = if(_subtype = "SYSTEM", _sys_user, _user_name_kv),
    _xdm_src_user_domain = if(_subtype = "SYSTEM", _sys_user_domain, _user_domain_kv),
    _xdm_src_groups = if(_subtype = "RISK" and _risk_group != null, arraycreate(_risk_group)),

    // Target side ------------------------------------------------------
    _xdm_tgt_ipv4 = if(
        _subtype = "RISK", _risk_ipv4,
        _subtype = "IPS" or _subtype = "TRAFFIC", _net_tgt_ipv4),
    _xdm_tgt_ipv6 = if(
        _subtype = "RISK", _risk_ipv6,
        _subtype = "IPS" or _subtype = "TRAFFIC", _net_tgt_ipv6),
    _xdm_tgt_host = if(
        _subtype = "RISK", _risk_computer,
        _subtype = "IPS" or _subtype = "TRAFFIC", _net_tgt_host,
        _subtype = "SYSTEM", _sys_computer),
    _xdm_tgt_mac = if(_subtype = "IPS" or _subtype = "TRAFFIC", _net_tgt_mac),
    _xdm_tgt_port = if(_subtype = "IPS" or _subtype = "TRAFFIC", _net_tgt_port),

    // Alert / event field selection ------------------------------------
    _alert_name = if(
        _subtype = "RISK", coalesce(_risk_name, _risk_app_name),
        _subtype = "IPS", _ips_cids_str,
        _subtype = "BEHAVIOR", _network_rule),
    _alert_id = if(_subtype = "IPS", _ips_cids_id),
    _alert_desc = if(
        _subtype = "RISK", coalesce(_risk_description, _risk_source),
        _subtype = "IPS", _ips_event_desc,
        _subtype = "BEHAVIOR", _bhv_event_desc),
    // For VIRUS records the Cortex schema (per the in-repo
    _event_desc = if(
        _subtype = "RISK" and _risk_kind = "VIRUS",
            concat(
                coalesce(_risk_source, _risk_description, _risk_app_name, ""),
                if(_risk_occurrences != null, concat("; Occurrences: ", _risk_occurrences), ""),
                if(_risk_event_time != null, concat("; Event time: ", _risk_event_time), ""),
                if(_risk_end_time != null, concat("; End Time: ", _risk_end_time), "")),
        _subtype = "RISK", coalesce(_risk_source, _risk_description, _risk_app_name),
        _subtype = "IPS", _ips_event_type,
        _subtype = "BEHAVIOR", _bhv_event_desc,
        _subtype = "TRAFFIC", _network_rule,
        _subtype = "SYSTEM", _sys_message),
    _alert_subcategory = if(
        _subtype = "RISK", coalesce(_risk_detection_type, _risk_app_type),
        _subtype = "IPS", _ips_url_cat,
        _subtype = "BEHAVIOR", _bhv_action_type),
    // Raw vendor action verb -- preserved for `xdm.event.outcome_reason`
    _observer_action_raw = if(
        _subtype = "RISK" and _risk_kind = "VIRUS" and _risk_actual_action != null,
            concat(
                _risk_actual_action,
                if(_risk_secondary_action != null, concat("; secondary: ", _risk_secondary_action), ""),
                if(_risk_requested_action != null and _risk_requested_action != _risk_actual_action, concat("; requested: ", _risk_requested_action), "")),
        _subtype = "RISK", _risk_actual_action,
        _subtype = "TRAFFIC", _traffic_action,
        _subtype = "BEHAVIOR", _bhv_action_type,
        _subtype = "IPS", _ips_action),
    _proc_name = if(
        _subtype = "RISK", _risk_app_name,
        _subtype = "IPS" or _subtype = "TRAFFIC", _net_app,
        _subtype = "BEHAVIOR", _bhv_proc_name),
    _proc_sha256 = coalesce(_file_sha256, if(_subtype = "RISK", _risk_app_hash))

// -- Stage 6: Final XDM drain --------------------------------------------
| alter
    // Observer ---------------------------------------------------------
    xdm.observer.vendor = "Symantec",
    xdm.observer.product = "Endpoint Protection",
    xdm.observer.name = coalesce(_server_name, _syslog_host),
    // observer.action takes the canonical OUTCOME constant (the schema
    // datatype is String and there is no observer-action enum); the
    // literal vendor verb is retained on xdm.event.outcome_reason.
    xdm.observer.action = _outcome,

    // Event ------------------------------------------------------------
    xdm.event.type = _event_type_str,
    xdm.event.original_event_type = if(
        _subtype = "RISK" and _risk_kind = "VIRUS", "Virus found",
        _original_event_type),
    xdm.event.description = _event_desc,
    xdm.event.log_level = _log_level,
    xdm.event.outcome = _outcome,
    xdm.event.outcome_reason = _observer_action_raw,

    // Alert ------------------------------------------------------------
    xdm.alert.name = _alert_name,
    xdm.alert.original_alert_id = _alert_original_id,
    xdm.alert.original_threat_name = _alert_name,
    xdm.alert.original_threat_id = _alert_id,
    xdm.alert.description = _alert_desc,
    xdm.alert.severity = coalesce(_severity, _severity_band),
    xdm.alert.status = _alert_status,
    xdm.alert.category = _category_const,
    xdm.alert.subcategory = coalesce(_alert_subcategory, _sep_category),
    xdm.alert.mitre_tactics = _mitre_tactics_const,
    xdm.alert.mitre_techniques = _mitre_techniques_const,

    // Source -----------------------------------------------------------
    xdm.source.ipv4 = _xdm_src_ipv4,
    xdm.source.ipv6 = _xdm_src_ipv6,
    xdm.source.port = _xdm_src_port,
    xdm.source.host.hostname = _xdm_src_host,
    xdm.source.host.mac_addresses = if(_xdm_src_mac != null, arraycreate(_xdm_src_mac)),
    xdm.source.host.device_id = if(_subtype = "BEHAVIOR", _bhv_device_id),
    xdm.source.user.username = _xdm_src_user,
    xdm.source.user.domain = _xdm_src_user_domain,
    xdm.source.user.groups = _xdm_src_groups,
    xdm.source.zone = if(_subtype = "IPS" or _subtype = "TRAFFIC", _net_location),
    xdm.source.application.name = if(_subtype = "IPS" or _subtype = "TRAFFIC", _net_app),
    xdm.source.process.name = _proc_name,
    xdm.source.process.command_line = if(_subtype = "BEHAVIOR", _bhv_cmdline),
    xdm.source.process.pid = if(_subtype = "BEHAVIOR" and _bhv_pid != null, to_integer(_bhv_pid)),
    xdm.source.process.executable.sha256 = _proc_sha256,
    xdm.source.process.executable.md5 = _file_md5,

    // Target -----------------------------------------------------------
    xdm.target.ipv4 = _xdm_tgt_ipv4,
    xdm.target.ipv6 = _xdm_tgt_ipv6,
    xdm.target.port = _xdm_tgt_port,
    xdm.target.host.hostname = _xdm_tgt_host,
    xdm.target.host.mac_addresses = if(_xdm_tgt_mac != null, arraycreate(_xdm_tgt_mac)),
    xdm.target.url = if(_subtype = "IPS", _ips_url),
    xdm.target.file.path = if(_subtype = "RISK", _risk_file_path),
    xdm.target.file.sha256 = if(_subtype = "RISK", _risk_app_hash),
    xdm.target.file.size = if(_subtype = "RISK" and _risk_file_size != null, to_integer(_risk_file_size)),
    // Virus-found certificate sinks. Only `signer` has a canonical
    xdm.target.file.signer = if(
        _subtype = "RISK" and _risk_kind = "VIRUS" and _risk_cert_signer != null and trim(_risk_cert_signer) != "",
        _risk_cert_signer),
    xdm.target.file.is_signed = if(
        _subtype = "RISK" and _risk_kind = "VIRUS"
            and ((_risk_cert_issuer != null and trim(_risk_cert_issuer) != "")
                or (_risk_cert_signer != null and trim(_risk_cert_signer) != "")
                or (_risk_cert_thumbprint != null and trim(_risk_cert_thumbprint) != "")
                or (_risk_cert_serial != null and trim(_risk_cert_serial) != "")
                or (_risk_signing_ts != null and _risk_signing_ts != "0")),
        true),
    // xdm.target.application.name intentionally left unset. SEP RISK
    xdm.target.domain = if(_subtype = "RISK", _user_domain_kv),

    // Network ----------------------------------------------------------
    xdm.network.ip_protocol = _net_proto,
    xdm.network.rule = if(_subtype = "TRAFFIC" or _subtype = "BEHAVIOR", _network_rule);
