#!/usr/bin/env python3
"""
API Key Service — CRUD, hashing, validation, YAML persistence
"""

import collections
import hashlib
import os
import secrets
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class APIKeyService:
    def __init__(self, config_dir: Optional[str] = None):
        if config_dir:
            self._config_dir = Path(config_dir)
        else:
            self._config_dir = Path(os.getenv("DATA_CONFIG_DIR", "data/config"))
        self._config_dir.mkdir(parents=True, exist_ok=True)
        self._file = self._config_dir / "api_keys.yaml"
        # In-memory cache invalidated by file mtime to avoid repeated disk I/O.
        self._cache: Optional[list] = None
        self._cache_mtime: Optional[float] = None
        # Audit ring buffer — capacity 200, lost on restart. Persistent storage
        # is intentionally out of scope (see ENTERPRISE_DEPLOYMENT_GAPS.md).
        self._audit: collections.deque = collections.deque(maxlen=200)

    def _load(self) -> list:
        if not self._file.exists():
            self._cache = []
            self._cache_mtime = None
            return []

        current_mtime = self._file.stat().st_mtime
        if self._cache is not None and self._cache_mtime == current_mtime:
            return self._cache

        data = yaml.safe_load(self._file.read_text()) or {}
        self._cache = data.get("keys", [])
        self._cache_mtime = current_mtime
        return self._cache

    def _save(self, keys: list) -> None:
        self._file.write_text(yaml.dump({"keys": keys}, default_flow_style=False))
        self._cache = keys
        self._cache_mtime = self._file.stat().st_mtime

    def _log(self, action: str, key_id: str, name: Optional[str] = None) -> None:
        """Append an admin-action event to the in-memory audit ring buffer."""
        self._audit.append({
            "ts": _now_iso(),
            "action": action,
            "key_id": key_id,
            "name": name,
        })

    def create_key(self, name: str, scopes: list, rate_limit_rpm: Optional[int] = None, expires_at: Optional[str] = None) -> dict:
        slug = _slug(name)
        random_part = secrets.token_hex(16)
        raw_key = f"sk-{slug}-{random_part}"
        prefix = f"sk-{slug}-"
        key_id = f"key_{secrets.token_hex(6)}"

        entry = {
            "id": key_id, "name": name, "key_hash": _hash_key(raw_key),
            "prefix": prefix, "last_four": raw_key[-4:],
            "created_at": _now_iso(), "last_used_at": None,
            "expires_at": expires_at, "rate_limit_rpm": rate_limit_rpm,
            "scopes": scopes, "enabled": True,
            "usage": {"total_requests": 0, "total_tokens": 0},
        }

        keys = self._load()
        keys.append(entry)
        self._save(keys)
        self._log("created", key_id, name)
        return {"id": key_id, "name": name, "key": raw_key, "scopes": scopes}

    def validate_key(self, raw_key: str) -> Optional[dict]:
        key_hash = _hash_key(raw_key)
        keys = self._load()
        for k in keys:
            if k["key_hash"] == key_hash:
                if not k["enabled"]:
                    return None
                if k.get("expires_at"):
                    expires = datetime.fromisoformat(k["expires_at"].replace("Z", "+00:00"))
                    if expires.tzinfo is None:
                        expires = expires.replace(tzinfo=timezone.utc)
                    if datetime.now(timezone.utc) > expires:
                        return None
                return {"id": k["id"], "name": k["name"], "scopes": k["scopes"], "rate_limit_rpm": k.get("rate_limit_rpm")}
        return None

    def revoke_key(self, key_id: str) -> bool:
        keys = self._load()
        for k in keys:
            if k["id"] == key_id:
                k["enabled"] = False
                self._save(keys)
                self._log("revoked", key_id, k.get("name"))
                return True
        return False

    def rotate_key(self, key_id: str) -> dict:
        keys = self._load()
        old = None
        for k in keys:
            if k["id"] == key_id:
                old = k
                break
        if not old:
            raise ValueError(f"Key not found: {key_id}")
        self.revoke_key(key_id)
        self._log("rotated", key_id, old.get("name"))
        return self.create_key(name=old["name"], scopes=old["scopes"], rate_limit_rpm=old.get("rate_limit_rpm"), expires_at=old.get("expires_at"))

    def list_keys(self) -> list:
        keys = self._load()
        return [{
            "id": k["id"], "name": k["name"], "prefix": k["prefix"],
            "last_four": k.get("last_four", ""), "created_at": k["created_at"],
            "last_used_at": k.get("last_used_at"), "expires_at": k.get("expires_at"),
            "rate_limit_rpm": k.get("rate_limit_rpm"), "scopes": k["scopes"],
            "enabled": k["enabled"],
            "usage": k.get("usage", {"total_requests": 0, "total_tokens": 0}),
        } for k in keys]

    def update_usage(self, key_id: str, tokens_used: int = 0) -> None:
        keys = self._load()
        for k in keys:
            if k["id"] == key_id:
                usage = k.setdefault("usage", {"total_requests": 0, "total_tokens": 0})
                usage["total_requests"] += 1
                usage["total_tokens"] += tokens_used
                k["last_used_at"] = _now_iso()
                self._save(keys)
                return


# ── First-run bootstrap ───────────────────────────────────────────────────
#
# When the operator enables auth on a fresh install, they shouldn't have to
# manually provision a key before the API works. This helper auto-creates a
# master key on first start (idempotent: returns None if any key already
# exists or if API_KEY is set in env).

ALL_SCOPES = [
    "chat", "completions", "models",
    "documents", "memory", "context",
    "profiles", "plugins", "workflows",
    "keys", "a2a",
]


def bootstrap_first_run_key(svc: "APIKeyService") -> Optional[dict]:
    """
    Provision a master key if and only if the keystore is empty AND no
    legacy API_KEY env var is set. Returns the {id, name, key, scopes}
    dict on creation, or None if no provisioning was needed.

    The raw key is included in the return so the caller can write it to
    a sentinel file and log it once — it cannot be retrieved later.
    """
    if os.getenv("API_KEY"):
        return None
    if svc.list_keys():
        return None
    return svc.create_key(
        name="first-run-master",
        scopes=ALL_SCOPES,
        rate_limit_rpm=None,
    )
