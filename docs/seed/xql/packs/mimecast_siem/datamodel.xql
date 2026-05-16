// Mimecast Secure Email Gateway -- XDM Data Model Rule
// Dataset: mimecast_siem_raw
// Vendor: Mimecast | Product: Secure Email Gateway
//
// Maps Mimecast SIEM events (receipt, process, delivery, url protect,
// attachment protect) to the Cortex XDM schema.
//
// Documentation: mimecast_siem_xdm_model_rule_documentation.md
//
// SPDX-FileCopyrightText: GoCortexIO
// SPDX-License-Identifier: AGPL-3.0-or-later

[MODEL: dataset=mimecast_siem_raw]
filter eventType != null

// -- Stage 1: Normalise common fields across event types -------------------
| alter
    _sender_ip = coalesce(senderIp, SourceIP),
    _recipient = coalesce(recipients, Recipient),
    _sender_addr = coalesce(senderEnvelope, senderHeader),
    _sender_domain = SenderDomain,
    _outcome_reason = coalesce(blockReason, holdReason, rejectionType, rejectionInfo),
    // Keep-in-both anchor: parser.xql stamps `_event_type` at ingest
    // from the top-level `eventType` column. Parser-stamped rows
    // short-circuit through the column read; legacy / replayed /
    // backfilled rows fall through to the raw column. Vocabulary:
    // ~6 closed values (receipt, process, delivery, url_protect,
    // attachment_protect, journal). Sunk into
    // `xdm.event.original_event_type` below as the first coalesce arm.
    _event_type = coalesce(_event_type, eventType),
    // Keep-in-both anchor: parser.xql stamps `_outcome` at ingest
    // from `coalesce(action, status, deliveryStatus)`. Parser-stamped
    // rows short-circuit; legacy rows fall through to the same
    // coalesce. Vocabulary: ~6 closed values (Allow, Hold, Block,
    // Bounce, Defer, Reject). Sunk into `xdm.event.outcome_reason`
    // below as a back-stop arm so the more specific free-text
    // reasons (`blockReason`, `holdReason`, `rejectionType`,
    // `rejectionInfo`) win when present.
    _outcome = coalesce(_outcome, action, status, deliveryStatus)

// -- Stage 2: Map to XDM fields --------------------------------------------
| alter
    // Observer -- Mimecast as the email security gateway
    xdm.observer.vendor = "Mimecast",
    xdm.observer.product = "Secure Email Gateway",

    // Event -- email processing event metadata
    xdm.event.type = "EMAIL",
    xdm.event.id = coalesce(processingId, id),
    xdm.event.original_event_type = coalesce(_event_type, eventType),
    xdm.event.description = concat(
        "Mimecast ", eventType,
        if(direction != null, concat(" (", direction, ")"), ""),
        if(Subject != null, concat(" | Subject: ", Subject), ""),
        if(Action != null, concat(" | Action: ", Action), ""),
        if(_recipient != null, concat(" | To: ", _recipient), ""),
        if(_sender_addr != null, concat(" | From: ", _sender_addr), "")),
    xdm.event.outcome = if(
        Action = "Acc", XDM_CONST.OUTCOME_SUCCESS,
        Action = "Block" or Action = "Rej" or Action = "Bnc", XDM_CONST.OUTCOME_FAILED,
        Action = "Hld", XDM_CONST.OUTCOME_PARTIAL,
        eventType = "delivery" and Delivered = "true", XDM_CONST.OUTCOME_SUCCESS,
        eventType = "delivery" and Delivered = "false", XDM_CONST.OUTCOME_FAILED,
        XDM_CONST.OUTCOME_UNKNOWN),
    xdm.event.outcome_reason = coalesce(_outcome_reason, _outcome),

    // Email -- message metadata
    xdm.email.sender = coalesce(senderHeader, senderEnvelope),
    xdm.email.recipients = if(_recipient != null, arraycreate(_recipient), null),
    xdm.email.subject = Subject,
    xdm.email.message_id = messageId,
    xdm.email.return_path = senderEnvelope,
    xdm.email.attachment.filename = fileName,
    xdm.email.attachment.md5 = md5,
    xdm.email.attachment.sha256 = sha256,

    // Source -- the sender of the email
    xdm.source.ipv4 = _sender_ip,
    xdm.source.user.username = _sender_addr,
    xdm.source.host.hostname = _sender_domain,

    // Target -- the recipient or suspicious destination
    xdm.target.ipv4 = destinationIp,
    xdm.target.url = url,
    xdm.target.user.username = _recipient,

    // Network -- TLS details from receipt events
    xdm.network.tls.protocol_version = tlsVersion,
    xdm.network.tls.cipher = tlsCipher,

    // Alert -- threat protection details (url protect / attachment protect)
    xdm.alert.name = coalesce(urlCategory, blockReason),
    xdm.alert.description = coalesce(virusFound, ScanResultInfo),

    // Intermediate -- the Mimecast infrastructure
    xdm.intermediate.host.hostname = Hostname,
    xdm.intermediate.ipv4 = _reporting_device_ip;
