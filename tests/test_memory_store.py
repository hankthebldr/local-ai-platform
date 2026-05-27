"""Unit tests for MemoryStore — the durable cross-run memory backing
kind=consolidate steps and $memory.* accessors."""

import json

import pytest

from api.services.memory_store import MemoryStore, _normalize_block, _safe_name


@pytest.fixture
def store(tmp_path):
    return MemoryStore(base_dir=str(tmp_path))


class TestPlaybook:
    def test_empty_read_returns_empty_string(self, store):
        assert store.read_playbook("nope") == ""

    def test_replace_overwrites(self, store):
        store.write_playbook("inc", "first content", strategy="replace")
        store.write_playbook("inc", "second content", strategy="replace")
        body = store.read_playbook("inc")
        assert "second content" in body
        assert "first content" not in body

    def test_append_keeps_both(self, store):
        store.write_playbook("inc", "rule one", strategy="replace")
        store.write_playbook("inc", "rule two", strategy="append")
        body = store.read_playbook("inc")
        assert "rule one" in body
        assert "rule two" in body

    def test_append_with_dedup_skips_duplicate(self, store):
        store.write_playbook("inc", "Rule: check logs", strategy="replace")
        store.write_playbook("inc", "Rule: check logs", strategy="append_with_dedup")
        body = store.read_playbook("inc")
        # Only one occurrence despite two writes.
        assert body.count("Rule: check logs") == 1

    def test_append_with_dedup_adds_novel(self, store):
        store.write_playbook("inc", "Rule: check logs", strategy="replace")
        store.write_playbook(
            "inc", "Rule: escalate criticals", strategy="append_with_dedup"
        )
        body = store.read_playbook("inc")
        assert "check logs" in body
        assert "escalate criticals" in body

    def test_dedup_is_case_and_whitespace_insensitive(self, store):
        store.write_playbook("inc", "Rule: Check Logs", strategy="replace")
        store.write_playbook(
            "inc", "  rule:   check logs  ", strategy="append_with_dedup"
        )
        body = store.read_playbook("inc")
        # The normalized form matches, so nothing new is appended.
        assert body.lower().count("check logs") == 1


class TestSemantic:
    def test_write_and_read(self, store):
        store.write_semantic(
            "xdm_timestamps",
            "data_received_time is the canonical XDM timestamp",
            strategy="replace",
        )
        assert "canonical XDM timestamp" in store.read_semantic("xdm_timestamps")


class TestEpisodic:
    def test_append_and_read(self, store):
        store.append_episodic("inc", "digest A", run_id="r1")
        store.append_episodic("inc", "digest B", run_id="r2")
        records = store.read_episodic("inc")
        assert len(records) == 2
        assert [r["run_id"] for r in records] == ["r1", "r2"]
        assert records[0]["content"] == "digest A"

    def test_read_limit_returns_most_recent(self, store):
        for i in range(5):
            store.append_episodic("inc", f"digest {i}", run_id=f"r{i}")
        records = store.read_episodic("inc", limit=2)
        assert [r["run_id"] for r in records] == ["r3", "r4"]

    def test_digest_renders_recent(self, store):
        store.append_episodic("inc", "older event", run_id="r1")
        store.append_episodic("inc", "newer event", run_id="r2")
        digest = store.read_episodic_digest("inc", limit=1)
        assert "newer event" in digest
        assert "older event" not in digest

    def test_corrupt_line_is_skipped(self, store):
        path = store.episodic_path("inc")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"run_id": "ok", "content": "good"})
            + "\nnot valid json\n"
            + json.dumps({"run_id": "ok2", "content": "good2"})
            + "\n",
            encoding="utf-8",
        )
        records = store.read_episodic("inc")
        assert [r["run_id"] for r in records] == ["ok", "ok2"]


class TestSafety:
    def test_safe_name_strips_traversal(self):
        assert "/" not in _safe_name("../../etc/passwd")
        assert ".." not in _safe_name("../../etc/passwd")

    def test_safe_name_empty_falls_back(self):
        assert _safe_name("") == "default"
        assert _safe_name("///") == "default"

    def test_traversal_write_stays_in_base(self, store, tmp_path):
        store.write_semantic("../../escape", "nope", strategy="replace")
        # Nothing escaped the base dir.
        written = list(tmp_path.rglob("*.md"))
        assert all(str(tmp_path) in str(p) for p in written)

    def test_normalize_block(self):
        a = _normalize_block("  Rule: Check Logs  \n\n")
        b = _normalize_block("rule: check logs")
        assert a == b


class TestAtomicWrite:
    def test_no_tmp_files_left_after_write(self, store, tmp_path):
        store.write_playbook("inc", "content", strategy="replace")
        leftover_tmp = list(tmp_path.rglob("*.tmp"))
        assert leftover_tmp == []
