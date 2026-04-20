#!/usr/bin/env python3
"""
Session Manager — Handles conversation lifecycle and auto-save
"""

from __future__ import annotations

from datetime import datetime, timezone

from ..logging_config import logger
from ..models.context_models import SessionSummary
from .context_store import ContextStore
from .memory_service import MemoryService


class SessionManager:
    def __init__(self, context_store: ContextStore, memory_service: MemoryService):
        self.context_store = context_store
        self.memory_service = memory_service

    def close_session(self, conversation_id: str, preview: str = ""):
        ctx = self.context_store.remove(conversation_id)
        if not ctx:
            return None
        summary = SessionSummary.from_context(ctx, preview=preview)

        # Preserve profile ID in metadata if present
        if ctx.metadata.get("profile_id"):
            summary.metadata["profile_id"] = ctx.metadata["profile_id"]

        # Archive sandbox contents (file list only) then delete the directory
        import shutil
        from pathlib import Path
        sandbox_dir = Path(f"data/sandboxes/{conversation_id}")
        if sandbox_dir.exists():
            files = []
            for f in sandbox_dir.rglob("*"):
                if f.is_file():
                    files.append({
                        "path": str(f.relative_to(sandbox_dir)),
                        "size": f.stat().st_size,
                    })
            summary.metadata["sandbox_files"] = files
            try:
                shutil.rmtree(sandbox_dir)
            except OSError as e:
                logger.warning(f"Could not remove sandbox dir {sandbox_dir}: {e}")

        self.memory_service.save_session(summary)
        logger.info(f"Session closed and saved: {conversation_id}")
        return summary.to_dict()

    def cleanup_stale(self, max_age_seconds: int = 300) -> int:
        now = datetime.now(timezone.utc)
        closed = 0
        for ctx_dict in self.context_store.list_active():
            last = datetime.fromisoformat(ctx_dict["last_activity"])
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            age = (now - last).total_seconds()
            if age > max_age_seconds:
                self.close_session(ctx_dict["conversation_id"], preview=ctx_dict.get("preview", ""))
                closed += 1
        return closed
