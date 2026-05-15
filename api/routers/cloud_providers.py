#!/usr/bin/env python3
"""
Cloud Providers Router — admin-plane CRUD for external/frontier LLM providers.

Surface area is intentionally narrow for the initial shell PR:

  GET    /api/cloud-providers        — list redacted records
  POST   /api/cloud-providers        — register a new provider
  GET    /api/cloud-providers/{id}   — get one redacted record
  PATCH  /api/cloud-providers/{id}   — update fields (api_key rotates the secret)
  DELETE /api/cloud-providers/{id}   — remove

All writes require the master-key dependency so unauthenticated callers
can't ship a record full of API secrets into the on-disk store.
Reads are open (mirrors the plugins/agents/etc. policy: discoverable
metadata, no secrets in the body).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..middleware import require_master_key
from ..models.cloud_provider_models import (
    CloudProviderCreate,
    CloudProviderRedacted,
    CloudProviderUpdate,
)
from ..services import cloud_provider_service as svc

router = APIRouter(prefix="/api/cloud-providers", tags=["cloud-providers"])


@router.get("", response_model=list[CloudProviderRedacted])
async def list_providers():
    return svc.list_providers()


@router.get("/{provider_id}", response_model=CloudProviderRedacted)
async def get_provider(provider_id: str):
    p = svc.get_provider(provider_id)
    if not p:
        raise HTTPException(
            status_code=404, detail=f"cloud provider '{provider_id}' not found"
        )
    return p


@router.post(
    "",
    response_model=CloudProviderRedacted,
    dependencies=[Depends(require_master_key)],
)
async def create_provider(req: CloudProviderCreate):
    try:
        return svc.create_provider(req)
    except ValueError as e:
        # Duplicate ID, validation error — surface as 409 / 400.
        msg = str(e)
        status = 409 if "already exists" in msg else 400
        raise HTTPException(status_code=status, detail=msg)


@router.patch(
    "/{provider_id}",
    response_model=CloudProviderRedacted,
    dependencies=[Depends(require_master_key)],
)
async def update_provider(provider_id: str, req: CloudProviderUpdate):
    updated = svc.update_provider(provider_id, req)
    if not updated:
        raise HTTPException(
            status_code=404, detail=f"cloud provider '{provider_id}' not found"
        )
    return updated


@router.delete("/{provider_id}", dependencies=[Depends(require_master_key)])
async def delete_provider(provider_id: str):
    if not svc.delete_provider(provider_id):
        raise HTTPException(
            status_code=404, detail=f"cloud provider '{provider_id}' not found"
        )
    return {"status": "deleted", "id": provider_id}
