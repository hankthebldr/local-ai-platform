"""Conversation store — durable chat threads on disk.

Same idiom as workflow_engine's run persistence: one JSON file per
conversation, written atomically (tmp + os.replace). Listing scans the
directory and returns lightweight summaries so the thread switcher loads
fast without reading every transcript.

Layout::

    {CONVERSATION_DATA_DIR}/{id}.json   # one SavedConversation per file
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from ..logging_config import logger
from ..models.conversation_models import SavedConversation

CONVERSATION_DATA_DIR = os.getenv("CONVERSATION_DATA_DIR", "./data/conversations")

# Thread ids become filenames; reject anything that could escape the dir.
_SAFE_ID_CHARS = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_."
)


def _safe_id(cid: str) -> str:
    c = (cid or "").strip()
    if not c or c in (".", "..") or not all(ch in _SAFE_ID_CHARS for ch in c):
        raise ValueError(f"unsafe conversation id: {cid!r}")
    return c


class ConversationStore:
    """Persist, list, retrieve, and delete saved chat threads."""

    def __init__(self, base_dir: Optional[str] = None):
        self.base = Path(base_dir or CONVERSATION_DATA_DIR)

    def _path(self, cid: str) -> Path:
        return self.base / f"{_safe_id(cid)}.json"

    # ── Write ────────────────────────────────────────────────────────────

    def save(self, conv: SavedConversation) -> SavedConversation:
        """Upsert a conversation. Preserves created_at if one already exists."""
        cid = _safe_id(conv.id)
        self.base.mkdir(parents=True, exist_ok=True)
        path = self._path(cid)
        if path.exists():
            existing = self.get(cid)
            if existing is not None:
                conv.created_at = existing.created_at
        conv.updated_at = datetime.now(timezone.utc)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(conv.model_dump(mode="json"), indent=2, default=str),
            encoding="utf-8",
        )
        os.replace(tmp, path)
        return conv

    # ── Read ─────────────────────────────────────────────────────────────

    def get(self, cid: str) -> Optional[SavedConversation]:
        try:
            path = self._path(cid)
        except ValueError:
            return None
        if not path.exists():
            return None
        try:
            return SavedConversation.model_validate_json(
                path.read_text(encoding="utf-8")
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"conversation_store: failed to read {cid!r}: {exc}")
            return None

    def list(self) -> List[dict]:
        """Return lightweight summaries, newest-updated first."""
        if not self.base.exists():
            return []
        rows: List[SavedConversation] = []
        for f in self.base.glob("*.json"):
            try:
                rows.append(
                    SavedConversation.model_validate_json(f.read_text(encoding="utf-8"))
                )
            except Exception:  # noqa: BLE001
                continue
        rows.sort(key=lambda c: str(c.updated_at), reverse=True)
        return [c.summary() for c in rows]

    # ── Delete ───────────────────────────────────────────────────────────

    def delete(self, cid: str) -> bool:
        try:
            path = self._path(cid)
        except ValueError:
            return False
        if not path.exists():
            return False
        path.unlink()
        return True


_store: Optional[ConversationStore] = None


def get_conversation_store() -> ConversationStore:
    global _store
    if _store is None:
        _store = ConversationStore()
    return _store
