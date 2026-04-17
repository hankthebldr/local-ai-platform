#!/usr/bin/env python3
"""
Profiles Router — Read-only profile management endpoints.

Profiles are edited as YAML files in data/profiles/. POST /api/profiles/reload
re-scans the directory to pick up changes.
"""

import os
from fastapi import APIRouter, HTTPException

from ..services.profile_service import ProfileService

router = APIRouter(prefix="/api/profiles", tags=["profiles"])

profile_service = ProfileService()
profile_service.load_profiles()


@router.get("")
async def list_profiles():
    """List all loaded profiles."""
    return profile_service.list_profiles()


@router.get("/active")
async def get_active_default():
    """Return the configured default profile ID."""
    default_id = os.getenv("DEFAULT_PROFILE", "default")
    return {"default_profile_id": default_id}


@router.get("/{profile_id}")
async def get_profile(profile_id: str):
    """Return full profile detail."""
    profile = profile_service.get_profile(profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile


@router.post("/reload")
async def reload_profiles():
    """Re-scan data/profiles/ for changes."""
    loaded = profile_service.reload()
    return {"loaded": len(loaded), "ids": [p["id"] for p in loaded]}
