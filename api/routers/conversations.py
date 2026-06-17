#!/usr/bin/env python3
"""
Conversations Router — durable chat threads.

POST   /api/conversations         → upsert a saved thread
GET    /api/conversations         → list thread summaries (newest first)
GET    /api/conversations/{id}     → full thread (messages + html + pins)
DELETE /api/conversations/{id}     → delete a thread

Backs the chat "Threads" switcher so threads survive reload. Single-operator
appliance: all data is local and operator-owned.
"""

from fastapi import APIRouter, HTTPException

from ..models.conversation_models import SavedConversation
from ..services.conversation_store import get_conversation_store

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


@router.post("")
async def upsert_conversation(conv: SavedConversation):
    """Create or update a saved thread (idempotent on id)."""
    store = get_conversation_store()
    try:
        saved = store.save(conv)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {
        "status": "saved",
        "id": saved.id,
        "updated_at": saved.updated_at.isoformat(),
    }


@router.get("")
async def list_conversations():
    store = get_conversation_store()
    rows = store.list()
    return {"total": len(rows), "conversations": rows}


@router.get("/{conversation_id}")
async def get_conversation(conversation_id: str):
    store = get_conversation_store()
    conv = store.get(conversation_id)
    if conv is None:
        raise HTTPException(
            status_code=404, detail=f"conversation {conversation_id!r} not found"
        )
    return conv.model_dump(mode="json")


@router.delete("/{conversation_id}")
async def delete_conversation(conversation_id: str):
    store = get_conversation_store()
    if not store.delete(conversation_id):
        raise HTTPException(
            status_code=404, detail=f"conversation {conversation_id!r} not found"
        )
    return {"status": "deleted", "id": conversation_id}
