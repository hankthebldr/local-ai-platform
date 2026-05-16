// Microsoft Defender for Cloud Apps Alerts -- XDM Data Model Rule
// Dataset: microsoftcloudappsecurity_generic_alert_raw
// Vendor: Microsoft | Product: Defender for Cloud Apps
//
// Maps Microsoft Defender for Cloud Apps (formerly MCAS) alert payloads
// to the Cortex XDM schema. The XSIAM ingest pipeline pre-flattens each
// entity class into its own top-level array (ip, account, country,
// service, policyRule) plus a single policy object, so this rule reads
// directly from those rather than walking a heterogeneous entities[].
//
// Documentation: microsoft_defender_cloud_apps_alerts_xdm_model_rule_documentation.md
//
// SPDX-FileCopyrightText: GoCortexIO
// SPDX-License-Identifier: AGPL-3.0-or-later

[MODEL: dataset = microsoftcloudappsecurity_generic_alert_raw]

filter title != null

// -- Stage 1: Top-level field aliases --------------------------------------
| alter
    _alert_id = _id,
    _alert_title = title,
    _alert_url = URL,
    _alert_context_id = contextId,
    _severity_value = to_integer(severityValue),
    _resolution_value = to_integer(resolutionStatusValue)

// -- Stage 2: First element of each pre-flattened top-level entity array --
| alter
    _account = arrayindex(account -> [], 0),
    _ip_entry = arrayindex(ip -> [], 0),
    _country_entry = arrayindex(country -> [], 0),
    _service_entry = arrayindex(service -> [], 0),
    _first_story_value = to_integer(arrayindex(stories -> [], 0))

// -- Stage 3: Pull scalars from each first element and the policy object --
// `account[0].em` is deliberately NOT captured into a temp -- the analyser
// raises ERR-019 ("unused underscore variable rejected on _gc_raw
// datasets") for any temp that does not transitively reach an xdm.*
// assignment, and the email has no clean XDM destination in the current
// schema (`pa` is already mapped to `xdm.source.user.upn`). See sibling
// md "Drift from plan". `policy.policyType` IS captured below as the
// `_policy_type` anchor (parser-stamped, with a keep-in-both coalesce
// fall-back) and sunk into `xdm.alert.subcategory`.
| alter
    _account_pa = json_extract_scalar(to_string(_account), "$.pa"),
    _account_id = json_extract_scalar(to_string(_account), "$.id"),
    _account_label = json_extract_scalar(to_string(_account), "$.label"),
    _ip_value = json_extract_scalar(to_string(_ip_entry), "$.id"),
    _country_code = json_extract_scalar(to_string(_country_entry), "$.id"),
    _service_label = json_extract_scalar(to_string(_service_entry), "$.label"),
    _policy_id = json_extract_scalar(to_string(policy), "$.id"),
    _policy_label = json_extract_scalar(to_string(policy), "$.label"),
    // Keep-in-both anchor: parser.xql stamps `_policy_type` at ingest
    // from `policy.policyType`. Parser-stamped rows short-circuit
    // through the column read; legacy / replayed / backfilled rows fall
    // through to the same JSON-path extraction below. Vocabulary: ~8
    // closed values (AnomalyDetectionPolicy, PolicyRuleAlerts,
    // ThreatProtection, MalwareProtection, DataLossPrevention,
    // AccessPolicy, SessionPolicy, OAUTH_APP_PERMISSION). Sunk into
    // `xdm.alert.subcategory` below as the first coalesce arm.
    _policy_type = coalesce(_policy_type, json_extract_scalar(to_string(policy), "$.policyType")),
    // Keep-in-both anchor: parser.xql stamps `_severity_band` at
    // ingest from the top-level `severity` enum. Parser-stamped rows
    // short-circuit; legacy rows fall through to the raw column.
    // Vocabulary: 3 closed values (LOW, MEDIUM, HIGH). Sunk into
    // `xdm.alert.severity` below as the first coalesce arm so the
    // vendor's canonical band wins over the integer-decoded label
    // when present, and the existing `_severity_label` covers the
    // Informational-only rows where `severity` is NULL.
    _severity_band = coalesce(_severity_band, severity)

// -- Stage 4: Route the single ip[0] address to ipv4 / ipv6 by family ------
| alter
    _effective_ipv4 = if(is_ipv4(_ip_value), _ip_value, null),
    _effective_ipv6 = if(is_ipv6(_ip_value), _ip_value, null)

// -- Stage 5: Decode severity, resolution and category labels --------------
| alter
    _severity_label = if(
        _severity_value = 0, "Low",
        _severity_value = 1, "Medium",
        _severity_value = 2, "High",
        _severity_value = 3, "Informational"),
    _resolution_label = if(
        _resolution_value = 0, "OPEN",
        _resolution_value = 1, "DISMISSED",
        _resolution_value = 2, "RESOLVED",
        _resolution_value = 3, "FALSE_POSITIVE",
        _resolution_value = 4, "BENIGN_TRUE_POSITIVE",
        _resolution_value = 5, "TRUE_POSITIVE"),
    _category_label = if(
        _first_story_value = 0, "ACCESS_CONTROL",
        _first_story_value = 1, "COMPLIANCE",
        _first_story_value = 2, "CONFIGURATION_MONITORING",
        _first_story_value = 3, "DLP",
        _first_story_value = 4, "DATA_GOVERNANCE",
        _first_story_value = 5, "PRIVILEGED_ACCOUNT_MONITORING",
        _first_story_value = 6, "SHARING_CONTROL",
        _first_story_value = 7, "THREAT_DETECTION",
        _first_story_value = 8, "DISCOVERY")

// -- Stage 6: Final XDM mapping --------------------------------------------
| alter
    xdm.observer.vendor = "Microsoft",
    xdm.observer.product = "Defender for Cloud Apps",

    xdm.event.id = _alert_id,
    xdm.event.type = "ALERT",
    xdm.event.original_event_type = _alert_title,
    xdm.event.description = description,
    xdm.event.tags = arraycreate(XDM_CONST.EVENT_TAG_CLOUD, XDM_CONST.EVENT_TAG_SAAS),
    xdm.event.outcome = if(
        _resolution_value = 4, XDM_CONST.OUTCOME_SUCCESS,
        _resolution_value = 5, XDM_CONST.OUTCOME_FAILED,
        XDM_CONST.OUTCOME_UNKNOWN),
    xdm.event.outcome_reason = _resolution_label,

    xdm.alert.original_alert_id = _alert_id,
    xdm.alert.original_threat_id = _alert_context_id,
    xdm.alert.original_threat_name = _policy_id,
    xdm.alert.name = _alert_title,
    xdm.alert.description = description,
    xdm.alert.severity = coalesce(_severity_band, _severity_label),
    xdm.alert.category = _category_label,
    xdm.alert.subcategory = coalesce(_policy_type, _policy_label),
    xdm.alert.status = if(
        _resolution_value = 0, XDM_CONST.ALERT_STATUS_PENDING,
        _resolution_value = 1, XDM_CONST.ALERT_STATUS_DONE,
        _resolution_value = 2, XDM_CONST.ALERT_STATUS_DONE,
        _resolution_value = 3, XDM_CONST.ALERT_STATUS_DONE,
        _resolution_value = 4, XDM_CONST.ALERT_STATUS_DONE,
        _resolution_value = 5, XDM_CONST.ALERT_STATUS_DONE,
        XDM_CONST.ALERT_STATUS_PENDING),
    // intent[] elements arrive typed as String in this dataset, so every
    // comparison MUST coerce via to_integer or Cortex returns
    // "Value N for operator = is invalid. Expected string but received
    // number" at data-model validation time. The outer arrayfilter
    // already uses to_integer for the same reason.
    // Default RECONNAISSANCE is unreachable (filter limits 1..13).
    xdm.alert.mitre_tactics = arraymap(
        arrayfilter(intent -> [], to_integer("@element") > 0 and to_integer("@element") < 14),
        if(
            to_integer("@element") = 1, XDM_CONST.MITRE_TACTIC_RECONNAISSANCE,
            to_integer("@element") = 2, XDM_CONST.MITRE_TACTIC_INITIAL_ACCESS,
            to_integer("@element") = 3, XDM_CONST.MITRE_TACTIC_PERSISTENCE,
            to_integer("@element") = 4, XDM_CONST.MITRE_TACTIC_PRIVILEGE_ESCALATION,
            to_integer("@element") = 5, XDM_CONST.MITRE_TACTIC_DEFENSE_EVASION,
            to_integer("@element") = 6, XDM_CONST.MITRE_TACTIC_CREDENTIAL_ACCESS,
            to_integer("@element") = 7, XDM_CONST.MITRE_TACTIC_DISCOVERY,
            to_integer("@element") = 8, XDM_CONST.MITRE_TACTIC_LATERAL_MOVEMENT,
            to_integer("@element") = 9, XDM_CONST.MITRE_TACTIC_EXECUTION,
            to_integer("@element") = 10, XDM_CONST.MITRE_TACTIC_COLLECTION,
            to_integer("@element") = 11, XDM_CONST.MITRE_TACTIC_EXFILTRATION,
            to_integer("@element") = 12, XDM_CONST.MITRE_TACTIC_COMMAND_AND_CONTROL,
            to_integer("@element") = 13, XDM_CONST.MITRE_TACTIC_IMPACT,
            XDM_CONST.MITRE_TACTIC_RECONNAISSANCE)),
    xdm.alert.source_url = _alert_url,

    xdm.source.ipv4 = _effective_ipv4,
    xdm.source.ipv6 = _effective_ipv6,
    xdm.source.user.upn = _account_pa,
    xdm.source.user.username = _account_label,
    xdm.source.user.identifier = _account_id,
    xdm.source.location.country = _country_code,

    xdm.target.ipv4 = _effective_ipv4,
    xdm.target.ipv6 = _effective_ipv6,
    xdm.target.user.username = _account_label,
    xdm.target.application.name = _service_label;
