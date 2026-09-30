#!/usr/bin/env python3
"""
WorkspaceIndex tests (C3) — durable, resumable worklist state.

Covers: idempotent add, claim/complete lifecycle, resume via requeue_stale,
completion detection, MOC rendering, and persistence across reloads (the
"memory of which items are done" that makes the loop restart-safe).
"""

import pytest

from api.services.workspace import Workspace, WorkspaceMeta, WorkspacePolicy, WorkspaceError
from api.services.workspace_index import WorkspaceIndex


def _ws(tmp_path):
    return Workspace(WorkspaceMeta(name="t", root=str(tmp_path)))


def test_add_is_idempotent(tmp_path):
    idx = WorkspaceIndex(_ws(tmp_path), "sites")
    r1 = idx.add_items([{"url": "https://a.com"}, {"url": "https://b.com"}])
    assert r1["added"] == 2
    r2 = idx.add_items([{"url": "https://a.com"}, {"url": "https://c.com"}])
    assert r2["added"] == 1  # a.com deduped
    assert idx.counts()["total"] == 3


def test_claim_and_complete_lifecycle(tmp_path):
    idx = WorkspaceIndex(_ws(tmp_path), "sites")
    idx.add_items([{"title": "one"}, {"title": "two"}])
    first = idx.next_pending()
    assert first.status == "in_progress"
    idx.set_status(first.id, "done", artifact="notes/one.md")
    assert idx.counts()["done"] == 1
    second = idx.next_pending()
    assert second.id != first.id
    idx.set_status(second.id, "done")
    assert idx.next_pending() is None
    assert idx.is_complete() is True


def test_resume_skips_completed_across_reload(tmp_path):
    ws = _ws(tmp_path)
    idx = WorkspaceIndex(ws, "sites")
    idx.add_items([{"title": "one"}, {"title": "two"}, {"title": "three"}])
    a = idx.next_pending()
    idx.set_status(a.id, "done")
    b = idx.next_pending()  # claimed in_progress, then "crash" (no status set)

    # fresh instance = restart. The in_progress item must be reclaimable.
    idx2 = WorkspaceIndex(ws, "sites")
    assert idx2.counts()["done"] == 1
    assert idx2.counts()["in_progress"] == 1
    requeued = idx2.requeue_stale()
    assert requeued == 1
    # now the loop continues: two pending remain (b and three), one is done
    remaining = [idx2.next_pending(), idx2.next_pending()]
    titles = {i.title for i in remaining if i}
    assert titles == {"two", "three"}
    assert idx2.next_pending() is None


def test_render_markdown_moc(tmp_path):
    ws = _ws(tmp_path)
    idx = WorkspaceIndex(ws, "sites")
    idx.add_items([{"title": "Alpha"}, {"title": "Beta"}])
    done = idx.next_pending()
    idx.set_status(done.id, "done", artifact="notes/alpha.md")
    out = idx.render_markdown()
    text = ws.read(out)
    assert "# sites — index" in text
    assert "1/2 done" in text
    assert "- [x] [[notes/alpha|Alpha]]" in text
    assert "- [ ] Beta" in text


def test_invalid_status_and_missing_item(tmp_path):
    idx = WorkspaceIndex(_ws(tmp_path), "sites")
    idx.add_items([{"title": "one"}])
    item = idx.items()[0]
    with pytest.raises(WorkspaceError):
        idx.set_status(item.id, "bogus")
    with pytest.raises(WorkspaceError):
        idx.set_status("nope", "done")


def test_index_persists_json_in_workspace(tmp_path):
    ws = _ws(tmp_path)
    idx = WorkspaceIndex(ws, "sites")
    idx.add_items([{"title": "one"}])
    assert (ws.root / ".enclave" / "index" / "sites.json").exists()


def test_concurrent_next_pending_no_double_claim(tmp_path):
    """Two threads racing /next must never claim the same item (CR#3)."""
    import threading
    ws = _ws(tmp_path)
    idx = WorkspaceIndex(ws, "sites")
    idx.add_items([{"title": f"s{i}"} for i in range(20)])
    claimed = []
    lock = threading.Lock()

    def worker():
        while True:
            # fresh instance per call == what the router does per request
            it = WorkspaceIndex(ws, "sites").next_pending(claim=True)
            if not it:
                return
            with lock:
                claimed.append(it.id)

    ts = [threading.Thread(target=worker) for _ in range(6)]
    for t in ts: t.start()
    for t in ts: t.join()
    assert len(claimed) == len(set(claimed)) == 20, f"double-claim: {len(claimed)} vs {len(set(claimed))}"


def test_requeue_errors_flips_only_errored_items(tmp_path):
    """requeue_stale leaves `error` alone (no hot-loop on a broken node);
    requeue_errors is the explicit operator retry for exactly those."""
    idx = WorkspaceIndex(_ws(tmp_path), "walk")
    idx.add_items([{"title": "ok"}, {"title": "broken"}, {"title": "later"}])
    a = idx.next_pending()
    idx.set_status(a.id, "done")
    b = idx.next_pending()
    idx.set_status(b.id, "error", note="model down")
    c = idx.next_pending()  # claimed → in_progress
    assert idx.counts()["error"] == 1

    assert idx.requeue_stale() == 1  # only the in_progress one
    assert idx.counts()["error"] == 1
    assert idx.requeue_errors() == 1
    counts = idx.counts()
    assert counts["error"] == 0 and counts["pending"] == 2 and counts["done"] == 1
    assert idx.requeue_errors() == 0  # idempotent
    # Persisted across reload.
    again = WorkspaceIndex(_ws(tmp_path), "walk")
    assert again.counts()["pending"] == 2
    assert {i.id for i in again.items("pending")} == {b.id, c.id}
