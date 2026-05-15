#!/usr/bin/env python3
"""
Pydantic models for the cloud-provider registry.

Local-first is still the project's posture; these models describe the
external/frontier LLM providers an operator opts into via the Admin
plane. Mirrors the shape of api/models/mcp_models.py — same redacted
list-view + full-record on-disk split that prevents accidental key
leaks into list responses.
"""

from __future__ import annotations

import re
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


# Same shape constraint as MCP IDs / project IDs — alphanum + `_-`,
# 1..64 chars. Used as the URL path segment, so filename-safe.
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class CloudProviderBase(BaseModel):
    """Fields shared by create / update / on-disk record."""

    name: str = Field(
        ..., description="Human-friendly display name (e.g. 'OpenAI · production')"
    )
    kind: str = Field(
        ...,
        description=(
            "Wire-protocol family. 'openai' covers OpenAI itself plus any "
            "OpenAI-compatible base URL (Together, Groq, OpenRouter, "
            "vLLM-OpenAI, etc.). 'anthropic' covers the Anthropic Messages "
            "API shape. 'custom' is the open escape hatch."
        ),
    )
    base_url: str = Field(
        ...,
        description="Absolute URL of the provider's API root (no trailing /v1/...).",
    )
    description: Optional[str] = None
    models: List[str] = Field(
        default_factory=list,
        description=(
            "Optional curated list of model IDs to surface in the chat picker. "
            "Empty list = 'fetch from the provider's /v1/models on first use'."
        ),
    )
    enabled: bool = True
    tags: List[str] = Field(default_factory=list)

    @field_validator("kind")
    @classmethod
    def _validate_kind(cls, v: str) -> str:
        v = (v or "").strip().lower()
        # Permissive: we don't reject unknown kinds today (custom shapes
        # may exist), just normalise. The router can warn on unknowns.
        return v or "custom"

    @field_validator("base_url")
    @classmethod
    def _validate_base_url(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("base_url is required")
        if not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError("base_url must start with http:// or https://")
        return v.rstrip("/")


class CloudProviderCreate(CloudProviderBase):
    """Inbound shape for POST /api/cloud-providers."""

    id: str = Field(
        ..., description="Stable client-supplied id; alphanum + `_-`, 1..64 chars."
    )
    api_key: Optional[str] = Field(
        default=None,
        description="Plain API key. Stored on disk in cleartext (host is the trust boundary).",
    )

    @field_validator("id")
    @classmethod
    def _validate_id(cls, v: str) -> str:
        if not _ID_RE.match(v or ""):
            raise ValueError("id must match [A-Za-z0-9_-]{1,64}")
        return v


class CloudProviderUpdate(BaseModel):
    """Inbound shape for PATCH /api/cloud-providers/{id} — all fields optional."""

    name: Optional[str] = None
    kind: Optional[str] = None
    base_url: Optional[str] = None
    description: Optional[str] = None
    models: Optional[List[str]] = None
    enabled: Optional[bool] = None
    tags: Optional[List[str]] = None
    api_key: Optional[str] = None


class CloudProvider(CloudProviderBase):
    """Internal full record — includes the raw api_key. NEVER returned on the wire."""

    id: str
    api_key: Optional[str] = None


class CloudProviderRedacted(CloudProviderBase):
    """Outbound shape — same as CloudProvider but with the key replaced
    by a boolean ``api_key_set`` so the client can render a 'configured'
    indicator without ever seeing the value."""

    id: str
    api_key_set: bool = False
