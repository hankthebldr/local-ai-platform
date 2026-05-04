"""
Unit tests for the memory ledger surface:
  - PinnedFact gains an `enabled` field
  - update_fact() patches in place
  - get_injection_context() skips disabled facts
  - injection_preview() returns text + per-fact breakdown
  - Legacy facts (no `enabled` key on disk) default to enabled
"""

import pytest
import yaml

from api.services.memory_service import MemoryService


@pytest.fixture
def svc(tmp_path):
    return MemoryService(data_dir=str(tmp_path))


# ── enabled defaults / round-trip ─────────────────────────────────────────


def test_added_fact_is_enabled_by_default(svc):
    fact = svc.add_fact("user prefers dark mode")
    assert fact["enabled"] is True


def test_legacy_fact_without_enabled_key_treated_as_enabled(svc, tmp_path):
    """
    Facts written before this change don't have an `enabled` key on disk.
    The injection path must still include them (default-on for legacy).
    """
    facts_file = tmp_path / "facts.yaml"
    facts_file.write_text(
        yaml.dump({"facts": [{"id": "fact_old", "content": "legacy", "tags": [], "created_at": "x"}]})
    )
    listed = svc.list_facts()
    assert listed[0].get("enabled", True) is True
    assert "legacy" in svc.get_injection_context()


# ── update_fact ───────────────────────────────────────────────────────────


def test_update_fact_patches_content_only(svc):
    f = svc.add_fact("original")
    updated = svc.update_fact(f["id"], content="rewritten")
    assert updated is not None
    assert updated["content"] == "rewritten"
    assert updated["id"] == f["id"]
    # tags / enabled untouched
    assert updated["enabled"] is True
    assert updated["tags"] == []


def test_update_fact_can_disable_without_losing_id(svc):
    f = svc.add_fact("temporary preference")
    updated = svc.update_fact(f["id"], enabled=False)
    assert updated["enabled"] is False
    # Re-enable round-trip
    again = svc.update_fact(f["id"], enabled=True)
    assert again["enabled"] is True
    assert again["id"] == f["id"]


def test_update_fact_unknown_id_returns_none(svc):
    assert svc.update_fact("fact_bogus", content="x") is None


def test_update_fact_with_no_changes_is_noop(svc):
    f = svc.add_fact("hello")
    same = svc.update_fact(f["id"])  # no fields passed
    assert same["content"] == "hello"
    assert same["enabled"] is True


# ── injection context honors enabled ──────────────────────────────────────


def test_injection_context_skips_disabled_facts(svc):
    a = svc.add_fact("always inject me")
    b = svc.add_fact("park me")
    svc.update_fact(b["id"], enabled=False)
    text = svc.get_injection_context()
    assert "always inject me" in text
    assert "park me" not in text


def test_injection_context_empty_when_all_disabled(svc):
    f = svc.add_fact("only fact")
    svc.update_fact(f["id"], enabled=False)
    assert svc.get_injection_context() == ""


# ── injection_preview structure ───────────────────────────────────────────


def test_injection_preview_includes_disabled_facts_marked_not_contributing(svc):
    on = svc.add_fact("active")
    off = svc.add_fact("parked")
    svc.update_fact(off["id"], enabled=False)
    preview = svc.injection_preview()
    # Both facts visible in the breakdown
    by_id = {f["id"]: f for f in preview["facts"]}
    assert by_id[on["id"]]["contributes"] is True
    assert by_id[off["id"]]["contributes"] is False
    # Injection text only has the active one
    assert "active" in preview["injection_text"]
    assert "parked" not in preview["injection_text"]


def test_injection_preview_empty_state(svc):
    preview = svc.injection_preview()
    assert preview["injection_text"] == ""
    assert preview["facts"] == []
