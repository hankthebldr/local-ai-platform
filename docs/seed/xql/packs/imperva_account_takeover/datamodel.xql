// Imperva Account Takeover Protection -- XDM Data Model Rule
// Dataset: imperva_accounttakeover_raw
// Vendor: Imperva | Product: Account Takeover Protection
//
// Maps Imperva ATO SIEM event payloads to the Cortex XDM schema.
// Detects credential-stuffing and brute-force account takeover attempts.
//
// Documentation: imperva_account_takeover_xdm_model_rule_documentation.md
//
// SPDX-FileCopyrightText: GoCortexIO
// SPDX-License-Identifier: AGPL-3.0-or-later

[MODEL: dataset = imperva_accounttakeover_raw]

// -- Stage 1: Extract all fields from parsed columns ------------------------
alter
    _client_ip = json_extract_scalar(to_string(client), "$.ip"),
    _risk_reason = json_extract_scalar(to_string(imperva), "$.risk_reason"),
    // Keep-in-both anchor: parser.xql stamps `_risk_level` at ingest with
    // the same JSON-path extraction. Parser-stamped rows short-circuit
    // through the column read; legacy / replayed / backfilled rows fall
    // through to the json_extract_scalar() below. Vocabulary is tiny and
    // case-stable (vendor lowercase: low / medium / high / critical).
    _risk_level = coalesce(_risk_level, json_extract_scalar(to_string(imperva), "$.risk_level")),
    _country = json_extract_scalar(to_string(imperva), "$.country"),
    _request_id = json_extract_scalar(to_string(imperva), "$.request_id"),
    // Keep-in-both anchor: parser.xql stamps `_event_type` at ingest with
    // the same JSON-path extraction. Parser-stamped rows short-circuit
    // through the column read; legacy / replayed / backfilled rows fall
    // through to the json_extract_scalar() below. Six-value closed
    // vocabulary (LOGIN_FAILURE, LOGIN_SUCCESS, ACCOUNT_TAKEOVER,
    // SUSPICIOUS_LOGIN, MFA_CHALLENGE, MFA_SUCCESS) drives all
    // per-event-type branching downstream.
    _event_type = coalesce(_event_type, json_extract_scalar(to_string(imperva), "$.event_type")),
    _request_user = json_extract_scalar(to_string(imperva), "$.request_user"),
    _declared_client = json_extract_scalar(to_string(imperva), "$.declared_client"),
    _classified_client = json_extract_scalar(to_string(imperva), "$.classified_client"),
    _path = json_extract_scalar(to_string(imperva), "$.path"),
    _referrer = json_extract_scalar(to_string(imperva), "$.referrer"),
    _failed_logins = json_extract_scalar(to_string(imperva), "$.failed_logins_last_24h"),
    _successful_logins = json_extract_scalar(to_string(imperva), "$.successful_logins_last_24h"),
    _credentials_leaked = json_extract_scalar(to_string(imperva), "$.credentials_leaked"),
    _additional_factors = json_extract_scalar(to_string(imperva), "$.additional_factors"),
    _site_name = json_extract_scalar(to_string(imperva), "$.ids.site_name")

// -- Stage 2: Build description summary string -----------------------------
| alter
    _description = concat(
        "Classified client: ", coalesce(_classified_client, "unknown"),
        " | Failed logins (24h): ", coalesce(_failed_logins, "0"),
        " | Successful logins (24h): ", coalesce(_successful_logins, "0"),
        " | Credentials leaked: ", coalesce(_credentials_leaked, "false"),
        if(_additional_factors != null and _additional_factors != "",
            concat(" | Risk factors: ", _additional_factors), ""))

// -- Stage 3: Map to XDM fields -------------------------------------------
| alter
    // XDM Observer fields -- xdm.observer.*
    xdm.observer.vendor = "Imperva",
    xdm.observer.product = "Account Takeover Protection",

    // XDM Event fields -- xdm.event.*
    xdm.event.type = "ALERT",
    xdm.event.id = _request_id,
    xdm.event.original_event_type = _event_type,

    // XDM Alert fields -- xdm.alert.*
    xdm.alert.name = _risk_reason,
    xdm.alert.original_threat_name = _risk_reason,
    xdm.alert.subcategory = _risk_reason,
    xdm.alert.severity = if(
        _risk_level = "low", "Low",
        _risk_level = "medium", "Medium",
        _risk_level = "high", "High",
        _risk_level != null, _risk_level),
    xdm.alert.description = _description,
    xdm.alert.mitre_tactics = arraycreate(XDM_CONST.MITRE_TACTIC_CREDENTIAL_ACCESS),
    xdm.alert.mitre_techniques = arraycreate(if(
        _risk_reason = "Brute_Force", XDM_CONST.MITRE_TECHNIQUE_BRUTE_FORCE,
        _risk_reason = "Password_Brute_Force", XDM_CONST.MITRE_TECHNIQUE_BRUTE_FORCE,
        _risk_reason = "Credential_Stuffing", XDM_CONST.MITRE_TECHNIQUE_BRUTE_FORCE_CREDENTIAL_STUFFING,
        _risk_reason = "Common_Password", XDM_CONST.MITRE_TECHNIQUE_BRUTE_FORCE_PASSWORD_GUESSING,
        _risk_reason = "Common_User", XDM_CONST.MITRE_TECHNIQUE_BRUTE_FORCE,
        _risk_reason = "Abnormal_Behavior_By_Profile", XDM_CONST.MITRE_TECHNIQUE_BRUTE_FORCE,
        _risk_reason = "Dynamic_Bot_Signatures", XDM_CONST.MITRE_TECHNIQUE_BRUTE_FORCE,
        _risk_reason = "Scripting_Tool", XDM_CONST.MITRE_TECHNIQUE_BRUTE_FORCE,
        _risk_reason = "Suspicious_Number_Of_Users", XDM_CONST.MITRE_TECHNIQUE_BRUTE_FORCE,
        _risk_reason != null, XDM_CONST.MITRE_TECHNIQUE_BRUTE_FORCE)),

    // XDM Source fields -- xdm.source.* (attacker)
    xdm.source.ipv4 = _client_ip,
    xdm.source.location.country = _country,
    xdm.source.user.username = _request_user,

    // XDM Target fields -- xdm.target.* (victim / protected resource)
    xdm.target.ipv4 = _client_ip,
    xdm.target.user.username = _request_user,
    xdm.target.host.hostname = _site_name,
    xdm.target.url = _path,

    // XDM Network fields -- xdm.network.*
    xdm.network.http.browser = _declared_client,
    xdm.network.http.referrer = _referrer;
