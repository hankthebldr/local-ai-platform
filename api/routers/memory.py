#!/usr/bin/env python3
"""
Memory Router — Persisted session and fact management endpoints
"""

from typing import Optional, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..services.memory_service import MemoryService

router = APIRouter(prefix="/api/memory", tags=["memory"])

memory_service = MemoryService()


class AddFactRequest(BaseModel):
    content: str = Field(..., description="The fact to pin")
    tags: List[str] = Field(default_factory=list, description="Optional tags")
    source_conversation: Optional[str] = Field(None, description="Source conversation ID")


class SearchRequest(BaseModel):
    query: str = Field(..., description="Search query")


@router.get("/sessions")
async def list_sessions(limit: int = 50, offset: int = 0):
    return memory_service.list_sessions(limit=limit, offset=offset)


@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    session = memory_service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    if not memory_service.delete_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    return {"status": "deleted", "id": session_id}


@router.post("/sessions/search")
async def search_sessions(body: SearchRequest):
    return memory_service.search_sessions(body.query)


@router.get("/facts")
async def list_facts():
    return memory_service.list_facts()


@router.post("/facts", status_code=201)
async def add_fact(body: AddFactRequest):
    return memory_service.add_fact(
        content=body.content, tags=body.tags,
        source_conversation=body.source_conversation,
    )


@router.delete("/facts/{fact_id}")
async def delete_fact(fact_id: str):
    if not memory_service.delete_fact(fact_id):
        raise HTTPException(status_code=404, detail="Fact not found")
    return {"status": "deleted", "id": fact_id}


@router.get("/stats")
async def memory_stats():
    return memory_service.get_stats()
