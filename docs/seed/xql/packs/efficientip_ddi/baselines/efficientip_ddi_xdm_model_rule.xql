// EfficientIP DDI -- XDM Data Model Rule
// Dataset: efficientip_raw
// Vendor: EfficientIP | Product: SOLIDserver DDI
//
// Maps EfficientIP DDI appliance syslog events to the Cortex XDM
// schema. The appliance ships syslog from four daemons in two
// envelope shapes:
//   1. RFC 3164:           <PRI>MMM DD HH:MM:SS [HOST] daemon[PID]: BODY
//   2. RFC 5424-in-kernel: <PRI>MMM DD HH:MM:SS kernel: ISO_TS HOST daemon PID - - BODY
//      (the appliance forwards a minimal RFC 5424 record wrapped
//      inside an RFC 3164 envelope; the two `- -` tokens are the
//      RFC 5424 NILVALUE placeholders for MSGID and STRUCTURED-DATA)
//
// File structure -- one [RULE:] + one [MODEL:] + four pipelines.
// Cortex permits exactly one [MODEL: dataset = efficientip_raw] per
// (dataset, model) tuple per file; the four daemon-specific
// pipelines below all live INSIDE that single MODEL block, each
// terminated by its own `;`. Putting four `[MODEL: dataset = ...]`
// headers in one file (which earlier drafts of this rule did) is
// rejected by the Cortex content engine and is now caught at
// write-time by analyser rule ERR-026.
//
// Both envelope shapes feed the same shared header rule
// `efficientip_syslog_header`, which extracts the syslog header
// fields (priority/facility/severity/host/pid/proc/msg) once and
// is `call`-ed by every daemon pipeline. This avoids duplicating
// ~20 lines of header parsing in every pipeline and means a
// future envelope shape is a one-rule change, not a four-pipeline
// rewrite. The Pattern-10 RULE/CALL discussion in
// PRIVATE_DOCS/data_model_rule_building_guide.md uses this rule as
// its worked example.
//
// Daemons (one ;-terminated pipeline each):
//   - named  (BIND DNS server)  -> xdm.network.dns.*
//   - dhcpd  (ISC DHCP server)  -> xdm.network.dhcp.*
//   - sshd   (operator login)   -> xdm.event.* / xdm.source.user.*
//   - sudo   (privileged ops)   -> xdm.target.user.* / process.*
//
// FreeBSD devd[] events, ipmserver[] internal RPC, and kernel:
// ipfw chatter are dropped by the allow-list filter at the head
// of the shared header rule before any pipeline body is reached.
//
// Documentation: PRIVATE_DOCS/packs/efficientip_ddi/documentation.md
//
// SPDX-FileCopyrightText: GoCortexIO
// SPDX-License-Identifier: AGPL-3.0-or-later

// =========================================================================
// Shared header rule -- handles both syslog envelope shapes
// =========================================================================
//
// `call efficientip_syslog_header` is the first stage of every MODEL
// stanza below. The rule produces:
//   _syslog_priority, _syslog_facility, _syslog_severity (numeric)
//   _syslog_host, _syslog_pid, _syslog_proc, _syslog_msg (string)
// and drops any line that is not from one of the four supported
// daemons in either envelope shape.

[RULE: efficientip_syslog_header]

// Allow-list filter: keep only lines from the four supported daemons
// in either the RFC 3164 (`daemon[pid]:`) or RFC 5424-in-kernel
// (`kernel: ISO HOST daemon PID - -`) envelope. Everything else
// (devd[], ipmserver[], kernel: ipfw, raw kernel messages) is
// dropped here so no MODEL stanza body has to defend against it.
filter _raw_log ~= "(\s(named|dhcpd|sshd|sudo)\[\d+\]:|\skernel:\s+\S+\s+\S+\s+(named|dhcpd|sshd|sudo)\s+\d+\s+-\s+-\s)"

// Header extraction. Each capture has a primary regex for the
// RFC 3164 shape and a coalesce fallback for the RFC 5424-in-kernel
// shape so a single set of intermediates feeds both envelopes.
//
// `_syslog_priority` and `_syslog_proc` additionally use the
// keep-in-both anchor convention from
// `PRIVATE_DOCS/anchor_field_design.md`: they coalesce the
// parser-stamped column written by `parser.xql` first, then fall
// back to the regex(es) over `_raw_log` for any row ingested before
// the parser shipped (or any sample replayed through XQL). On
// parser-stamped rows the fallback short-circuits to one column
// read; on un-stamped rows the same regex the rule has always run
// is evaluated.
| alter
    _syslog_priority = coalesce(
        _syslog_priority,
        to_integer(arrayindex(regextract(_raw_log, "^<(\d{1,3})>"), 0))),
    _syslog_proc = coalesce(
        _syslog_proc,
        arrayindex(regextract(_raw_log, "\s(named|dhcpd|sshd|sudo)\[\d+\]:"), 0),
        arrayindex(regextract(_raw_log, "\skernel:\s+\S+\s+\S+\s+(named|dhcpd|sshd|sudo)\s+\d+\s+-\s+-"), 0)),
    _syslog_pid = coalesce(
        arrayindex(regextract(_raw_log, "\s(?:named|dhcpd|sshd|sudo)\[(\d+)\]:"), 0),
        arrayindex(regextract(_raw_log, "\skernel:\s+\S+\s+\S+\s+(?:named|dhcpd|sshd|sudo)\s+(\d+)\s+-\s+-"), 0)),
    _syslog_host = coalesce(
        arrayindex(regextract(_raw_log, "^<\d+>\w+\s+\d+\s+\d+:\d+:\d+\s+(\S+)\s+(?:named|dhcpd|sshd|sudo)\["), 0),
        arrayindex(regextract(_raw_log, "\skernel:\s+\S+\s+(\S+)\s+(?:named|dhcpd|sshd|sudo)\s+\d+\s+-\s+-"), 0)),
    _syslog_msg = coalesce(
        arrayindex(regextract(_raw_log, "(?:named|dhcpd|sshd|sudo)\[\d+\]:\s*(.+)$"), 0),
        arrayindex(regextract(_raw_log, "(?:named|dhcpd|sshd|sudo)\s+\d+\s+-\s+-\s+(.+)$"), 0))

| alter
    _syslog_facility = floor(divide(_syslog_priority, 8))

| alter
    _syslog_severity = subtract(_syslog_priority, multiply(_syslog_facility, 8));


// =========================================================================
// Stanza 1 -- BIND named events (query, answer, update, transfer,
//             notify, lame server, rate limit)
// =========================================================================

[MODEL: dataset = efficientip_raw]

call efficientip_syslog_header
| filter _syslog_proc = "named"

// -- Stage 2: BIND line-shape discriminator ---------------------------------
// BIND named emits >=11 distinct syslog body shapes. The discriminator
// drives operation_sub_type and lets the field-extraction stage cope
// with each shape without one shape's null capture poisoning another's
// XDM mapping (the bug that crashed the prior version of this rule:
// see Drift in the documentation).
| alter
    _dns_action = if(
        _syslog_msg ~= "^client\b.+:\s+query:", "QUERY",
        _syslog_msg ~= "^client\b.+:\s+answer:", "ANSWER",
        _syslog_msg ~= "^client\b.+:\s+updating zone\s+'[^']+':\s+adding", "UPDATE_ADD",
        _syslog_msg ~= "^client\b.+:\s+updating zone\s+'[^']+':\s+deleting", "UPDATE_DELETE",
        _syslog_msg ~= "^client\b.+:\s+update\s+'[^']+'\s+denied", "UPDATE_DENIED",
        _syslog_msg ~= "^client\b.+:\s+transfer of\s+'[^']+':\s+IXFR", "IXFR",
        _syslog_msg ~= "^client\b.+:\s+transfer of\s+'[^']+':\s+AXFR", "AXFR",
        _syslog_msg ~= "^client\b.+:\s+would rate limit", "RATELIMIT",
        _syslog_msg ~= "^zone\s+\S+:\s+transferred serial", "XFER_DONE",
        _syslog_msg ~= "^zone\s+\S+:\s+sending notifies", "NOTIFY",
        _syslog_msg ~= "^lame server resolving", "LAME",
        "OTHER")

// -- Stage 3: Per-shape body extraction -------------------------------------
// Client pair (IP / port) is shared by query, answer, update*,
// transfer*, ratelimit, and denied lines. BIND named query logs do
// not contain a reverse-resolved client hostname; the parenthesised
// token before the shape verb is the QNAME, which is captured
// separately as _query_name and mapped to
// xdm.network.dns.dns_question.name. xdm.source.host.hostname is
// therefore left unset for BIND events.
| alter
    _client_ip = arrayindex(regextract(_syslog_msg, "client\s+(?:@0x[\da-fA-F]+\s+)?([\da-fA-F.:]+)#\d+"), 0),
    _client_port = arrayindex(regextract(_syslog_msg, "client\s+(?:@0x[\da-fA-F]+\s+)?[\da-fA-F.:]+#(\d+)"), 0),

// Question-section captures unify across query/answer/ratelimit/update*/
// denied/lame so the same _query_* intermediates feed
// xdm.network.dns.dns_question.* without per-shape duplication.
    _query_name = coalesce(
        arrayindex(regextract(_syslog_msg, "(?:query|answer):\s+(\S+)\s"), 0),
        arrayindex(regextract(_syslog_msg, "would rate limit\s+(?:slip|drop)\s+(?:NXDOMAIN\s+)?response\s+to\s+\S+\s+for\s+(\S+)\s"), 0),
        arrayindex(regextract(_syslog_msg, "updating zone\s+'[^']+':\s+(?:adding|deleting)\s+an?\s+RR\s+at\s+'([^']+)'"), 0),
        arrayindex(regextract(_syslog_msg, "update\s+'([^']+?)/(?:IN|CS|CH|HS)'\s+denied"), 0),
        arrayindex(regextract(_syslog_msg, "lame server resolving\s+'([^']+)'"), 0)),
    _query_class = coalesce(
        arrayindex(regextract(_syslog_msg, "(?:query|answer):\s+\S+\s+(IN|CS|CH|HS)\s"), 0),
        arrayindex(regextract(_syslog_msg, "would rate limit.+\s+for\s+\S+\s+(IN|CS|CH|HS)\s"), 0),
        arrayindex(regextract(_syslog_msg, "(?:zone|of|update)\s+'[^']+/(IN|CS|CH|HS)'"), 0)),
    _query_record_type = coalesce(
        arrayindex(regextract(_syslog_msg, "(?:query|answer):\s+\S+\s+(?:IN|CS|CH|HS)\s+([A-Z][A-Z0-9-]*)"), 0),
        arrayindex(regextract(_syslog_msg, "would rate limit.+\s+(?:IN|CS|CH|HS)\s+([A-Z][A-Z0-9-]*)"), 0),
        arrayindex(regextract(_syslog_msg, "updating zone\s+'[^']+':\s+(?:adding|deleting)\s+an?\s+RR\s+at\s+'[^']+'\s+([A-Z][A-Z0-9-]*)"), 0)),
    _query_flags = arrayindex(regextract(_syslog_msg, "(?:query|answer):\s+\S+\s+(?:IN|CS|CH|HS)\s+[A-Z][A-Z0-9-]*\s+([+-][SETDC()0-9]*)"), 0),

// Listener IP regex now requires a dot or a colon so the BIND internal
// hash token at the end of "would rate limit ... (138956d9)" lines is
// excluded -- it is a 32-bit hash, not an IP literal.
    _dns_listener_ip = arrayindex(regextract(_syslog_msg, "\((\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}|[\da-fA-F]*:[\da-fA-F:]+)\)\s*$"), 0),

// Response code: real DNS rcode mnemonic comes after the "->" in answer
// lines; the rate-limit "NXDOMAIN response" wording carries the same
// semantic for the suppressed response and is captured as a fallback.
    _rcode = coalesce(
        arrayindex(regextract(_syslog_msg, "->\s*(NOERROR|FORMERR|SERVFAIL|NXDOMAIN|NOTIMP|REFUSED|YXDOMAIN|YXRRSET|NXRRSET|NOTAUTH|NOTZONE|BADVERS|BADSIG|BADKEY|BADTIME|BADMODE|BADNAME|BADALG|BADTRUNC)\b"), 0),
        arrayindex(regextract(_syslog_msg, "would rate limit\s+\S+\s+(NXDOMAIN)\s+response"), 0)),

// Zone name carried by update/transfer/notify/xfer_done/lame lines.
    _dns_zone = coalesce(
        arrayindex(regextract(_syslog_msg, "(?:updating zone|transfer of)\s+'([^']+?)/(?:IN|CS|CH|HS)'"), 0),
        arrayindex(regextract(_syslog_msg, "^zone\s+(\S+?)/(?:IN|CS|CH|HS):"), 0),
        arrayindex(regextract(_syslog_msg, "lame server resolving\s+'[^']+'\s+\(in\s+'([^']+)'"), 0)),

// Lame-server diagnostic IP / port (the upstream resolver reported as
// lame). Routed to xdm.intermediate.* alongside _dns_listener_ip.
    _dns_diag_ip = arrayindex(regextract(_syslog_msg, "lame server resolving.+:\s+([\da-fA-F.:]+)#\d+"), 0),
    _dns_diag_port = arrayindex(regextract(_syslog_msg, "lame server resolving.+:\s+[\da-fA-F.:]+#(\d+)"), 0),

// Rate-limit verb (slip|drop) -> outcome_reason; subnet captured for
// description enrichment but no XDM destination available.
//
// Note: zone-transfer and notify serial numbers carried by XFER_DONE
// and NOTIFY lines (e.g. "transferred serial 18121600",
// "sending notifies (serial 2150543647)") are intentionally not
// extracted to dedicated intermediates -- there is no obvious XDM
// destination for them and the verbatim values are preserved in
// xdm.event.description (the full syslog body).
    _dns_ratelimit_verb = arrayindex(regextract(_syslog_msg, "would rate limit\s+(slip|drop)"), 0)

// -- Stage 4: Route IPs by family -------------------------------------------
| alter
    _client_ipv4 = if(is_ipv4(_client_ip), _client_ip, null),
    _client_ipv6 = if(is_ipv6(_client_ip), _client_ip, null),
    _dns_listener_ipv4 = if(is_ipv4(_dns_listener_ip), _dns_listener_ip, null),
    _dns_listener_ipv6 = if(is_ipv6(_dns_listener_ip), _dns_listener_ip, null),
    _dns_diag_ipv4 = if(is_ipv4(_dns_diag_ip), _dns_diag_ip, null),
    _dns_diag_ipv6 = if(is_ipv6(_dns_diag_ip), _dns_diag_ip, null)

// -- Stage 5: XDM mapping ---------------------------------------------------
// CRITICAL null-guard convention: every arraycreate(...) call wraps any
// non-literal element in an explicit `if(... != null, arraycreate(...))`
// or a "literal-only fallback" form. Cortex discards the entire
// enclosing alter (so xdm.event.type is also dropped) when arraycreate
// produces an array<string> with a null element -- the local analyser
// does not catch this. See documentation Drift section.
| alter
    xdm.observer.vendor = "EfficientIP",
    xdm.observer.product = "SOLIDserver DDI",
    xdm.observer.name = _syslog_host,

    xdm.event.type = "DNS",
    xdm.event.description = _syslog_msg,
    xdm.event.operation_sub_type = if(_dns_action != "OTHER", _dns_action),
    xdm.event.log_level = if(
        _syslog_severity = 0, XDM_CONST.LOG_LEVEL_EMERGENCY,
        _syslog_severity = 1, XDM_CONST.LOG_LEVEL_ALERT,
        _syslog_severity = 2, XDM_CONST.LOG_LEVEL_CRITICAL,
        _syslog_severity = 3, XDM_CONST.LOG_LEVEL_ERROR,
        _syslog_severity = 4, XDM_CONST.LOG_LEVEL_WARNING,
        _syslog_severity = 5, XDM_CONST.LOG_LEVEL_NOTICE,
        _syslog_severity = 6, XDM_CONST.LOG_LEVEL_INFORMATIONAL,
        _syslog_severity = 7, XDM_CONST.LOG_LEVEL_DEBUG),
    xdm.event.outcome = if(
        _dns_action = "UPDATE_DENIED", XDM_CONST.OUTCOME_FAILED,
        _dns_action = "RATELIMIT", XDM_CONST.OUTCOME_FAILED,
        _dns_action = "LAME", XDM_CONST.OUTCOME_FAILED,
        _rcode != null and _rcode = "NOERROR", XDM_CONST.OUTCOME_SUCCESS,
        _rcode != null, XDM_CONST.OUTCOME_FAILED),
// outcome_reason precedence: UPDATE_DENIED -> "denied"; RATELIMIT
// always carries the slip|drop verb (even when the line also names
// an NXDOMAIN response, because slip/drop is the operationally
// useful reason -- the rcode is still preserved on
// xdm.network.dns.response_code below); everything else falls
// through to the rcode mnemonic for ANSWER lines.
    xdm.event.outcome_reason = coalesce(
        if(_dns_action = "UPDATE_DENIED", "denied"),
        if(_dns_action = "RATELIMIT" and _dns_ratelimit_verb != null, _dns_ratelimit_verb),
        _rcode,
        _dns_ratelimit_verb),

    xdm.network.application_protocol = "DNS",
    // Null-guarded: only the two-element "DNS" + transport array is built
    // when query flags identified the transport; otherwise the array
    // contains only "DNS". Building arraycreate("DNS", null) crashes the
    // alter on Cortex (analyser does not detect this).
    xdm.network.protocol_layers = if(
        _query_flags != null,
        arraycreate("DNS", if(_query_flags ~= "T", "TCP", "UDP")),
        arraycreate("DNS")),
    xdm.network.ip_protocol = if(
        _query_flags != null and _query_flags ~= "T", XDM_CONST.IP_PROTOCOL_TCP,
        _query_flags != null, XDM_CONST.IP_PROTOCOL_UDP),
    xdm.network.dns.dns_question.name = _query_name,
    xdm.network.dns.dns_resource_record.class = if(
        _query_class = "IN", 1,
        _query_class = "CS", 2,
        _query_class = "CH", 3,
        _query_class = "HS", 4),
    xdm.network.dns.dns_question.type = if(
        _query_record_type = "A", XDM_CONST.DNS_RECORD_TYPE_A,
        _query_record_type = "AAAA", XDM_CONST.DNS_RECORD_TYPE_AAAA,
        _query_record_type = "AFSDB", XDM_CONST.DNS_RECORD_TYPE_AFSDB,
        _query_record_type = "APL", XDM_CONST.DNS_RECORD_TYPE_APL,
        _query_record_type = "CAA", XDM_CONST.DNS_RECORD_TYPE_CAA,
        _query_record_type = "CDNSKEY", XDM_CONST.DNS_RECORD_TYPE_CDNSKEY,
        _query_record_type = "CDS", XDM_CONST.DNS_RECORD_TYPE_CDS,
        _query_record_type = "CERT", XDM_CONST.DNS_RECORD_TYPE_CERT,
        _query_record_type = "CNAME", XDM_CONST.DNS_RECORD_TYPE_CNAME,
        _query_record_type = "CSYNC", XDM_CONST.DNS_RECORD_TYPE_CSYNC,
        _query_record_type = "DHCID", XDM_CONST.DNS_RECORD_TYPE_DHCID,
        _query_record_type = "DLV", XDM_CONST.DNS_RECORD_TYPE_DLV,
        _query_record_type = "DNAME", XDM_CONST.DNS_RECORD_TYPE_DNAME,
        _query_record_type = "DNSKEY", XDM_CONST.DNS_RECORD_TYPE_DNSKEY,
        _query_record_type = "DS", XDM_CONST.DNS_RECORD_TYPE_DS,
        _query_record_type = "EUI48", XDM_CONST.DNS_RECORD_TYPE_EUI48,
        _query_record_type = "EUI64", XDM_CONST.DNS_RECORD_TYPE_EUI64,
        _query_record_type = "HINFO", XDM_CONST.DNS_RECORD_TYPE_HINFO,
        _query_record_type = "HIP", XDM_CONST.DNS_RECORD_TYPE_HIP,
        _query_record_type = "HTTPS", XDM_CONST.DNS_RECORD_TYPE_HTTPS,
        _query_record_type = "IPSECKEY", XDM_CONST.DNS_RECORD_TYPE_IPSECKEY,
        _query_record_type = "KEY", XDM_CONST.DNS_RECORD_TYPE_KEY,
        _query_record_type = "KX", XDM_CONST.DNS_RECORD_TYPE_KX,
        _query_record_type = "LOC", XDM_CONST.DNS_RECORD_TYPE_LOC,
        _query_record_type = "MX", XDM_CONST.DNS_RECORD_TYPE_MX,
        _query_record_type = "NAPTR", XDM_CONST.DNS_RECORD_TYPE_NAPTR,
        _query_record_type = "NS", XDM_CONST.DNS_RECORD_TYPE_NS,
        _query_record_type = "NSEC", XDM_CONST.DNS_RECORD_TYPE_NSEC,
        _query_record_type = "NSEC3", XDM_CONST.DNS_RECORD_TYPE_NSEC3,
        _query_record_type = "NSEC3PARAM", XDM_CONST.DNS_RECORD_TYPE_NSEC3PARAM,
        _query_record_type = "OPENPGPKEY", XDM_CONST.DNS_RECORD_TYPE_OPENPGPKEY,
        _query_record_type = "PTR", XDM_CONST.DNS_RECORD_TYPE_PTR,
        _query_record_type = "RP", XDM_CONST.DNS_RECORD_TYPE_RP,
        _query_record_type = "RRSIG", XDM_CONST.DNS_RECORD_TYPE_RRSIG,
        _query_record_type = "SIG", XDM_CONST.DNS_RECORD_TYPE_SIG,
        _query_record_type = "SMIMEA", XDM_CONST.DNS_RECORD_TYPE_SMIMEA,
        _query_record_type = "SOA", XDM_CONST.DNS_RECORD_TYPE_SOA,
        _query_record_type = "SRV", XDM_CONST.DNS_RECORD_TYPE_SRV,
        _query_record_type = "SSHFP", XDM_CONST.DNS_RECORD_TYPE_SSHFP,
        _query_record_type = "SVCB", XDM_CONST.DNS_RECORD_TYPE_SVCB,
        _query_record_type = "TA", XDM_CONST.DNS_RECORD_TYPE_TA,
        _query_record_type = "TKEY", XDM_CONST.DNS_RECORD_TYPE_TKEY,
        _query_record_type = "TLSA", XDM_CONST.DNS_RECORD_TYPE_TLSA,
        _query_record_type = "TSIG", XDM_CONST.DNS_RECORD_TYPE_TSIG,
        _query_record_type = "TXT", XDM_CONST.DNS_RECORD_TYPE_TXT,
        _query_record_type = "URI", XDM_CONST.DNS_RECORD_TYPE_URI,
        _query_record_type = "ZONEMD", XDM_CONST.DNS_RECORD_TYPE_ZONEMD),
    xdm.network.dns.is_response = if(
        _dns_action = "ANSWER", to_boolean("TRUE"),
        _dns_action = "QUERY", to_boolean("FALSE"),
        _rcode != null, to_boolean("TRUE"),
        to_boolean("FALSE")),
    // BIND omits the opcode token for the default QUERY opcode (0).
    // UPDATE* shapes carry opcode 5 (RFC 2136); NOTIFY carries opcode 4.
    xdm.network.dns.opcode = if(
        _dns_action in ("QUERY", "ANSWER"), 0,
        _dns_action in ("UPDATE_ADD", "UPDATE_DELETE", "UPDATE_DENIED"), 5,
        _dns_action = "NOTIFY", 4),
    xdm.network.dns.response_code = if(
        _rcode = "NOERROR", XDM_CONST.DNS_RESPONSE_CODE_NO_ERROR,
        _rcode = "FORMERR", XDM_CONST.DNS_RESPONSE_CODE_FORMAT_ERROR,
        _rcode = "SERVFAIL", XDM_CONST.DNS_RESPONSE_CODE_SERVER_FAILURE,
        _rcode = "NXDOMAIN", XDM_CONST.DNS_RESPONSE_CODE_NON_EXISTENT_DOMAIN,
        _rcode = "NOTIMP", XDM_CONST.DNS_RESPONSE_CODE_NOT_IMPLEMENTED,
        _rcode = "REFUSED", XDM_CONST.DNS_RESPONSE_CODE_QUERY_REFUSED,
        _rcode = "YXDOMAIN", XDM_CONST.DNS_RESPONSE_CODE_NAME_EXISTS_WHEN_IT_SHOULD_NOT,
        _rcode = "YXRRSET", XDM_CONST.DNS_RESPONSE_CODE_RR_SET_EXISTS_WHEN_IT_SHOULD_NOT,
        _rcode = "NXRRSET", XDM_CONST.DNS_RESPONSE_CODE_RR_SET_THAT_SHOULD_EXIST_DOES_NOT,
        _rcode = "NOTAUTH", XDM_CONST.DNS_RESPONSE_CODE_SERVER_NOT_AUTHORITATIVE_FOR_ZONE,
        _rcode = "NOTZONE", XDM_CONST.DNS_RESPONSE_CODE_NAME_NOT_CONTAINED_IN_ZONE,
        _rcode = "BADVERS", XDM_CONST.DNS_RESPONSE_CODE_BAD_OPT_VERSION,
        _rcode = "BADSIG", XDM_CONST.DNS_RESPONSE_CODE_TSIG_SIGNATURE_FAILURE,
        _rcode = "BADKEY", XDM_CONST.DNS_RESPONSE_CODE_KEY_NOT_RECOGNIZED,
        _rcode = "BADTIME", XDM_CONST.DNS_RESPONSE_CODE_SIGNATURE_OUT_OF_TIME_WINDOW,
        _rcode = "BADMODE", XDM_CONST.DNS_RESPONSE_CODE_BAD_TKEY_MODE,
        _rcode = "BADNAME", XDM_CONST.DNS_RESPONSE_CODE_DUPLICATE_KEY_NAME,
        _rcode = "BADALG", XDM_CONST.DNS_RESPONSE_CODE_ALGORITHM_NOT_SUPPORTED,
        _rcode = "BADTRUNC", XDM_CONST.DNS_RESPONSE_CODE_BAD_TRUNCATION),

    xdm.source.ipv4 = _client_ipv4,
    xdm.source.ipv6 = _client_ipv6,
    xdm.source.port = to_integer(_client_port),
    xdm.source.process.name = _syslog_proc,
    xdm.source.process.pid = to_integer(_syslog_pid),

    // Zone name (UPDATE / TRANSFER / XFER_DONE / NOTIFY / LAME shapes)
    // surfaces as the resource the operation acted on.
    xdm.target.resource.name = _dns_zone,

    // Listener IP from query/answer lines plus lame-resolver IP from
    // LAME shapes both belong on the intermediate-hop fields.
    xdm.intermediate.ipv4 = coalesce(_dns_listener_ipv4, _dns_diag_ipv4),
    xdm.intermediate.ipv6 = coalesce(_dns_listener_ipv6, _dns_diag_ipv6),
    xdm.intermediate.port = to_integer(_dns_diag_port);


// =========================================================================
// Pipeline 2 -- ISC dhcpd lease lifecycle
// =========================================================================
// Second `;`-terminated pipeline inside the single
// [MODEL: dataset = efficientip_raw] block opened above.

call efficientip_syslog_header
| filter _syslog_proc = "dhcpd"

// -- Stage 2: Suppress DHCP appliance noise ---------------------------------
// Single anchored alternation that supersedes the original 30-line cluster
// of single-pattern `filter not` rules. Three logical groups: lease
// housekeeping, transport chatter, and server admin / startup banners.
// Word boundaries (\b...\b) on the broader admin words prevent over-suppression
// of lines that legitimately contain the same substring inside a hostname or
// vendor/feature label.
//
// Note: `\bkernel:\s` was previously in this alternation to drop
// dhcpd[X]: kernel: ... lines. With the RFC 5424-in-kernel envelope
// support, every kernel-wrapped DHCP line legitimately contains
// "kernel: " as the outer process tag; the suppression pattern was
// removed so those lines now reach the DHCP body extractions.
| filter not _raw_log ~= "(balanc(?:ing|ed) pool|scrubbing lease|abandoning IP |my (?:backup|free) count|lease .+ changed|last message .+? repeated|(?:uid_|hw_|uid )lease |\bbind update\b|\bsqlite3\b|\bBPF\b|bad udp checksum|(?:send|listen)ing on|interface [^ ]+ is attached|Internet Systems Consortium|https:|\bConfig file\b|dhcpd\.conf file|\bPWD\b|ignoring requests on|\s+subnet declaration|\bfailover(?:\.c)?:|\bLast message\b|\bcount:\s+\d+$|\breserved\b|\bWrote\b|\bdatabase\b|^(?:All|server|Config|Database|PID))"

// -- Stage 3: DHCP message-type discriminator -------------------------------
| alter
    _dhcp_msg_type_raw = arrayindex(regextract(_syslog_msg, "^[^ ]+"), 0)

| alter
    _dhcp_msg_type = if(
        _dhcp_msg_type_raw ~= "client", "DHCPDUPLICATE",
        _dhcp_msg_type_raw ~= "storm", "DHCPSTORM",
        _dhcp_msg_type_raw)

// -- Stage 4: DHCP field extraction -----------------------------------------
// All body extractions read from `_syslog_msg` (the body after
// the envelope, produced by the shared header rule) so they work
// on both RFC 3164 and RFC 5424-in-kernel shapes without needing
// per-shape duplication. The DHCP body verbs (DHCPACK on/to,
// DHCPNAK on, DHCPREQUEST for, etc.) are themselves envelope-
// agnostic; only the wrapping envelope changed in Task #89.
| alter
    _dhcp_acknowledged_ip = arrayindex(regextract(_syslog_msg, "DHCPACK\s+(?:on|to)\s+((?:\d{1,3}\.){3}\d{1,3})"), 0),
    _dhcp_not_acknowledged_ip = arrayindex(regextract(_syslog_msg, "DHCPNAK\s+on\s+((?:\d{1,3}\.){3}\d{1,3})"), 0),
    _dhcp_bootstrap_server_ip = arrayindex(regextract(_syslog_msg, "DHCPREQUEST\s+for\s+\S+\s+\(((?:\d{1,3}\.){3}\d{1,3})"), 0),
    _dhcp_client_ip = coalesce(
        arrayindex(regextract(_syslog_msg, "(?:DHCPDECLINE|DHCPRELEASE)\s+of\s+((?:\d{1,3}\.){3}\d{1,3})"), 0),
        arrayindex(regextract(_syslog_msg, "(?:DHCPINFORM|DHCPLEASEQUERY)\s+from\s+((?:\d{1,3}\.){3}\d{1,3})"), 0)),
    _dhcp_client_mac = coalesce(
        arrayindex(regextract(_syslog_msg, "from\s+((?:[a-fA-F\d]{2}:){5}[\da-fA-F]{2})"), 0),
        arrayindex(regextract(_syslog_msg, "\s+on\s+\S+\s+to\s+((?:[a-fA-F\d]{2}:){5}[\da-fA-F]{2})"), 0),
        arrayindex(regextract(_syslog_msg, "\s+to\s+\S+\s+\(((?:[a-fA-F\d]{2}:){5}[\da-fA-F]{2})"), 0)),
    _dhcp_client_hostname = coalesce(
        arrayindex(regextract(_syslog_msg, "from\s+\S+\s+\(([^\)]+)"), 0),
        arrayindex(regextract(_syslog_msg, "\s+on\s+\S+\s+to\s+\S+\s+\(([\w\-\.]+)"), 0)),
    _dhcp_client_interface = arrayindex(regextract(_syslog_msg, "via\s+(\w+)(?:\s|$)"), 0),
    _dhcp_client_uid = rtrim(arrayindex(regextract(_syslog_msg, "uid\s+(\S+)"), 0), ":"),
    _dhcp_expired_lease_ip = arrayindex(regextract(_syslog_msg, "DHCPEXPIRE\s+on\s+((?:\d{1,3}\.){3}\d{1,3})"), 0),
    _dhcp_lease_duration = arrayindex(regextract(_syslog_msg, "lease\-duration\s+(\d+)"), 0),
    _dhcp_offered_ip = arrayindex(regextract(_syslog_msg, "DHCPOFFER\s+on\s+((?:\d{1,3}\.){3}\d{1,3})"), 0),
    _dhcp_relay_agent_ip = coalesce(
        arrayindex(regextract(_syslog_msg, "via\s+((?:\d{1,3}\.){3}\d{1,3})"), 0),
        arrayindex(regextract(_syslog_msg, "relay(?:\-agent)?\s+((?:\d{1,3}\.){3}\d{1,3})"), 0)),
    _dhcp_requested_ip = arrayindex(regextract(_syslog_msg, "DHCPREQUEST\s+for\s+((?:\d{1,3}\.){3}\d{1,3})"), 0),
    _dhcp_is_renewal = if(_syslog_msg ~= "RENEW", to_boolean("TRUE"), to_boolean("FALSE")),
    _dhcp_target_network = arrayindex(regextract(_syslog_msg, "network\s+((?:\d{1,3}\.){3}\d{1,3}\/\d+)"), 0),
    _dhcp_msg_suffix = coalesce(
        arrayindex(regextract(_syslog_msg, "via \S+(?:\s+TransID\s+\w+)?:\s+(.+)"), 0),
        arrayindex(regextract(_syslog_msg, "(?:uid|TransID)\s+\S+:\s+(.+)$"), 0))

// -- Stage 5: XDM mapping ---------------------------------------------------
// Defensive null-guards mirror the DNS stanza convention: every
// arraycreate(...) wrapping a non-literal element is gated behind an
// explicit `!= null` check so the alter cannot be silently discarded.
| alter
    xdm.observer.vendor = "EfficientIP",
    xdm.observer.product = "SOLIDserver DDI",
    xdm.observer.name = _syslog_host,

    xdm.event.type = "DHCP",
    xdm.event.description = _syslog_msg,
    xdm.event.log_level = if(
        _syslog_severity = 0, XDM_CONST.LOG_LEVEL_EMERGENCY,
        _syslog_severity = 1, XDM_CONST.LOG_LEVEL_ALERT,
        _syslog_severity = 2, XDM_CONST.LOG_LEVEL_CRITICAL,
        _syslog_severity = 3, XDM_CONST.LOG_LEVEL_ERROR,
        _syslog_severity = 4, XDM_CONST.LOG_LEVEL_WARNING,
        _syslog_severity = 5, XDM_CONST.LOG_LEVEL_NOTICE,
        _syslog_severity = 6, XDM_CONST.LOG_LEVEL_INFORMATIONAL,
        _syslog_severity = 7, XDM_CONST.LOG_LEVEL_DEBUG),
    xdm.event.outcome = if(
        _dhcp_msg_type in ("DHCPACK", "DHCPLEASEQUERYDONE"), XDM_CONST.OUTCOME_SUCCESS,
        _dhcp_msg_type in ("DHCPDECLINE", "DHCPNAK", "DHCPLEASEUNKNOWN"), XDM_CONST.OUTCOME_FAILED,
        _dhcp_msg_suffix != null and _dhcp_msg_suffix ~= "failed|abandoned", XDM_CONST.OUTCOME_FAILED),
    xdm.event.outcome_reason = _dhcp_msg_suffix,
    xdm.event.operation_sub_type = if(_dhcp_is_renewal, "RENEW"),

    xdm.network.application_protocol = "DHCP",
    xdm.network.protocol_layers = arraycreate("DHCP"),
    xdm.network.dhcp.chaddr = _dhcp_client_mac,
    xdm.network.dhcp.ciaddr = coalesce(
        _dhcp_client_ip,
        _dhcp_expired_lease_ip,
        if(_dhcp_is_renewal, _dhcp_requested_ip)),
    xdm.network.dhcp.client_hostname = _dhcp_client_hostname,
    xdm.network.dhcp.giaddr = _dhcp_relay_agent_ip,
    xdm.network.dhcp.lease = to_integer(_dhcp_lease_duration),
    xdm.network.dhcp.message_type = if(
        _dhcp_msg_type = "DHCPDISCOVER", XDM_CONST.DHCP_MESSAGE_TYPE_DHCPDISCOVER,
        _dhcp_msg_type = "DHCPOFFER", XDM_CONST.DHCP_MESSAGE_TYPE_DHCPOFFER,
        _dhcp_msg_type = "DHCPREQUEST", XDM_CONST.DHCP_MESSAGE_TYPE_DHCPREQUEST,
        _dhcp_msg_type = "DHCPDECLINE", XDM_CONST.DHCP_MESSAGE_TYPE_DHCPDECLINE,
        _dhcp_msg_type = "DHCPACK", XDM_CONST.DHCP_MESSAGE_TYPE_DHCPACK,
        _dhcp_msg_type = "DHCPNAK", XDM_CONST.DHCP_MESSAGE_TYPE_DHCPNAK,
        _dhcp_msg_type = "DHCPRELEASE", XDM_CONST.DHCP_MESSAGE_TYPE_DHCPRELEASE,
        _dhcp_msg_type = "DHCPINFORM", XDM_CONST.DHCP_MESSAGE_TYPE_DHCPINFORM,
        _dhcp_msg_type = "DHCPFORCERENEW", XDM_CONST.DHCP_MESSAGE_TYPE_DHCPFORCERENEW,
        _dhcp_msg_type = "DHCPLEASEQUERY", XDM_CONST.DHCP_MESSAGE_TYPE_DHCPLEASEQUERY,
        _dhcp_msg_type = "DHCPLEASEUNASSIGNED", XDM_CONST.DHCP_MESSAGE_TYPE_DHCPLEASEUNASSIGNED,
        _dhcp_msg_type = "DHCPLEASEUNKNOWN", XDM_CONST.DHCP_MESSAGE_TYPE_DHCPLEASEUNKNOWN,
        _dhcp_msg_type = "DHCPLEASEACTIVE", XDM_CONST.DHCP_MESSAGE_TYPE_DHCPLEASEACTIVE,
        _dhcp_msg_type = "DHCPBULKLEASEQUERY", XDM_CONST.DHCP_MESSAGE_TYPE_DHCPBULKLEASEQUERY,
        _dhcp_msg_type = "DHCPLEASEQUERYDONE", XDM_CONST.DHCP_MESSAGE_TYPE_DHCPLEASEQUERYDONE,
        _dhcp_msg_type = "DHCPACTIVELEASEQUERY", XDM_CONST.DHCP_MESSAGE_TYPE_DHCPACTIVELEASEQUERY,
        _dhcp_msg_type = "DHCPLEASEQUERYSTATUS", XDM_CONST.DHCP_MESSAGE_TYPE_DHCPLEASEQUERYSTATUS,
        _dhcp_msg_type = "DHCPTLS", XDM_CONST.DHCP_MESSAGE_TYPE_DHCPTLS),
    xdm.network.dhcp.requested_address = _dhcp_requested_ip,
    xdm.network.dhcp.siaddr = _dhcp_bootstrap_server_ip,
    xdm.network.dhcp.yiaddr = coalesce(
        _dhcp_offered_ip,
        _dhcp_acknowledged_ip,
        _dhcp_not_acknowledged_ip),

    xdm.intermediate.ipv4 = _dhcp_relay_agent_ip,

    xdm.source.host.device_id = _dhcp_client_uid,
    xdm.source.host.mac_addresses = if(_dhcp_client_mac != null, arraycreate(_dhcp_client_mac)),
    xdm.source.interface = _dhcp_client_interface,
    xdm.source.ipv4 = coalesce(_dhcp_client_ip, _dhcp_expired_lease_ip),
    xdm.source.process.name = _syslog_proc,
    xdm.source.process.pid = to_integer(_syslog_pid),

    xdm.target.ipv4 = _dhcp_bootstrap_server_ip,
    xdm.target.subnet = _dhcp_target_network;


// =========================================================================
// Pipeline 3 -- OpenSSH sshd login / connection events
// =========================================================================
// Third `;`-terminated pipeline inside the single
// [MODEL: dataset = efficientip_raw] block opened above.

call efficientip_syslog_header
| filter _syslog_proc = "sshd"

// -- Stage 2: SSH event extraction ------------------------------------------
// First word of the message body is the action verb (Accepted, Failed,
// Connection, Received, Disconnect, Invalid, Disconnected, ...).
// Anchored extractions for user, client IP, and port replace the
// original's broken `[^\:|\d+]+\:\s` character class and unbounded
// digit-dot greps.
| alter
    _ssh_act = uppercase(arrayindex(regextract(_syslog_msg, "^([A-Za-z]+)"), 0)),
    // User extraction covers the four common sshd line shapes:
    //   "Accepted publickey for opadmin from <ip>"
    //   "Failed password for invalid user root from <ip>"
    //   "Connection closed by invalid user root <ip> port"
    //   "user=opadmin" (PAM key/value form)
    _ssh_user = coalesce(
        arrayindex(regextract(_syslog_msg, "(?:for invalid user|for|user)\s+(\S+)\s+from"), 0),
        arrayindex(regextract(_syslog_msg, "(?:by invalid user|by user|by)\s+(\S+)\s+(?:\d|[\da-fA-F]*:)"), 0),
        arrayindex(regextract(_syslog_msg, "user=([^\s,]+)"), 0)),
    // Explicit IPv4 / IPv6 literals captured directly from the body so
    // each family routes through its own typed alter without a runtime
    // is_ipv4 / is_ipv6 detour. Two coalesce arms cover both
    // "from <ip>" (Accepted/Failed) and "by ... <ip>" (Connection closed).
    _ssh_client_ipv4_raw = coalesce(
        arrayindex(regextract(_syslog_msg, "from\s+((?:\d{1,3}\.){3}\d{1,3})"), 0),
        arrayindex(regextract(_syslog_msg, "by\s+\S+(?:\s+\S+)*?\s+((?:\d{1,3}\.){3}\d{1,3})\s+port"), 0)),
    _ssh_client_ipv6_raw = coalesce(
        arrayindex(regextract(_syslog_msg, "from\s+([\da-fA-F]*:[\da-fA-F:]+)"), 0),
        arrayindex(regextract(_syslog_msg, "by\s+\S+(?:\s+\S+)*?\s+([\da-fA-F]*:[\da-fA-F:]+)\s+port"), 0)),
    _ssh_client_port = arrayindex(regextract(_syslog_msg, "port\s+(\d+)"), 0)

| alter
    _ssh_client_ipv4 = if(is_ipv4(_ssh_client_ipv4_raw), _ssh_client_ipv4_raw, null),
    _ssh_client_ipv6 = if(is_ipv6(_ssh_client_ipv6_raw), _ssh_client_ipv6_raw, null)

// -- Stage 3: XDM mapping ---------------------------------------------------
| alter
    xdm.observer.vendor = "EfficientIP",
    xdm.observer.product = "SOLIDserver DDI",
    xdm.observer.name = _syslog_host,

    xdm.event.type = "SSH",
    xdm.event.description = _syslog_msg,
    xdm.event.operation_sub_type = _ssh_act,
    xdm.event.log_level = if(
        _syslog_severity = 0, XDM_CONST.LOG_LEVEL_EMERGENCY,
        _syslog_severity = 1, XDM_CONST.LOG_LEVEL_ALERT,
        _syslog_severity = 2, XDM_CONST.LOG_LEVEL_CRITICAL,
        _syslog_severity = 3, XDM_CONST.LOG_LEVEL_ERROR,
        _syslog_severity = 4, XDM_CONST.LOG_LEVEL_WARNING,
        _syslog_severity = 5, XDM_CONST.LOG_LEVEL_NOTICE,
        _syslog_severity = 6, XDM_CONST.LOG_LEVEL_INFORMATIONAL,
        _syslog_severity = 7, XDM_CONST.LOG_LEVEL_DEBUG),
    xdm.event.outcome = if(
        _ssh_act in ("ACCEPTED", "DISCONNECTED"), XDM_CONST.OUTCOME_SUCCESS,
        _ssh_act in ("FAILED", "INVALID", "ERROR", "REVERSE"), XDM_CONST.OUTCOME_FAILED),

    xdm.network.application_protocol = "SSH",
    xdm.network.protocol_layers = arraycreate("SSH"),

    xdm.source.ipv4 = _ssh_client_ipv4,
    xdm.source.ipv6 = _ssh_client_ipv6,
    xdm.source.port = to_integer(_ssh_client_port),
    xdm.source.user.username = _ssh_user,
    xdm.source.process.name = _syslog_proc,
    xdm.source.process.pid = to_integer(_syslog_pid);


// =========================================================================
// Pipeline 4 -- sudo privileged-command audit
// =========================================================================
// Fourth `;`-terminated pipeline inside the single
// [MODEL: dataset = efficientip_raw] block opened above.

call efficientip_syslog_header
| filter _syslog_proc = "sudo"

// -- Stage 2: sudo line extraction ------------------------------------------
// Standard sudo line: "user : TTY=tty ; PWD=/path ; USER=tgt ; COMMAND=cmd"
// Quoted-string fallback is retained as the coalesce tail to keep
// compatibility with non-standard sudo wrappers that quote the body.
| alter
    _sudo_src_user = coalesce(
        arrayindex(regextract(_syslog_msg, "^(\S+)\s+:\s+TTY="), 0),
        arrayindex(regextract(_syslog_msg, "^'?([^'\s:]+)"), 0)),
    _sudo_tgt_user = arrayindex(regextract(_syslog_msg, "USER=(\S+?)\s*;?"), 0),
    _sudo_pwd = arrayindex(regextract(_syslog_msg, "PWD=([^;]+?)\s*;"), 0),
    _sudo_cmd = arrayindex(regextract(_syslog_msg, "COMMAND=(.+)$"), 0)

// -- Stage 3: XDM mapping ---------------------------------------------------
| alter
    xdm.observer.vendor = "EfficientIP",
    xdm.observer.product = "SOLIDserver DDI",
    xdm.observer.name = _syslog_host,

    xdm.event.type = "SUDO",
    xdm.event.description = _syslog_msg,
    xdm.event.log_level = if(
        _syslog_severity = 0, XDM_CONST.LOG_LEVEL_EMERGENCY,
        _syslog_severity = 1, XDM_CONST.LOG_LEVEL_ALERT,
        _syslog_severity = 2, XDM_CONST.LOG_LEVEL_CRITICAL,
        _syslog_severity = 3, XDM_CONST.LOG_LEVEL_ERROR,
        _syslog_severity = 4, XDM_CONST.LOG_LEVEL_WARNING,
        _syslog_severity = 5, XDM_CONST.LOG_LEVEL_NOTICE,
        _syslog_severity = 6, XDM_CONST.LOG_LEVEL_INFORMATIONAL,
        _syslog_severity = 7, XDM_CONST.LOG_LEVEL_DEBUG),

    xdm.network.application_protocol = "SUDO",
    xdm.network.protocol_layers = arraycreate("SUDO"),

    xdm.source.host.hostname = _syslog_host,
    xdm.source.user.username = _sudo_src_user,
    xdm.source.process.name = _syslog_proc,
    xdm.source.process.pid = to_integer(_syslog_pid),

    xdm.target.user.username = _sudo_tgt_user,
    xdm.target.process.command_line = _sudo_cmd,
    xdm.target.process.executable.path = _sudo_pwd;
