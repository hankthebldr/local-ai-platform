#!/usr/bin/env python3
"""
Memory Service — YAML persistence for session summaries and pinned facts
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml

from ..logging_config import logger
from ..models.context_models import PinnedFact, SessionSummary


class MemoryService:
    def __init__(self, data_dir: Optional[str] = None):
        self._dir = Path(data_dir) if data_dir else Path("data/memory")
        self._sessions_dir = self._dir / "sessions"
        self._index_file = self._dir / "index.yaml"
        self._facts_file = self._dir / "facts.yaml"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._sessions_dir.mkdir(parents=True, exist_ok=True)

    def save_session(self, summary: SessionSummary) -> None:
        session_file = self._sessions_dir / f"{summary.id}.yaml"
        session_file.write_text(yaml.dump(summary.to_dict(), default_flow_style=False))
        index = self._load_index()
        index = [e for e in index if e["id"] != summary.id]
        index.insert(0, summary.to_index_entry())
        self._save_index(index)
        logger.info(f"Session saved: {summary.id} ({summary.message_count} messages)")

    def list_sessions(self, limit: int = 50, offset: int = 0) -> list:
        index = self._load_index()
        return index[offset:offset + limit]

    def get_session(self, session_id: str) -> Optional[dict]:
        session_file = self._sessions_dir / f"{session_id}.yaml"
        if not session_file.exists():
            return None
        try:
            return yaml.safe_load(session_file.read_text())
        except yaml.YAMLError as e:
            logger.error(f"Failed to load session {session_id}: {e}")
            return None

    def delete_session(self, session_id: str) -> bool:
        session_file = self._sessions_dir / f"{session_id}.yaml"
        if session_file.exists():
            session_file.unlink()
        index = self._load_index()
        new_index = [e for e in index if e["id"] != session_id]
        if len(new_index) == len(index):
            return False
        self._save_index(new_index)
        logger.info(f"Session deleted: {session_id}")
        return True

    def search_sessions(self, query: str) -> list:
        query_lower = query.lower()
        index = self._load_index()
        results = []
        for entry in index:
            preview = entry.get("preview", "").lower()
            topics = [t.lower() for t in entry.get("topics", [])]
            if query_lower in preview or any(query_lower in t for t in topics):
                results.append(entry)
        return results

    def add_fact(self, content: str, tags: list = None, source_conversation: str = None) -> dict:
        fact = PinnedFact(content=content, tags=tags or [], source_conversation=source_conversation)
        facts = self._load_facts()
        facts.append(fact.to_dict())
        self._save_facts(facts)
        logger.info(f"Fact added: {fact.id}")
        return fact.to_dict()

    def list_facts(self) -> list:
        return self._load_facts()

    def delete_fact(self, fact_id: str) -> bool:
        facts = self._load_facts()
        new_facts = [f for f in facts if f["id"] != fact_id]
        if len(new_facts) == len(facts):
            return False
        self._save_facts(new_facts)
        logger.info(f"Fact deleted: {fact_id}")
        return True

    def get_injection_context(self) -> str:
        facts = self._load_facts()
        if not facts:
            return ""
        lines = [f"- {f['content']}" for f in facts]
        return "User memory (pinned facts):\n" + "\n".join(lines)

    def get_stats(self) -> dict:
        index = self._load_index()
        facts = self._load_facts()
        total_tool_calls = sum(e.get("tool_calls_count", 0) for e in index)
        return {
            "total_sessions": len(index),
            "total_facts": len(facts),
            "total_tool_calls": total_tool_calls,
        }

    def _load_index(self) -> list:
        if not self._index_file.exists():
            return []
        data = yaml.safe_load(self._index_file.read_text()) or {}
        return data.get("sessions", [])

    def _save_index(self, sessions: list) -> None:
        self._index_file.write_text(yaml.dump({"sessions": sessions}, default_flow_style=False))

    def _load_facts(self) -> list:
        if not self._facts_file.exists():
            return []
        data = yaml.safe_load(self._facts_file.read_text()) or {}
        return data.get("facts", [])

    def _save_facts(self, facts: list) -> None:
        self._facts_file.write_text(yaml.dump({"facts": facts}, default_flow_style=False))
