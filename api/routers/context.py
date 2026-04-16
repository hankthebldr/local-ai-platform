#!/usr/bin/env python3
"""
Context Router — Active conversation context endpoints
"""

from fastapi import APIRouter, HTTPException

from ..services.context_store import ContextStore
from ..services.memory_service import MemoryService
from ..services.session_manager import SessionManager

router = APIRouter(prefix="/api/context", tags=["context"])

context_store = ContextStore()
_memory_service = MemoryService()
_session_manager = SessionManager(context_store, _memory_service)


@router.get("")
async def list_active_contexts():
    return context_store.list_active()


@router.get("/{conversation_id}")
async def get_context(conversation_id: str):
    ctx = context_store.get(conversation_id)
    if not ctx:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return ctx.to_dict()


@router.get("/{conversation_id}/tool-calls")
async def get_tool_calls(conversation_id: str):
    ctx = context_store.get(conversation_id)
    if not ctx:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return [tc.to_dict() for tc in ctx.tool_calls]


@router.post("/{conversation_id}/close")
async def close_conversation(conversation_id: str):
    result = _session_manager.close_session(conversation_id)
    if not result:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return result


@router.post("/cleanup")
async def cleanup_stale():
    closed = _session_manager.cleanup_stale(max_age_seconds=300)
    return {"closed": closed}
