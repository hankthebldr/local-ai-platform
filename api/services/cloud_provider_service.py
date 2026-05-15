#!/usr/bin/env python3
"""
Cloud Provider Service — Registry of external/frontier LLM providers.

Local-first remains the default — this service is the **bridge** to
operator-configured cloud providers (OpenAI, Anthropic, Together,
Groq, OpenRouter, etc.). Initial shell scope: CRUD on provider
configs, store API keys, expose redacted listings to clients.

The actual proxy through to /v1/chat/completions for cloud models is
deferred to a follow-up PR; this service is the management surface
the Admin → Cloud Models tab reads/writes against.

Design notes
------------
* Persistence: ``data/config/cloud_providers.json`` (chmod 0600).
  Same host-is-trust-boundary posture as the MCP service — API keys
  are stored in cleartext on disk; the API masks them in responses.
* Each provider record has a stable client-supplied ``id`` (so URLs
  stay deterministic), a free-form display ``name``, a ``kind``
  (openai-compatible / anthropic / etc.), ``base_url``, ``api_key``,
  and an optional ``models[]`` list the operator wants surfaced.
* The ``api_key`` round-trips on the wire as ``api_key_set`` (bool)
  for list / get responses; the raw value is only accepted on
  create / update. To rotate a key the operator re-submits the
  whole record with the new value.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

from ..models.cloud_provider_models import (
    CloudProvider,
    CloudProviderCreate,
    CloudProviderRedacted,
    CloudProviderUpdate,
)

logger = logging.getLogger("local-ai")

# Known provider kinds; "custom" is the open escape hatch for anything
# that speaks OpenAI's /v1/chat/completions shape on a base URL.
KNOWN_KINDS = ("openai", "anthropic", "together", "groq", "openrouter", "custom")


def _config_dir() -> Path:
    """Resolve where on-disk config lives. Mirrors mcp_service."""
    return Path(os.getenv("DATA_CONFIG_DIR", "data/config"))


def _store_path() -> Path:
    return _config_dir() / "cloud_providers.json"


def _read_store() -> list[dict]:
    p = _store_path()
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8") or "[]")
        if not isinstance(data, list):
            logger.warning(f"cloud provider store {p} is not a list — resetting")
            return []
        return data
    except (OSError, json.JSONDecodeError) as e:
        logger.warning(f"failed to read cloud provider store {p}: {e}")
        return []


def _write_store(items: list[dict]) -> None:
    p = _store_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(items, indent=2, sort_keys=False)
    p.write_text(text, encoding="utf-8")
    try:
        p.chmod(0o600)  # API keys live here; defense in depth.
    except OSError:
        pass


def _redact(record: dict) -> dict:
    """Strip the API key from a provider record before serializing to the wire."""
    return {
        **{k: v for k, v in record.items() if k != "api_key"},
        "api_key_set": bool(record.get("api_key")),
    }


# ── Public API ─────────────────────────────────────────────────────────


def list_providers() -> list[CloudProviderRedacted]:
    return [CloudProviderRedacted.model_validate(_redact(r)) for r in _read_store()]


def get_provider(provider_id: str) -> Optional[CloudProviderRedacted]:
    for r in _read_store():
        if r.get("id") == provider_id:
            return CloudProviderRedacted.model_validate(_redact(r))
    return None


def create_provider(req: CloudProviderCreate) -> CloudProviderRedacted:
    items = _read_store()
    if any(r.get("id") == req.id for r in items):
        raise ValueError(f"cloud provider '{req.id}' already exists")
    record = req.model_dump(mode="json", exclude_none=False)
    items.append(record)
    _write_store(items)
    logger.info(
        f"Cloud provider '{req.id}' created (kind={req.kind}, base={req.base_url})"
    )
    return CloudProviderRedacted.model_validate(_redact(record))


def update_provider(
    provider_id: str, req: CloudProviderUpdate
) -> Optional[CloudProviderRedacted]:
    items = _read_store()
    for i, r in enumerate(items):
        if r.get("id") != provider_id:
            continue
        patch = req.model_dump(mode="json", exclude_unset=True)
        # If api_key is sent empty, treat as "no change" — the client
        # uses a separate explicit-null pattern (``api_key: null``) to
        # clear it intentionally.
        if "api_key" in patch and patch["api_key"] == "":
            patch.pop("api_key")
        items[i] = {**r, **patch}
        _write_store(items)
        logger.info(f"Cloud provider '{provider_id}' updated")
        return CloudProviderRedacted.model_validate(_redact(items[i]))
    return None


def delete_provider(provider_id: str) -> bool:
    items = _read_store()
    remaining = [r for r in items if r.get("id") != provider_id]
    if len(remaining) == len(items):
        return False
    _write_store(remaining)
    logger.info(f"Cloud provider '{provider_id}' deleted")
    return True


def get_provider_with_key(provider_id: str) -> Optional[CloudProvider]:
    """Internal accessor used when we *do* need the raw key (proxy path,
    not yet implemented). Kept separate from the public list/get so the
    wire response never accidentally leaks the key."""
    for r in _read_store():
        if r.get("id") == provider_id:
            return CloudProvider.model_validate(r)
    return None
