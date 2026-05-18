# Derived from gocortex-xql-ide/server/data/scaffold-engine.ts (AGPL-3.0).
"""
scaffold_xql — sample-to-rule scaffold engine.

Deterministic one-shot that takes raw log samples and emits a paired
starter parsing rule + datamodel rule. Self-contained: accepts plain
text and returns plain text rules.

The full upstream relies on:
  - log-field-mappings.ts (matchFieldToXdr)
  - field-anchors.ts (lookupAnchor) — backed by an external JSON anchor
    library that we don't yet bundle in this repo.

This Python port ships a minimal in-code FIELD_MAPPINGS table mirroring
the TS one, plus a small built-in anchor heuristic keyed on common
field-name shapes. It detects format family (json/kv/csv/text) and
emits parsing + modeling rules with validation gating via _engine.

Public entrypoint:
    execute(raw_log: str, vendor: str = "vendor_name",
            product: str = "product_name") -> dict
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import List, Optional


# ── Format detection ─────────────────────────────────────────────────


def detect_format(raw: str) -> str:
    """Return one of 'json' | 'kv' | 'csv' | 'text'."""
    trimmed = raw.strip()
    if not trimmed:
        return "text"
    if trimmed[0] in ("{", "["):
        try:
            json.loads(trimmed)
            return "json"
        except Exception:
            pass
    kv_matches = re.findall(
        r'(?:^|[\s,])([A-Za-z_][\w.-]*)=(?:"[^"]*"|\S+)', trimmed
    )
    if len(kv_matches) >= 2:
        return "kv"
    lines = [l for l in trimmed.split("\n") if l.strip()]
    if lines:
        counts = [
            len(re.findall(r",", re.sub(r'"[^"]*"', '""', l))) for l in lines
        ]
        if counts[0] >= 1 and all(c == counts[0] for c in counts):
            return "csv"
    return "text"


# ── Leaf extraction ──────────────────────────────────────────────────


@dataclass
class RawLeaf:
    path: str
    type: str
    sampleValue: Optional[str] = None
    columnIndex: Optional[int] = None


def _walk_json(value, path: str, out: List[RawLeaf]) -> None:
    if value is None:
        out.append(RawLeaf(path=path, type="null", sampleValue="null"))
        return
    if isinstance(value, list):
        out.append(RawLeaf(path=path, type="array", sampleValue=f"[{len(value)} items]"))
        if value and isinstance(value[0], (dict, list)):
            _walk_json(value[0], f"{path}[0]", out)
        return
    if isinstance(value, dict):
        for key, child in value.items():
            needs_bracket = not re.match(r"^[A-Za-z0-9_]+$", key)
            child_path = f"{path}['{key}']" if needs_bracket else f"{path}.{key}"
            _walk_json(child, child_path, out)
        return
    if isinstance(value, bool):
        t = "boolean"
    elif isinstance(value, int):
        t = "integer"
    elif isinstance(value, float):
        t = "float"
    else:
        t = "string"
    s = str(value)
    if len(s) > 80:
        s = s[:77] + "..."
    out.append(RawLeaf(path=path, type=t, sampleValue=s))


def extract_json_leaves(raw: str) -> List[RawLeaf]:
    try:
        parsed = json.loads(raw)
    except Exception:
        return []
    out: List[RawLeaf] = []
    _walk_json(parsed, "$", out)
    return [l for l in out if l.type != "object"]


def extract_kv_leaves(raw: str) -> List[RawLeaf]:
    seen: dict[str, RawLeaf] = {}
    pattern = re.compile(r'(?:^|[\s,])([A-Za-z_][\w.-]*)=("([^"]*)"|([^\s,]+))')
    for m in pattern.finditer(raw):
        key = m.group(1)
        value = m.group(3) if m.group(3) is not None else (m.group(4) or "")
        if key not in seen:
            sample = value[:77] + "..." if len(value) > 80 else value
            seen[key] = RawLeaf(path=key, type="string", sampleValue=sample)
    return list(seen.values())


def extract_csv_leaves(raw: str) -> List[RawLeaf]:
    lines = [l for l in raw.split("\n") if l.strip()]
    if not lines:
        return []
    header = [c.strip().strip('"') for c in lines[0].split(",")]
    sample_row = [c.strip().strip('"') for c in (lines[1].split(",") if len(lines) > 1 else [])]
    id_like = re.compile(r"^[A-Za-z_][\w-]*$")
    headers_are_ids = all(id_like.match(h) for h in header)
    out: List[RawLeaf] = []
    for i, h in enumerate(header):
        out.append(RawLeaf(
            path=h if headers_are_ids else f"col_{i + 1}",
            type="string",
            sampleValue=sample_row[i] if i < len(sample_row) else None,
            columnIndex=i,
        ))
    return out


# ── Field-to-xdr mapping (port of log-field-mappings.ts) ──────────────


@dataclass
class FieldMapping:
    pattern: re.Pattern
    xdr_field: str
    xql_function: str
    description: str


FIELD_MAPPINGS: List[FieldMapping] = [
    FieldMapping(
        pattern=re.compile(
            r"^(timestamp|time|date|created_at|createdAt|eventTime|event_time|@timestamp|"
            r"occurredAt|occurred_at|generatedAt|generated_at|receivedAt|received_at)$",
            re.IGNORECASE,
        ),
        xdr_field="_time",
        xql_function='if(FIELD != null and FIELD != "", parse_epoch(FIELD, "MILLIS"), null)',
        description="Timestamp field -- map to _time using parse_epoch or parse_timestamp",
    ),
    FieldMapping(
        pattern=re.compile(
            r"^(ip|ipaddr|ip_addr|src_ip|srcip|source_ip|sourceIp|client_ip|clientIp|"
            r"remote_ip|remoteIp|actor_ip|peer_ip|peerIp|caller_ip|callerIp|request_ip|requestIp)$",
            re.IGNORECASE,
        ),
        xdr_field="actor_remote_ip",
        xql_function="actor_remote_ip = FIELD",
        description="Client or source IP address",
    ),
    FieldMapping(
        pattern=re.compile(
            r"^(dst_ip|dstip|dest_ip|destIp|destination_ip|destinationIp|target_ip|targetIp|"
            r"server_ip|serverIp)$",
            re.IGNORECASE,
        ),
        xdr_field="action_remote_ip",
        xql_function="action_remote_ip = FIELD",
        description="Destination or target IP address",
    ),
    FieldMapping(
        pattern=re.compile(
            r"^(user|username|user_name|userName|email|userEmail|user_email|actor|"
            r"actor_email|actorEmail|principal|subject|login|loginName|login_name)$",
            re.IGNORECASE,
        ),
        xdr_field="actor_primary_username",
        xql_function="actor_primary_username = FIELD",
        description="User identity or email address",
    ),
    FieldMapping(
        pattern=re.compile(
            r"^(message|msg|description|detail|details|summary|text|body|reason)$",
            re.IGNORECASE,
        ),
        xdr_field="action_evtlog_message",
        xql_function="action_evtlog_message = FIELD",
        description="Event message or description",
    ),
    FieldMapping(
        pattern=re.compile(
            r"^(severity|level|priority|riskLevel|risk_level|threat_level|threatLevel|criticality)$",
            re.IGNORECASE,
        ),
        xdr_field="action_evtlog_severity",
        xql_function="action_evtlog_severity = FIELD",
        description="Event severity or risk level",
    ),
    FieldMapping(
        pattern=re.compile(
            r"^(action|eventType|event_type|eventName|event_name|activity|operation|"
            r"operationType|operation_type|category|eventCategory|event_category)$",
            re.IGNORECASE,
        ),
        xdr_field="event_id",
        xql_function="event_id = FIELD",
        description="Event type, action, or category identifier",
    ),
    FieldMapping(
        pattern=re.compile(
            r"^(hostname|host|server|serverName|server_name|machineName|machine_name|"
            r"deviceName|device_name|node|nodeName|node_name)$",
            re.IGNORECASE,
        ),
        xdr_field="action_evtlog_hostname",
        xql_function="action_evtlog_hostname = FIELD",
        description="Hostname or server name",
    ),
    FieldMapping(
        pattern=re.compile(
            r"^(src_port|srcport|source_port|sourcePort|client_port|clientPort)$",
            re.IGNORECASE,
        ),
        xdr_field="action_local_port",
        xql_function="action_local_port = to_integer(FIELD)",
        description="Source or client port number",
    ),
    FieldMapping(
        pattern=re.compile(
            r"^(dst_port|dstport|dest_port|destPort|destination_port|destinationPort|"
            r"server_port|serverPort|target_port|targetPort)$",
            re.IGNORECASE,
        ),
        xdr_field="action_remote_port",
        xql_function="action_remote_port = to_integer(FIELD)",
        description="Destination or server port number",
    ),
    FieldMapping(
        pattern=re.compile(
            r"^(url|uri|path|request_url|requestUrl|request_uri|requestUri|href|endpoint)$",
            re.IGNORECASE,
        ),
        xdr_field="action_evtlog_url",
        xql_function="action_evtlog_url = FIELD",
        description="URL, URI, or request path",
    ),
    FieldMapping(
        pattern=re.compile(
            r"^(user_agent|userAgent|useragent|ua|http_user_agent|httpUserAgent)$",
            re.IGNORECASE,
        ),
        xdr_field="action_evtlog_user_agent",
        xql_function="action_evtlog_user_agent = FIELD",
        description="HTTP user agent string",
    ),
    FieldMapping(
        pattern=re.compile(
            r"^(country|geo|location|geo_country|geoCountry|countryCode|country_code|"
            r"src_country|srcCountry)$",
            re.IGNORECASE,
        ),
        xdr_field="actor_geo_country",
        xql_function="actor_geo_country = FIELD",
        description="Geographic country or location",
    ),
    FieldMapping(
        pattern=re.compile(
            r"^(status|result|outcome|response_code|responseCode|statusCode|status_code|"
            r"http_status|httpStatus)$",
            re.IGNORECASE,
        ),
        xdr_field="action_evtlog_status",
        xql_function="action_evtlog_status = FIELD",
        description="Event status, outcome, or response code",
    ),
    FieldMapping(
        pattern=re.compile(
            r"^(accountId|account_id|tenantId|tenant_id|orgId|org_id|"
            r"organisationId|organisation_id|organizationId|organization_id)$",
            re.IGNORECASE,
        ),
        xdr_field="actor_primary_org_id",
        xql_function="actor_primary_org_id = FIELD",
        description="Account, tenant, or organisation identifier",
    ),
    FieldMapping(
        pattern=re.compile(
            r"^(protocol|proto|transport|network_protocol|networkProtocol)$", re.IGNORECASE
        ),
        xdr_field="action_network_protocol",
        xql_function="action_network_protocol = FIELD",
        description="Network protocol (TCP, UDP, HTTP, etc.)",
    ),
    FieldMapping(
        pattern=re.compile(
            r"^(bytes|bytesSent|bytes_sent|bytesReceived|bytes_received|size|"
            r"content_length|contentLength)$",
            re.IGNORECASE,
        ),
        xdr_field="action_network_packet_data",
        xql_function="action_network_packet_data = to_integer(FIELD)",
        description="Byte count or content size",
    ),
    FieldMapping(
        pattern=re.compile(
            r"^(method|http_method|httpMethod|request_method|requestMethod|verb)$",
            re.IGNORECASE,
        ),
        xdr_field="action_evtlog_request_method",
        xql_function="action_evtlog_request_method = FIELD",
        description="HTTP method or request verb",
    ),
    FieldMapping(
        pattern=re.compile(
            r"^(process|processName|process_name|processId|process_id|pid)$",
            re.IGNORECASE,
        ),
        xdr_field="actor_process_name",
        xql_function="actor_process_name = FIELD",
        description="Process name or identifier",
    ),
    FieldMapping(
        pattern=re.compile(
            r"^(fileName|file_name|filePath|file_path|file|target_file|targetFile)$",
            re.IGNORECASE,
        ),
        xdr_field="action_file_name",
        xql_function="action_file_name = FIELD",
        description="File name or path",
    ),
]


def match_field_to_xdr(field_name: str) -> Optional[FieldMapping]:
    leaf = field_name.split(".")[-1] if "." in field_name else field_name
    for mapping in FIELD_MAPPINGS:
        if mapping.pattern.match(leaf):
            return mapping
    return None


# ── Minimal anchor heuristic ─────────────────────────────────────────
# The upstream library is data-driven via field-anchors.json; we do not
# ship it. Provide a built-in mapping for the most common cases so the
# scaffold output is useful for the canonical samples. Lookups beyond
# this list return None and the temp is surfaced under NOT MAPPED.

_BUILTIN_ANCHORS: dict[str, str] = {
    "user": "xdm.source.user.username",
    "username": "xdm.source.user.username",
    "user_name": "xdm.source.user.username",
    "email": "xdm.source.user.email_address",
    "ip": "xdm.source.ipv4",
    "src_ip": "xdm.source.ipv4",
    "source_ip": "xdm.source.ipv4",
    "client_ip": "xdm.source.ipv4",
    "remote_ip": "xdm.source.ipv4",
    "dst_ip": "xdm.target.ipv4",
    "dest_ip": "xdm.target.ipv4",
    "destination_ip": "xdm.target.ipv4",
    "target_ip": "xdm.target.ipv4",
    "hostname": "xdm.source.host.hostname",
    "host": "xdm.source.host.hostname",
    "url": "xdm.network.http.url",
    "uri": "xdm.network.http.url",
    "method": "xdm.network.http.method",
    "http_method": "xdm.network.http.method",
    "user_agent": "xdm.source.user_agent",
    "useragent": "xdm.source.user_agent",
    "country": "xdm.source.location.country",
    "src_port": "xdm.source.port",
    "source_port": "xdm.source.port",
    "dst_port": "xdm.target.port",
    "dest_port": "xdm.target.port",
    "destination_port": "xdm.target.port",
    "protocol": "xdm.network.ip_protocol",
    "severity": "xdm.alert.severity",
    "action": "xdm.event.type",
    "event_type": "xdm.event.type",
    "outcome": "xdm.event.outcome",
    "status": "xdm.event.outcome",
    "message": "xdm.event.description",
    "description": "xdm.event.description",
    "process": "xdm.source.process.name",
    "process_name": "xdm.source.process.name",
    "pid": "xdm.source.process.pid",
    "file": "xdm.target.file.path",
    "file_name": "xdm.target.file.path",
    "file_path": "xdm.target.file.path",
}


def lookup_anchor(field_name: str) -> Optional[dict]:
    leaf = field_name.split(".")[-1] if "." in field_name else field_name
    leaf = leaf.lower()
    if leaf in _BUILTIN_ANCHORS:
        return {"xdmPath": _BUILTIN_ANCHORS[leaf], "confidence": 0.8, "frequency": 5}
    return None


# ── Temp-name sanitiser ──────────────────────────────────────────────


def sanitise_temp_name(raw_path: str, used: set[str]) -> str:
    s = raw_path
    s = re.sub(r"\['([^']+)'\]", r".\1", s)
    s = re.sub(r"\[\d+\]", "", s)
    s = re.sub(r"^\$\.?", "", s)
    s = re.sub(r"[.\-\s]+", "_", s)
    s = re.sub(r"[^A-Za-z0-9_]", "", s)
    s = s.lower()
    s = re.sub(r"_+", "_", s).strip("_")
    if not s:
        s = "field"
    if len(s) > 40:
        s = s[:40].rstrip("_")
    candidate = f"_{s}"
    if candidate not in used:
        used.add(candidate)
        return candidate
    i = 2
    while f"{candidate}_{i}" in used:
        i += 1
    final = f"{candidate}_{i}"
    used.add(final)
    return final


def build_expression(leaf: dict, fmt: str) -> str:
    """Return the RHS expression for a leaf, based on detected format."""
    path = leaf["path"]
    if fmt == "json":
        fn = "json_extract_array" if leaf.get("type") == "array" else "json_extract_scalar"
        return f'{fn}(_raw_log, "{path}")'
    if fmt == "kv":
        escaped = re.sub(r"[.\-]", lambda m: "\\" + m.group(0), path)
        return f'arrayindex(regextract(_raw_log, "{escaped}=\\"?([^\\"\\s,]+)"), 0)'
    if fmt == "csv":
        col_idx = leaf.get("columnIndex")
        if isinstance(col_idx, int):
            return f'trim(arrayindex(split(_raw_log, ","), {col_idx}))'
        return "_raw_log"
    return "_raw_log"


# ── Aggregation ──────────────────────────────────────────────────────


def aggregate(per_sample: List[List[RawLeaf]]) -> List[dict]:
    m: dict[str, dict] = {}
    for s_idx, sample in enumerate(per_sample):
        seen_this: set[str] = set()
        for leaf in sample:
            if leaf.path in seen_this:
                continue
            seen_this.add(leaf.path)
            existing = m.get(leaf.path)
            if existing:
                existing["seenIn"] += 1
                if (not existing.get("sampleValue") or existing["sampleValue"] == "null") and leaf.sampleValue:
                    existing["sampleValue"] = leaf.sampleValue
            else:
                m[leaf.path] = {
                    "path": leaf.path,
                    "type": leaf.type,
                    "sampleValue": leaf.sampleValue,
                    "columnIndex": leaf.columnIndex,
                    "seenIn": 1,
                    "firstIndex": s_idx * 10000 + len(m),
                }
    return sorted(m.values(), key=lambda x: x["firstIndex"])


# ── Rendering ────────────────────────────────────────────────────────

HEADER_INGEST_TPL = (
    '[INGEST:vendor="{vendor}", product="{product}", '
    'target_dataset="{vendor}_{product}_raw", no_hit=keep]'
)
HEADER_MODEL_TPL = "[MODEL: dataset = {vendor}_{product}_raw]"


def _indent(line: str) -> str:
    return f"    {line}"


def _join_alter(lines: List[str]) -> str:
    return ",\n".join(_indent(l) for l in lines)


def build_parsing_rule(temps: List[dict], vendor: str, product: str) -> dict:
    extract_lines: List[str] = []
    xdr_lines: List[str] = []
    mapped: List[str] = []
    unmapped: List[str] = []
    for t in temps:
        extract_lines.append(f"{t['tempName']} = {t['expression']}")
        if t.get("xdrAssignment"):
            xdr_lines.append(t["xdrAssignment"])
            mapped.append(t["tempName"])
        else:
            unmapped.append(t["tempName"])

    has_timestamp = any(re.match(r"^\s*_time\s*=", l) for l in xdr_lines)
    final_alter_lines = list(xdr_lines)
    if not has_timestamp:
        final_alter_lines.append("_time = current_time()")

    blocks: List[str] = [HEADER_INGEST_TPL.format(vendor=vendor, product=product)]
    blocks.append("filter")
    blocks.append(_indent("_raw_log != null"))
    if extract_lines:
        blocks.append("| alter")
        blocks.append(_join_alter(extract_lines))
    blocks.append("| alter")
    blocks.append(_join_alter(final_alter_lines))
    return {
        "code": "\n".join(blocks) + ";\n",
        "mappedTemps": mapped,
        "unmappedTemps": unmapped,
    }


def build_modeling_rule(temps: List[dict], vendor: str, product: str) -> dict:
    extract_lines: List[str] = []
    xdm_lines: List[str] = []
    mapped: List[str] = []
    unmapped: List[str] = []
    for t in temps:
        if t.get("anchor"):
            extract_lines.append(f"{t['tempName']} = {t['expression']}")
            xdm_lines.append(f"{t['anchor']['xdmPath']} = {t['tempName']}")
            mapped.append(t["tempName"])
        else:
            unmapped.append(t["tempName"])

    observer_lines = [
        f'xdm.observer.vendor = "{vendor}"',
        f'xdm.observer.product = "{product}"',
    ]
    blocks: List[str] = [HEADER_MODEL_TPL.format(vendor=vendor, product=product)]
    if extract_lines:
        blocks.append("alter")
        blocks.append(_join_alter(extract_lines))
        blocks.append("| alter")
    else:
        blocks.append("alter")
    drain_lines = observer_lines + xdm_lines
    blocks.append(_join_alter(drain_lines) + ";")

    if unmapped:
        blocks.append("")
        blocks.append("// NOT MAPPED -- the following sample fields had no high-confidence")
        blocks.append("// xdm.* anchor and need a manual review. The suggested extract")
        blocks.append("// expression is shown verbatim; pick an xdm.* path and add both")
        blocks.append("// the alter line and the matching xdm.<path> = <temp> assignment.")
        for t in temps:
            if t.get("anchor"):
                continue
            blocks.append(f"//   {t['sourcePath']}  ->  {t['tempName']} = {t['expression']}")
    return {
        "code": "\n".join(blocks) + "\n",
        "mappedTemps": mapped,
        "unmappedTemps": unmapped,
    }


# ── Format-family heuristic (pattern A/B/C/D) ────────────────────────
# Reflects the upstream task's pattern taxonomy and lets callers ask
# "what shape did the scaffold detect?". Maps:
#   A — pure JSON                (>= 1 json sample)
#   B — key=value syslog         (kv detector)
#   C — positional CSV/TSV       (csv detector)
#   D — opaque text / regex      (everything else)

def pattern_family(fmt: str) -> str:
    return {"json": "A", "kv": "B", "csv": "C", "text": "D"}.get(fmt, "D")


# ── Main entrypoint ──────────────────────────────────────────────────


MAX_SAMPLES = 50
MAX_TEMPS = 64
MAX_PATH_LEN = 256


def _pick_dominant_format(formats: List[str]) -> str:
    if not formats:
        return "text"
    counts: dict[str, int] = {}
    for f in formats:
        counts[f] = counts.get(f, 0) + 1
    order = ["json", "kv", "csv", "text"]
    best = "text"
    best_count = -1
    for f in order:
        c = counts.get(f, 0)
        if c > best_count:
            best = f
            best_count = c
    return best


def scaffold_from_samples(
    samples: List[str],
    vendor: str = "vendor_name",
    product: str = "product_name",
) -> dict:
    """Generate paired parsing + modeling scaffolds from raw log samples."""
    # Imports are deferred so consumers that only want the format-family
    # detector don't pay the rules-engine cost.
    from ._engine import analyse_code

    safe_samples = (samples or [])[:MAX_SAMPLES]
    formats: List[str] = []
    per_sample_leaves: List[List[RawLeaf]] = []
    for raw in safe_samples:
        fmt = detect_format(raw)
        formats.append(fmt)
        if fmt == "json":
            leaves = extract_json_leaves(raw)
        elif fmt == "kv":
            leaves = extract_kv_leaves(raw)
        elif fmt == "csv":
            leaves = extract_csv_leaves(raw)
        else:
            leaves = []
        per_sample_leaves.append([l for l in leaves if len(l.path) <= MAX_PATH_LEN])

    dominant = _pick_dominant_format(formats)
    aggregated = aggregate(per_sample_leaves)

    used: set[str] = set()
    temps: List[dict] = []
    for leaf in aggregated:
        if len(temps) >= MAX_TEMPS:
            break
        temp_name = sanitise_temp_name(leaf["path"], used)
        expression = build_expression(leaf, dominant)
        t: dict = {
            "tempName": temp_name,
            "sourcePath": leaf["path"],
            "expression": expression,
            "sampleValue": leaf.get("sampleValue"),
            "type": leaf["type"],
        }
        leaf_ident = sanitise_temp_name(leaf["path"], set()).lstrip("_")
        xdr_mapping = match_field_to_xdr(leaf_ident)
        if xdr_mapping:
            t["xdrField"] = xdr_mapping.xdr_field
            if "FIELD" in xdr_mapping.xql_function:
                rendered = xdr_mapping.xql_function.replace("FIELD", temp_name)
            else:
                rendered = f"{xdr_mapping.xdr_field} = {temp_name}"
            if not rendered.startswith(xdr_mapping.xdr_field):
                rendered = f"{xdr_mapping.xdr_field} = {rendered}"
            t["xdrAssignment"] = rendered
        anchor = lookup_anchor(leaf_ident)
        if anchor:
            t["anchor"] = anchor
        temps.append(t)

    parsing = build_parsing_rule(temps, vendor, product)
    modeling = build_modeling_rule(temps, vendor, product)
    parsing_analysis = analyse_code(parsing["code"], "parsing")
    modeling_analysis = analyse_code(modeling["code"], "modeling")

    validation = {
        "parsing": {
            "errors": parsing_analysis.summary.errors,
            "warnings": parsing_analysis.summary.warnings,
            "errorRuleIds": [
                v.ruleId for v in parsing_analysis.violations if v.severity == "error"
            ],
        },
        "modeling": {
            "errors": modeling_analysis.summary.errors,
            "warnings": modeling_analysis.summary.warnings,
            "errorRuleIds": [
                v.ruleId for v in modeling_analysis.violations if v.severity == "error"
            ],
        },
        "blocking": (
            parsing_analysis.summary.errors > 0 or modeling_analysis.summary.errors > 0
        ),
    }
    return {
        "parsing": parsing,
        "modeling": modeling,
        "temps": temps,
        "formats": formats,
        "patternFamilies": [pattern_family(f) for f in formats],
        "dominantFormat": dominant,
        "dominantPattern": pattern_family(dominant),
        "validation": validation,
    }


def execute(raw_log: str, vendor: str = "vendor_name", product: str = "product_name", **_unused) -> dict:
    """Single-sample convenience wrapper around scaffold_from_samples.

    Splits multi-line input on blank lines so a paste of three JSON events
    separated by blank lines is treated as three samples.
    """
    if isinstance(raw_log, list):
        return scaffold_from_samples(raw_log, vendor=vendor, product=product)
    # Split on blank-line separators; fall back to single sample.
    parts = [p.strip() for p in re.split(r"\n\s*\n", raw_log) if p.strip()]
    if not parts:
        parts = [raw_log]
    return scaffold_from_samples(parts, vendor=vendor, product=product)
