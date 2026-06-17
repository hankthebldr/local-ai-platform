"""Saved-conversation models — durable chat threads.

The chat "Threads" switcher was session-only ("not persisted across reload —
continuity is a future add"). This is that future add: a thread is snapshotted
to ``data/conversations/{id}.json`` so it survives reloads and restarts.

A saved conversation carries the message history (the source of truth) plus an
optional rendered-HTML snapshot for fast exact restore and the pinned snippets.
On a single-operator appliance the operator owns all of this data locally.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class SavedConversation(BaseModel):
    """One persisted chat thread."""

    id: str
    title: str = "Thread"
    model: Optional[str] = None
    pinned: bool = False
    # The chatHistory array verbatim ({role, content, ...}); the source of
    # truth. Kept loose so the client can round-trip whatever it tracks.
    messages: List[Dict[str, Any]] = Field(default_factory=list)
    # Optional rendered-HTML snapshot for exact restore (capped client-side).
    html: Optional[str] = None
    # Pinned snippets (workflow-step candidates) carried with the thread.
    pins: List[Any] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def summary(self) -> Dict[str, Any]:
        """Lightweight listing row (no message bodies / html)."""
        return {
            "id": self.id,
            "title": self.title,
            "model": self.model,
            "pinned": self.pinned,
            "message_count": len(self.messages),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
