"""
Schema loader — loads the upstream JSON snapshots into Python sets/maps
that mirror the TypeScript module-level state in rules-engine.ts.

Source data lives in _data/{xdm_schema,xql_functions,xql_schema}.json
(one-shot exports from the upstream TS modules). Re-run scripts/
update_xql_data.py to refresh.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_DATA_DIR = Path(__file__).resolve().parent / "_data"


@lru_cache(maxsize=None)
def _load(name: str) -> dict:
    return json.loads((_DATA_DIR / f"{name}.json").read_text(encoding="utf-8"))


# ── XDM schema ────────────────────────────────────────────────────────

def xdm_fields() -> list[dict]:
    return _load("xdm_schema")["xdmSchema"]


def xdm_consts() -> dict[str, list[str]]:
    """XDM_CONST name -> legal values list."""
    raw = _load("xdm_schema")["xdmConsts"]
    return {c["name"]: [v["value"] for v in c["values"]] for c in raw}


@lru_cache(maxsize=1)
def known_xdm_paths() -> frozenset[str]:
    return frozenset(f["name"] for f in xdm_fields() if f["name"].startswith("xdm."))


@lru_cache(maxsize=1)
def array_xdm_paths() -> frozenset[str]:
    return frozenset(
        f["name"] for f in xdm_fields()
        if f["name"].startswith("xdm.") and f.get("dataclass") == "Array"
    )


@lru_cache(maxsize=1)
def xdm_const_paths() -> dict[str, str]:
    """xdm.path -> XDM_CONST.NAME (only for XDM_CONST-typed fields)."""
    return {
        f["name"]: f["type"]
        for f in xdm_fields()
        if f["name"].startswith("xdm.") and f.get("type", "").startswith("XDM_CONST.")
    }


def is_valid_xdm_path(field_path: str) -> bool:
    """TS: isValidXdmPath. Exact match OR known-path prefix + '.'."""
    known = known_xdm_paths()
    if field_path in known:
        return True
    for prefix in known:
        if field_path.startswith(prefix + "."):
            return True
    return False


def xdm_field_type(field_path: str) -> str | None:
    for f in xdm_fields():
        if f["name"] == field_path:
            return f.get("type")
    return None


def xdm_field_enum(field_path: str) -> list[str] | None:
    """Return the legal values for an XDM_CONST-typed field, else None."""
    t = xdm_field_type(field_path)
    if not t or not t.startswith("XDM_CONST."):
        return None
    return xdm_consts().get(t.split(".", 1)[1])


# Top-level XDM categories accepted by ERR-006. Sourced from the source
# `KNOWN_XDM_CATEGORIES` set (rules-engine.ts line 41).
KNOWN_XDM_CATEGORIES: frozenset[str] = frozenset({
    "alert", "auth", "database", "email", "event",
    "intermediate", "logon", "network", "observer",
    "source", "target", "session",
    "active_directory", "appsec", "backlog_status", "code", "disk",
    "domain", "http", "identity", "malware", "secret",
    "security_control", "software_package", "vulnerability",
})


# ── XQL functions / stages / operators ────────────────────────────────

@lru_cache(maxsize=1)
def known_xql_functions() -> frozenset[str]:
    funcs = {f["name"] for f in _load("xql_functions")["xqlFunctions"]}
    stages = {s["name"] for s in _load("xql_functions")["xqlStages"]}
    # The rules-engine.ts KNOWN_XQL_FUNCTIONS set unions both.
    return frozenset(funcs | stages)


@lru_cache(maxsize=1)
def known_xql_stages() -> frozenset[str]:
    return frozenset(s["name"] for s in _load("xql_functions")["xqlStages"])


# ── XDM type metadata (Task #113) ─────────────────────────────────────
# Mirrors xdm-schema.ts:getXdmFieldType / getXdmFieldEnum.

_SCALAR_BASE_BY_TYPE: dict[str, str] = {
    "String": "string",
    "Boolean": "bool",
    "Number": "int",
    "Float": "float",
    "IPv4": "ipv4",
    "IPv6": "ipv6",
    "Timestamp": "timestamp",
    "EmailAddress": "email",
    "URL": "url",
    "MD5": "md5",
    "SHA256": "sha256",
}


@lru_cache(maxsize=1)
def _enum_values_by_const() -> dict[str, list[str]]:
    raw = _load("xdm_schema")["xdmConsts"]
    m: dict[str, list[str]] = {}
    for c in raw:
        tokens: list[str] = []
        for row in c["values"]:
            if row.get("value") == "Original" and row.get("description") == "Mapped":
                continue
            desc = row.get("description") or ""
            if desc.startswith("XDM_CONST."):
                tokens.append(desc)
            val = row.get("value") or ""
            if val and not val.startswith("XDM_CONST."):
                tokens.append(val)
        # Preserve order, drop duplicates.
        seen: set[str] = set()
        uniq: list[str] = []
        for t in tokens:
            if t not in seen:
                seen.add(t)
                uniq.append(t)
        m[c["name"]] = uniq
    return m


def _derive_scalar_or_enum(type_str: str) -> dict:
    if type_str.startswith("XDM_CONST."):
        values = _enum_values_by_const().get(type_str, [])
        return {"kind": "enum", "constName": type_str, "values": values}
    base = _SCALAR_BASE_BY_TYPE.get(type_str, "string")
    return {"kind": "scalar", "base": base}


@lru_cache(maxsize=1)
def _type_meta_by_path() -> dict[str, dict]:
    m: dict[str, dict] = {}
    for f in xdm_fields():
        name = f["name"]
        if not name.startswith("xdm."):
            continue
        inner = _derive_scalar_or_enum(f.get("type", "String"))
        if f.get("dataclass") == "Array":
            m[name] = {"kind": "array", "element": inner}
        else:
            m[name] = inner
    return m


def get_xdm_field_type(path: str) -> dict | None:
    """Return type metadata dict for an xdm.* path: scalar/enum/array."""
    return _type_meta_by_path().get(path)


def get_xdm_field_enum(path: str) -> list[str] | None:
    """Closed enum vocabulary (XDM_CONST + raw values) for the path, or None."""
    meta = _type_meta_by_path().get(path)
    if not meta:
        return None
    if meta.get("kind") == "enum":
        return meta["values"]
    if meta.get("kind") == "array":
        elem = meta.get("element", {})
        if elem.get("kind") == "enum":
            return elem["values"]
    return None


# Source-of-truth version constants (rules-engine.ts lines 58-60).
XDM_SCHEMA_VERSION = "2026-04-21"
XDM_SCHEMA_SOURCE = (
    "Cortex XSIAM XDM Schema Reference (mirrored in PRIVATE_DOCS/XDM_SCHEMA/)"
)
