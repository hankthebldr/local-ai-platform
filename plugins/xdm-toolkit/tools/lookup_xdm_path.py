"""
lookup_xdm_path — fuzzy-match a vendor field name or NL description to
candidate XDM paths.

Reads the shipped XDM schema reference from
docs/seed/xql/xql-xdm-knowledge.md (§2). Returns the top-K matches with
confidence + the companion-pair partner when applicable.

Confidence:
  HIGH   — exact substring match on the leaf field name
  MEDIUM — token overlap on the full path or label
  LOW    — fallback fuzzy match, surfaced only if no HIGH/MEDIUM hit

Heuristic, not a real semantic embedding lookup — the agent
xdm-schema-navigator handles ambiguous cases with full LLM context. This
tool is the fast path for obvious matches during agentic loops.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

KNOWLEDGE_PATH = Path("docs/seed/xql/xql-xdm-knowledge.md")

# Tiny seed catalogue extracted from §2 — covers the most common vendor
# field names. Real lookups still fall back to scanning the full file.
SEED_CATALOGUE: List[Tuple[str, str, List[str]]] = [
    # (xdm_path, label, alias keywords)
    ("xdm.source.ipv4", "Source IPv4 address (scalar)", ["src.ip", "src_ip", "source_ip", "client_ip", "saddr"]),
    ("xdm.source.host.ipv4_addresses", "Source host IPv4 addresses (array)", ["src.ip.list", "src_ips"]),
    ("xdm.target.ipv4", "Target IPv4 address (scalar)", ["dst.ip", "dst_ip", "dest_ip", "daddr", "destination_ip"]),
    ("xdm.target.host.ipv4_addresses", "Target host IPv4 addresses (array)", ["dst.ip.list"]),
    ("xdm.source.port", "Source TCP/UDP port", ["src.port", "src_port", "sport"]),
    ("xdm.target.port", "Target TCP/UDP port", ["dst.port", "dst_port", "dport", "destination_port"]),
    ("xdm.event.outcome", "Event outcome (XDM_CONST)", ["status", "result", "outcome"]),
    ("xdm.event.outcome_reason", "Event outcome reason (free text)", ["reason", "message", "status_msg"]),
    ("xdm.event.type", "Event type (XDM_CONST)", ["event.kind", "event_type", "category"]),
    ("xdm.event.original_event_type", "Original raw event type string", ["event.action", "raw_event_type"]),
    ("xdm.network.application_protocol", "Application protocol name", ["proto", "protocol", "app_proto"]),
    ("xdm.network.application_protocol_category", "Application protocol category (XDM_CONST)", ["proto_category"]),
    ("xdm.auth.outcome", "Auth attempt outcome (XDM_CONST)", ["auth.status", "login_result"]),
    ("xdm.auth.outcome_reason", "Auth outcome reason text", ["auth.reason", "login_message"]),
    ("xdm.alert.severity", "Alert severity (XDM_CONST)", ["sev", "severity", "priority"]),
    ("xdm.alert.name", "Alert / signature name", ["sig_name", "rule_name", "alert.name"]),
    ("xdm.source.user.username", "Source user account name", ["user", "username", "src_user", "account"]),
    ("xdm.target.user.username", "Target user account name", ["target_user", "dst_user"]),
    ("xdm.source.process.name", "Source process name", ["process.name", "proc_name", "image"]),
    ("xdm.source.process.command_line", "Source process command line", ["process.cmd", "cmdline", "command_line"]),
    ("xdm.source.process.parent.command_line", "Parent process command line", ["parent.cmd", "ppid_cmdline"]),
    ("xdm.event.description", "Free-text event description", ["description", "msg", "details"]),
    ("xdm.observer.name", "Observer / sensor name", ["host", "hostname", "device_name"]),
    ("xdm.observer.vendor", "Observer vendor", ["vendor"]),
    ("xdm.observer.product", "Observer product", ["product", "device_product"]),
]


# Companion-pair lookup — mirrors validate_xql.py.
COMPANION_PAIRS: Dict[str, str] = {
    "xdm.source.ipv4": "xdm.source.host.ipv4_addresses",
    "xdm.source.host.ipv4_addresses": "xdm.source.ipv4",
    "xdm.target.ipv4": "xdm.target.host.ipv4_addresses",
    "xdm.target.host.ipv4_addresses": "xdm.target.ipv4",
    "xdm.network.application_protocol": "xdm.network.application_protocol_category",
    "xdm.network.application_protocol_category": "xdm.network.application_protocol",
    "xdm.auth.outcome": "xdm.auth.outcome_reason",
    "xdm.event.outcome": "xdm.event.outcome_reason",
}


def _normalize(s: str) -> str:
    """lowercase + non-alphanum → space; useful for fuzzy match."""
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def _score(query_tokens: List[str], path: str, label: str, aliases: List[str]) -> Tuple[str, int]:
    """Score one catalogue entry against the query. Returns (confidence, score)."""
    q = " ".join(query_tokens)
    norm_alias_blob = " ".join(_normalize(a) for a in aliases)
    norm_label = _normalize(label)
    norm_path = _normalize(path)

    # HIGH: substring of the leaf field, or any alias matches the query verbatim.
    leaf = path.rsplit(".", 1)[-1].lower()
    if q == leaf or q in (a.lower() for a in aliases):
        return ("HIGH", 100)
    if q and q in norm_path:
        return ("HIGH", 95)

    # MEDIUM: token overlap with aliases or label.
    overlap = sum(1 for t in query_tokens if t and (t in norm_alias_blob or t in norm_label))
    if overlap >= max(1, len(query_tokens) // 2):
        return ("MEDIUM", 60 + overlap * 5)

    # LOW: any token appears in the path.
    if any(t for t in query_tokens if t and t in norm_path):
        return ("LOW", 30)

    return ("NONE", 0)


def execute(query: str = "", top_k: int = 5, **_unused) -> Dict[str, Any]:
    """Plugin tool entrypoint — kwargs match the manifest's `parameters:` block.

    The plugin runtime spreads params as kwargs via `func(**params)`, so each
    declared parameter must appear here as a typed kwarg. Extras (sandbox,
    future fields) are accepted via **_unused.
    """
    query = (query or "").strip()
    top_k = max(1, min(int(top_k or 5), 10))
    if not query:
        return {"query": query, "matches": [], "advice": "empty query"}

    query_tokens = _normalize(query).split()

    scored = []
    for path, label, aliases in SEED_CATALOGUE:
        conf, score = _score(query_tokens, path, label, aliases)
        if conf == "NONE":
            continue
        scored.append(
            {
                "xdm_path": path,
                "label": label,
                "confidence": conf,
                "score": score,
                "companion": COMPANION_PAIRS.get(path),
                "xdm_const": "xdm" in path
                and any(
                    path.endswith(suffix)
                    for suffix in (".outcome", ".type", ".severity", ".application_protocol_category")
                ),
            }
        )

    # If seed catalogue gave nothing useful, suggest the navigator agent.
    if not scored:
        return {
            "query": query,
            "matches": [],
            "advice": (
                "no HIGH/MEDIUM match in the seed catalogue — try the "
                "xdm-schema-navigator agent for a full §2 scan, or "
                "consult docs/seed/xql/xql-xdm-knowledge.md directly."
            ),
        }

    scored.sort(key=lambda x: x["score"], reverse=True)
    return {
        "query": query,
        "matches": scored[:top_k],
        "advice": None,
    }
