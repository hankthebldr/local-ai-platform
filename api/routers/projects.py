#!/usr/bin/env python3
"""
Projects Router — CRUD + bundle operations for project records.
"""

from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from ..models.project_models import ProjectCreate, ProjectUpdate
from ..services.project_service import get_project_service

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("")
async def list_projects():
    return get_project_service().list_projects()


@router.post("")
async def create_project(body: ProjectCreate):
    try:
        return get_project_service().create_project(body)
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=f"project '{exc}' already exists")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/{project_id}")
async def get_project(project_id: str):
    try:
        result = get_project_service().get_project(project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if result is None:
        raise HTTPException(status_code=404, detail="project not found")
    return result


@router.patch("/{project_id}")
async def update_project(project_id: str, body: ProjectUpdate):
    try:
        return get_project_service().update_project(project_id, body)
    except KeyError:
        raise HTTPException(status_code=404, detail="project not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/{project_id}")
async def delete_project(project_id: str):
    try:
        removed = get_project_service().delete_project(project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not removed:
        raise HTTPException(status_code=404, detail="project not found")
    return {"removed": True, "project_id": project_id}


@router.post("/{project_id}/artifacts/{kind}/{artifact_id}")
async def add_artifact(project_id: str, kind: str, artifact_id: str):
    try:
        return get_project_service().add_artifact(project_id, kind, artifact_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="project not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/{project_id}/artifacts/{kind}/{artifact_id}")
async def remove_artifact(project_id: str, kind: str, artifact_id: str):
    try:
        return get_project_service().remove_artifact(project_id, kind, artifact_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="project not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/{project_id}/export")
async def export_bundle(project_id: str):
    try:
        return get_project_service().export_bundle(project_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="project not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/import")
async def import_bundle(body: Dict[str, Any], overwrite: bool = False):
    try:
        return get_project_service().import_bundle(body, overwrite=overwrite)
    except FileExistsError as exc:
        raise HTTPException(
            status_code=409,
            detail=f"project '{exc}' already exists; pass ?overwrite=true to replace",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
