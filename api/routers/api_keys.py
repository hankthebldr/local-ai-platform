#!/usr/bin/env python3
"""
API Keys Router — Key management endpoints (master key protected)
"""

from typing import Optional, List

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..middleware import require_master_key as _require_master
from ..services.api_key_service import APIKeyService

router = APIRouter(prefix="/api/keys", tags=["api-keys"])
_service = APIKeyService()


class CreateKeyRequest(BaseModel):
    name: str = Field(..., description="Human-readable key name")
    scopes: List[str] = Field(..., description="Endpoint access scopes")
    rate_limit_rpm: Optional[int] = Field(None, description="Per-key rate limit")
    expires_at: Optional[str] = Field(None, description="ISO 8601 expiration")


@router.post("", status_code=201)
async def create_key(body: CreateKeyRequest, request: Request):
    _require_master(request)
    result = _service.create_key(
        name=body.name, scopes=body.scopes,
        rate_limit_rpm=body.rate_limit_rpm, expires_at=body.expires_at,
    )
    return result


@router.get("")
async def list_keys(request: Request):
    _require_master(request)
    return _service.list_keys()


@router.get("/scopes")
async def list_scopes(request: Request):
    """Return the scope identifiers known to the middleware.

    Master-key gated for consistency with the rest of /api/keys/*.
    """
    _require_master(request)
    from ..middleware import SCOPE_MAP
    # SCOPE_MAP values are scope names; deduplicate while preserving insertion order.
    scopes = list(dict.fromkeys(SCOPE_MAP.values()))
    return {"scopes": scopes}


@router.get("/audit")
async def get_audit(request: Request):
    """Return the in-memory audit log (last 200 events). Master-key gated."""
    _require_master(request)
    return list(_service._audit)


@router.delete("/{key_id}")
async def revoke_key(key_id: str, request: Request):
    _require_master(request)
    if not _service.revoke_key(key_id):
        raise HTTPException(status_code=404, detail="Key not found")
    return {"status": "revoked", "id": key_id}


@router.post("/{key_id}/rotate")
async def rotate_key(key_id: str, request: Request):
    _require_master(request)
    try:
        result = _service.rotate_key(key_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Key not found")
    return result


@router.get("/{key_id}/usage")
async def get_usage(key_id: str, request: Request):
    _require_master(request)
    keys = _service.list_keys()
    for k in keys:
        if k["id"] == key_id:
            return k["usage"]
    raise HTTPException(status_code=404, detail="Key not found")
