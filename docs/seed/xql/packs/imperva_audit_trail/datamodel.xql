// Imperva Audit Trail -- XDM Data Model Rule
// Dataset: imperva_audittrail_raw
// Vendor: Imperva | Product: Cloud Application Security
//
// Maps Imperva Audit Trail SIEM events to the Cortex XDM schema.
// Records administrative actions on the Imperva console (sites, users,
// SSL, policy, login, system jobs).
//
// Documentation: imperva_audit_trail_xdm_model_rule_documentation.md
//
// SPDX-FileCopyrightText: GoCortexIO
// SPDX-License-Identifier: AGPL-3.0-or-later

[MODEL: dataset = imperva_audittrail_raw]

// -- Stage 1: Extract all fields from parsed columns ------------------------
alter
    _event_action = json_extract_scalar(to_string(imperva), "$.audit_trail.event_action"),
    _event_action_description = json_extract_scalar(to_string(imperva), "$.audit_trail.event_action_description"),
    _assumed_by = json_extract_scalar(to_string(imperva), "$.audit_trail.assumed_by"),
    // Keep-in-both anchor: parser.xql stamps `_resource_type` at ingest
    // with the same JSON-path extraction. Parser-stamped rows
    // short-circuit through the column read; legacy / replayed /
    // backfilled rows fall through to the json_extract_scalar() below.
    // Vocabulary: ~8 closed values (Site, User, Policy, SSL, Account,
    // Rule, System) plus NULL on system-initiated rows.
    _resource_type = coalesce(_resource_type, json_extract_scalar(to_string(imperva), "$.audit_trail.resource_type")),
    _resource_id = json_extract_scalar(to_string(imperva), "$.audit_trail.resource_id"),
    _resource_name = json_extract_scalar(to_string(imperva), "$.audit_trail.resource_name"),
    _event_context = json_extract_scalar(to_string(imperva), "$.audit_trail.event_context"),
    _event_context_description = json_extract_scalar(to_string(imperva), "$.audit_trail.event_context_description"),
    _account_id = json_extract_scalar(to_string(imperva), "$.ids.account_id"),
    _account_name = json_extract_scalar(to_string(imperva), "$.ids.account_name"),
    _site_id = json_extract_scalar(to_string(imperva), "$.ids.site_id"),
    _user_email = json_extract_scalar(to_string(user), "$.email")

// -- Stage 2: Derive `_action_class` anchor (prefix of event_action) -------
//
// Keep-in-both anchor: parser.xql stamps `_action_class` at ingest by
// taking arrayindex(split(event_action, "_"), 0). Parser-stamped rows
// short-circuit through the column read; legacy / replayed /
// backfilled rows fall through to the freshly-derived prefix
// expression below (NOT to the raw `_event_action`). Vocabulary:
// ~7 closed values (SITE, USER, SSL, POLICY, LOGIN, ACCOUNT, SYSTEM).
// Folded into `_description` so analysts see the class alongside the
// human-readable action summary.
| alter
    _action_class = coalesce(_action_class, if(_event_action != null, arrayindex(split(_event_action, "_"), 0)))

// -- Stage 3: Build description summary string ------------------------------
| alter
    _description = concat(
        coalesce(_event_action_description, _event_action, "Unknown action"),
        if(_action_class != null, concat(" | Class: ", _action_class), ""),
        " | Context: ", coalesce(_event_context_description, _event_context, "unknown"),
        if(_assumed_by != null, concat(" | Assumed by: ", _assumed_by), ""),
        " | Account: ", coalesce(_account_name, _account_id, "unknown"),
        if(_site_id != null, concat(" | Site ID: ", _site_id), ""))

// -- Stage 4: Map to XDM fields --------------------------------------------
| alter
    // XDM Observer fields -- xdm.observer.*
    xdm.observer.vendor = "Imperva",
    xdm.observer.product = "Cloud Application Security",

    // XDM Event fields -- xdm.event.*
    xdm.event.type = "AUDIT",
    xdm.event.description = _description,
    xdm.event.original_event_type = _event_action,
    xdm.event.operation_sub_type = _event_action,
    xdm.event.operation = if(
        _event_action contains "LOGIN" or _event_action contains "SIGN_IN" or _event_action contains "LOGGED_IN" or _event_action contains "LOGGED_OUT", XDM_CONST.OPERATION_TYPE_AUTH_LOGIN,
        _event_action contains "TWO_FACTOR" or _event_action contains "AUTHENTICAT", XDM_CONST.OPERATION_TYPE_AUTH_MFA,
        _event_action contains "CREAT" or _event_action contains "_ADD" or _event_action contains "SIGNUP" or _event_action contains "UPLOAD", XDM_CONST.OPERATION_TYPE_CREATE,
        _event_action contains "REMOV" or _event_action contains "DELET" or _event_action contains "PURG", XDM_CONST.OPERATION_TYPE_DELETE,
        _event_action contains "UPDAT" or _event_action contains "CHANG" or _event_action contains "EDIT" or _event_action contains "RESET", XDM_CONST.OPERATION_TYPE_UPDATE,
        _event_action contains "CONFIG" or _event_action contains "SETTING", XDM_CONST.OPERATION_TYPE_CONFIG_CHANGE,
        _event_action contains "ENABL" or _event_action contains "DISABL" or _event_action contains "LOCK" or _event_action contains "ACTIV", XDM_CONST.OPERATION_TYPE_STATUS_CHANGE,
        XDM_CONST.OPERATION_TYPE_AUDIT),

    // XDM Source fields -- xdm.source.* (who performed the action)
    xdm.source.user.username = _user_email,

    // XDM Target Resource fields -- xdm.target.resource.* (what was acted upon)
    xdm.target.resource.type = _resource_type,
    xdm.target.resource.name = _resource_name,
    xdm.target.resource.id = _resource_id,
    xdm.target.resource.parent_id = _account_id,

    // XDM Target Host -- resource_name is an FQDN when resource_type is "Site"
    xdm.target.host.hostname = if(_resource_type = "Site", _resource_name),

    // XDM Target User -- mirrored from source (only one user in payload)
    xdm.target.user.username = _user_email;
