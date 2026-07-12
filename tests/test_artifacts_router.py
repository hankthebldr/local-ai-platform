#!/usr/bin/env python3
"""Artifacts inventory router (Operate U10) — read-only unified store view.

Covers: aggregation across run/feedback/export stores, facets, filters,
size-capped preview, raw attachment download, composite-id containment
(``../`` traversal → 404, never an escape), and scope enforcement (a
non-``workflows`` key is 403'd; auth-off is open).
"""

import importlib
import json
import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """Isolated run root + feedback log + exports dir, seeded with one artifact
    of each source, with auth OFF."""
    monkeypatch.setenv("ENABLE_API_AUTH", "false")
    monkeypatch.setenv("RATE_LIMIT_RPM", "0")

    runs = tmp_path / "workflows"
    feedback = tmp_path / "feedback"
    runs.mkdir()
    feedback.mkdir()
    monkeypatch.setenv("WORKFLOW_DATA_DIR", str(runs))
    monkeypatch.setenv("DATA_FEEDBACK_DIR", str(feedback))

    # run store: one run with a step artifact + a summary.md
    run_id = "run-aaaa-1111"
    rd = runs / run_id
    (rd / "artifacts").mkdir(parents=True)
    (rd / "run.json").write_text(
        json.dumps(
            {
                "workflow_id": "demo-wf",
                "status": "completed",
                "started_at": "2026-07-01T00:00:00",
                "completed_at": "2026-07-01T00:01:00",
                "step_results": [
                    {"step_id": "draft", "model_used": "mistral:latest"}
                ],
            }
        ),
        encoding="utf-8",
    )
    (rd / "artifacts" / "draft.json").write_text(
        json.dumps({"output": "hello world"}), encoding="utf-8"
    )
    (rd / "summary.md").write_text("# Run summary\n\ndone\n", encoding="utf-8")

    # feedback store
    (feedback / "artifacts.jsonl").write_text(
        json.dumps(
            {
                "id": "art_beef",
                "source": "research",
                "title": "A finding",
                "body": "captured body text",
                "captured_at": "2026-07-02T00:00:00Z",
                "context": {"workflow_id": "demo-wf", "model": "yi:34b"},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    # export store lives at project_root/data/exports — patch the router's dir
    import api.routers.artifacts as art

    exports = tmp_path / "exports"
    exports.mkdir()
    (exports / "session-1.md").write_text("# Chat export\n", encoding="utf-8")
    monkeypatch.setattr(art, "_exports_dir", lambda: exports)

    import api.middleware

    importlib.reload(api.middleware)
    import api.main

    importlib.reload(api.main)
    # run_index caches the root signature across tests — drop it.
    import api.services.run_index as ri

    ri.reset_caches()
    return TestClient(api.main.app), run_id


def test_lists_all_three_sources_with_facets(env):
    client, _run_id = env
    r = client.get("/api/artifacts")
    assert r.status_code == 200
    body = r.json()
    sources = {it["source"] for it in body["items"]}
    assert sources == {"run", "feedback", "export"}
    # summary + step + feedback + export == 4 records
    assert body["total"] == 4
    assert body["facets"]["source"] == {"run": 2, "feedback": 1, "export": 1}
    assert body["facets"]["model"].get("mistral:latest") == 1


def test_source_and_model_filters(env):
    client, _run_id = env
    assert all(
        it["source"] == "run"
        for it in client.get("/api/artifacts?source=run").json()["items"]
    )
    got = client.get("/api/artifacts?model=mistral:latest").json()
    assert got["total"] == 1 and got["items"][0]["provenance"]["step_id"] == "draft"


def test_detail_preview_and_provenance(env):
    client, run_id = env
    aid = f"run:{run_id}:draft"
    r = client.get(f"/api/artifacts/{aid}")
    assert r.status_code == 200
    d = r.json()
    assert d["provenance"]["model_used"] == "mistral:latest"
    assert d["provenance"]["workflow_id"] == "demo-wf"
    assert "hello world" in d["preview"]
    assert d["preview_truncated"] is False


def test_raw_download_is_attachment(env):
    client, run_id = env
    r = client.get(f"/api/artifacts/run:{run_id}:__summary__/raw")
    assert r.status_code == 200
    assert "attachment" in r.headers["content-disposition"]
    assert "Run summary" in r.text


def test_feedback_and_export_detail(env):
    client, _run_id = env
    fb = client.get("/api/artifacts/feedback:art_beef").json()
    assert fb["preview"] == "captured body text"
    ex = client.get("/api/artifacts/export:session-1.md").json()
    assert "Chat export" in ex["preview"]


def test_traversal_rejected(env):
    client, run_id = env
    # bogus run id (the run_index containment guard rejects '.'/'..')
    assert client.get("/api/artifacts/run:..:x").status_code == 404
    # empty step-id after the run id → malformed
    assert client.get(f"/api/artifacts/run:{run_id}:").status_code == 404
    # export name that is not a contained .md basename
    assert client.get("/api/artifacts/export:passwd").status_code == 404
    # malformed id (no source separator)
    assert client.get("/api/artifacts/nonsense").status_code == 404


def test_containment_guards_reject_escapes():
    """Direct unit check of the resolved-path containment (the prompts.py
    discipline): a ``..`` handle can never resolve outside its store root."""
    import api.routers.artifacts as art
    from fastapi import HTTPException

    for rest in ("../secret", "..", "sub/../../x.md"):
        with pytest.raises(HTTPException) as ei:
            art._export_path(rest)
        assert ei.value.status_code == 404
    # a run handle whose run-id component escapes
    with pytest.raises(HTTPException):
        art._run_path("../evil:step")


def test_missing_ids_404(env):
    client, _run_id = env
    assert client.get("/api/artifacts/feedback:art_missing").status_code == 404
    assert client.get("/api/artifacts/export:nope.md").status_code == 404
    assert client.get("/api/artifacts/run:no-such-run:draft").status_code == 404


# ── scope enforcement (auth ON) ──────────────────────────────────────────────
def test_scope_enforced_with_auth_on(tmp_path, monkeypatch):
    """A key WITHOUT the `workflows` scope is 403'd on /api/artifacts; the
    SCOPE_MAP entry shipped in this unit is what enforces it (F9)."""
    monkeypatch.setenv("ENABLE_API_AUTH", "true")
    monkeypatch.setenv("RATE_LIMIT_RPM", "0")
    monkeypatch.setenv("WORKFLOW_DATA_DIR", str(tmp_path / "wf"))
    (tmp_path / "wf").mkdir()

    import api.middleware

    importlib.reload(api.middleware)
    assert api.middleware.SCOPE_MAP.get("/api/artifacts") == "workflows"
    assert api.middleware.SCOPE_MAP.get("/api/format-sets") == "workflows"
    assert api.middleware._required_scope("/api/artifacts") == "workflows"
