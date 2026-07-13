"""Tests for the run index service + `/api/workflows/runs-index` route (U5).

Covers the five spec-named cases (§3.2):
  * cursor determinism under checkpoint-mtime churn
  * origin-precedence in the type taxonomy
  * health / anomaly math (incl. the cold-cache `stats_pending` degrade)
  * `../` traversal rejection / containment
  * catch-all non-shadowing (`/runs-index` is not read as a workflow_id, and
    the legacy `/runs` payload is byte-unchanged)
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.services import run_index


# ── fixtures ────────────────────────────────────────────────────────────────


def _write_run(root: Path, run_id: str, **fields) -> Path:
    run_dir = root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    data = {"run_id": run_id, "status": "completed", "step_results": [], **fields}
    (run_dir / "run.json").write_text(json.dumps(data), encoding="utf-8")
    return run_dir


def _write_origin(root: Path, run_id: str, **fields) -> None:
    (root / run_id / "origin.json").write_text(json.dumps(fields), encoding="utf-8")


@pytest.fixture
def run_root(tmp_path, monkeypatch):
    root = tmp_path / "runs"
    root.mkdir()
    monkeypatch.setenv("WORKFLOW_DATA_DIR", str(root))
    run_index.reset_caches()
    yield root
    run_index.reset_caches()


# ── cursor determinism under mtime churn ────────────────────────────────────


class TestCursorDeterminism:
    def test_full_walk_is_ordered_desc_by_started_at(self, run_root):
        for i in range(5):
            _write_run(
                run_root,
                f"run-{i}",
                started_at=f"2026-07-0{i+1}T00:00:00",
            )
        page = run_index.scan_runs(limit=10)
        order = [r["run_id"] for r in page["runs"]]
        assert order == ["run-4", "run-3", "run-2", "run-1", "run-0"]
        assert page["exhausted"] is True

    def test_paging_has_no_gaps_or_dupes(self, run_root):
        for i in range(6):
            _write_run(run_root, f"r{i}", started_at=f"2026-07-01T00:0{i}:00")
        p1 = run_index.scan_runs(limit=2)
        p2 = run_index.scan_runs(limit=2, cursor=p1["next_cursor"])
        p3 = run_index.scan_runs(limit=2, cursor=p2["next_cursor"])
        ids = [r["run_id"] for r in p1["runs"] + p2["runs"] + p3["runs"]]
        assert ids == ["r5", "r4", "r3", "r2", "r1", "r0"]
        assert len(set(ids)) == 6
        assert p3["exhausted"] is True

    def test_checkpoint_mtime_churn_does_not_reorder(self, run_root):
        for i in range(4):
            _write_run(run_root, f"c{i}", started_at=f"2026-07-01T00:0{i}:00")
        before = [r["run_id"] for r in run_index.scan_runs(limit=10)["runs"]]

        # Touch the OLDEST run's checkpoint so its dir mtime becomes the newest —
        # if mtime leaked into the sort key this would jump it to the top.
        time.sleep(0.01)
        oldest = run_root / "c0" / "run.json"
        os.utime(oldest, None)
        (run_root / "c0" / "run.json").write_text(
            json.dumps(
                {
                    "run_id": "c0",
                    "status": "completed",
                    "started_at": "2026-07-01T00:00:00",
                    "step_results": [],
                }
            ),
            encoding="utf-8",
        )
        after = [r["run_id"] for r in run_index.scan_runs(limit=10)["runs"]]
        assert before == after
        assert after[0] == "c3"  # newest started_at, unmoved

    def test_started_at_absent_falls_back_to_mtime_not_crash(self, run_root):
        _write_run(run_root, "no-start")  # no started_at key
        page = run_index.scan_runs(limit=10)
        assert [r["run_id"] for r in page["runs"]] == ["no-start"]
        # A mtime ISO fallback was substituted into the sort index, not run.json.
        assert page["runs"][0]["started_at"] is None


# ── origin precedence in the type taxonomy ──────────────────────────────────


class TestTypePrecedence:
    def test_scheduled_sidecar_wins_and_carries_category(self):
        tags = run_index.classify_type(
            {"origin": "scheduled", "schedule_category": "Digest"},
            set(),
            "some-wf",
        )
        types = {t["type"] for t in tags}
        assert "scheduled" in types
        assert "manual" not in types  # scheduled claims the run
        sched = next(t for t in tags if t["type"] == "scheduled")
        assert sched["label"] == "Scheduled Digest"
        assert sched["run_now"] is False

    def test_run_now_gets_lightning_affix(self):
        tags = run_index.classify_type(
            {"origin": "scheduled", "schedule_category": "Digest", "trigger": "run-now"},
            set(),
            "wf",
        )
        sched = next(t for t in tags if t["type"] == "scheduled")
        assert sched["label"].startswith("⚡")
        assert sched["run_now"] is True

    def test_test_sidecar_beats_heuristic_and_is_not_derived(self):
        tags = run_index.classify_type({"origin": "test"}, set(), "prod-wf")
        test = next(t for t in tags if t["type"] == "test")
        assert "derived" not in test  # authoritative, not derived

    def test_heuristic_test_is_flagged_derived(self):
        tags = run_index.classify_type(None, set(), "test-a2a-happy")
        test = next(t for t in tags if t["type"] == "test")
        assert test.get("derived") is True

    def test_legacy_sidecarless_run_is_plain_manual(self):
        tags = run_index.classify_type(None, set(), "intel-enrichment")
        assert [t["type"] for t in tags] == ["manual"]

    def test_autonomous_cooccurs_with_scheduled(self):
        tags = run_index.classify_type(
            {"origin": "scheduled", "schedule_category": "Loop"},
            {"ralph", "llm"},
            "wf",
        )
        types = {t["type"] for t in tags}
        assert types == {"scheduled", "autonomous"}

    def test_autonomous_from_plan_item_origin(self):
        tags = run_index.classify_type(
            None, set(), "wf", plan_items=[{"origin": "ralph"}]
        )
        assert any(t["type"] == "autonomous" for t in tags)


# ── health / anomaly math ───────────────────────────────────────────────────


class TestHealthModel:
    def test_failed_run_carries_failing_step_and_error_class(self):
        data = {
            "status": "failed",
            "step_results": [
                {"step_id": "fetch", "status": "completed"},
                {
                    "step_id": "analyze",
                    "status": "failed",
                    "error": "TimeoutError: model did not respond",
                    "retries": 2,
                },
            ],
        }
        h = run_index.assess_health(data, stats={})
        assert h["health"] == "failed"
        assert h["failing_step"] == "analyze"
        assert h["error_class"] == "TimeoutError"
        assert h["retries_total"] == 2

    def test_running_run(self):
        h = run_index.assess_health({"status": "running", "step_results": []}, {})
        assert h["health"] == "running"

    def test_clean_completed_run(self):
        h = run_index.assess_health(
            {"status": "completed", "step_results": [{"status": "completed"}]},
            {"duration_median": 10, "tokens_median": 100},
        )
        assert h["health"] == "completed"
        assert h["degraded_reasons"] == []

    def test_retries_mark_degraded(self):
        h = run_index.assess_health(
            {
                "status": "completed",
                "step_results": [{"status": "completed", "retries": 1}],
            },
            {"duration_median": 10, "tokens_median": 100},
        )
        assert h["health"] == "degraded"
        assert "retries" in h["degraded_reasons"]

    def test_duration_anomaly_beyond_3x_median(self):
        data = {
            "status": "completed",
            "started_at": "2026-07-01T00:00:00",
            "completed_at": "2026-07-01T00:01:00",  # 60s
            "step_results": [{"status": "completed"}],
        }
        h = run_index.assess_health(data, {"duration_median": 10, "tokens_median": 999})
        assert h["health"] == "degraded"
        assert "duration_anomaly" in h["degraded_reasons"]

    def test_token_anomaly_beyond_3x_median(self):
        data = {
            "status": "completed",
            "step_results": [
                {"status": "completed", "token_count": {"total_tokens": 500}}
            ],
        }
        h = run_index.assess_health(data, {"duration_median": None, "tokens_median": 100})
        assert h["health"] == "degraded"
        assert "token_anomaly" in h["degraded_reasons"]

    def test_cold_cache_yields_stats_pending_not_blocking(self):
        # A clean run with a cold (None) cache stays `completed` but carries the
        # caveat — cost anomalies are suppressed, never a per-row sibling scan.
        data = {
            "status": "completed",
            "started_at": "2026-07-01T00:00:00",
            "completed_at": "2026-07-01T01:00:00",  # would be a huge duration
            "step_results": [{"status": "completed"}],
        }
        h = run_index.assess_health(data, stats=None)
        assert h["health"] == "completed"
        assert "stats_pending" in h["degraded_reasons"]
        assert "duration_anomaly" not in h["degraded_reasons"]

    def test_skipped_step_marks_degraded(self):
        h = run_index.assess_health(
            {"status": "completed", "step_results": [{"status": "skipped"}]},
            {"duration_median": 10, "tokens_median": 100},
        )
        assert h["health"] == "degraded"
        assert "skipped_step" in h["degraded_reasons"]

    def test_warm_stats_computes_medians(self, run_root):
        for i in range(3):
            _write_run(
                run_root,
                f"m{i}",
                workflow_id="wf-a",
                started_at=f"2026-07-0{i+1}T00:00:00",
                completed_at=f"2026-07-0{i+1}T00:00:10",  # 10s each
                step_results=[{"status": "completed", "token_count": {"total_tokens": 50}}],
            )
        stats = run_index.warm_stats(run_root)
        assert stats["wf-a"]["duration_median"] == pytest.approx(10.0)
        assert stats["wf-a"]["tokens_median"] == 50


# ── containment / traversal rejection ───────────────────────────────────────


class TestContainment:
    def test_dotdot_run_id_rejected(self, run_root):
        assert run_index._resolve_run_dir(run_root, "..") is None
        assert run_index._resolve_run_dir(run_root, "../etc") is None
        assert run_index._resolve_run_dir(run_root, "a/../../b") is None

    def test_absolute_path_injection_rejected(self, run_root):
        assert run_index._resolve_run_dir(run_root, "/etc/passwd") is None

    def test_legit_run_id_resolves(self, run_root):
        _write_run(run_root, "good-run", started_at="2026-07-01T00:00:00")
        resolved = run_index._resolve_run_dir(run_root, "good-run")
        assert resolved is not None
        assert resolved.name == "good-run"

    def test_symlink_escape_not_followed_out_of_root(self, run_root, tmp_path):
        outside = tmp_path / "secret"
        outside.mkdir()
        (outside / "run.json").write_text("{}", encoding="utf-8")
        link = run_root / "sneaky"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError:
            pytest.skip("symlinks unsupported on this platform")
        assert run_index._resolve_run_dir(run_root, "sneaky") is None


# ── cursor codec ────────────────────────────────────────────────────────────


class TestCursorCodec:
    def test_round_trip(self):
        c = run_index.encode_cursor("2026-07-01T00:00:00", "abc-123")
        assert run_index.decode_cursor(c) == ("2026-07-01T00:00:00", "abc-123")

    def test_bad_cursor_resets_to_top(self):
        assert run_index.decode_cursor("!!!not-base64!!!") is None
        assert run_index.decode_cursor(None) is None
        assert run_index.decode_cursor("") is None


# ── server-side filters ─────────────────────────────────────────────────────


class TestFilters:
    def test_status_filter(self, run_root):
        _write_run(run_root, "ok", status="completed", started_at="2026-07-02T00:00:00")
        _write_run(run_root, "bad", status="failed", started_at="2026-07-01T00:00:00")
        page = run_index.scan_runs(limit=10, status="failed")
        assert [r["run_id"] for r in page["runs"]] == ["bad"]

    def test_health_filter(self, run_root):
        _write_run(run_root, "clean", status="completed", started_at="2026-07-02T00:00:00")
        _write_run(
            run_root,
            "fail",
            status="failed",
            started_at="2026-07-01T00:00:00",
            step_results=[{"step_id": "s", "status": "failed", "error": "Boom: x"}],
        )
        page = run_index.scan_runs(limit=10, health="failed")
        assert [r["run_id"] for r in page["runs"]] == ["fail"]

    def test_type_filter(self, run_root):
        _write_run(run_root, "sched", started_at="2026-07-02T00:00:00")
        _write_origin(run_root, "sched", origin="scheduled", schedule_category="D")
        _write_run(run_root, "manual", started_at="2026-07-01T00:00:00")
        page = run_index.scan_runs(limit=10, type_="scheduled")
        assert [r["run_id"] for r in page["runs"]] == ["sched"]

    def test_q_filter_matches_workflow_id(self, run_root):
        _write_run(run_root, "r1", workflow_id="intel-pipe", started_at="2026-07-02T00:00:00")
        _write_run(run_root, "r2", workflow_id="chat-flow", started_at="2026-07-01T00:00:00")
        page = run_index.scan_runs(limit=10, q="intel")
        assert [r["run_id"] for r in page["runs"]] == ["r1"]


# ── route: catch-all non-shadowing + legacy /runs byte-unchanged ────────────


@pytest.fixture
def client(run_root, monkeypatch):
    from unittest.mock import patch

    with patch("api.services.ollama_service.OllamaService") as MockClass:
        instance = MockClass.return_value
        instance.health_check.return_value = True
        instance.list_models.return_value = []
        with patch("api.routers.workflows.get_ollama_service", return_value=instance):
            with patch("api.main.ollama_service", instance):
                from api.main import app

                yield TestClient(app)


class TestRouteRegistration:
    def test_runs_index_resolves_not_as_workflow_id(self, client, run_root):
        _write_run(run_root, "seed-run", workflow_id="wf", started_at="2026-07-01T00:00:00")
        resp = client.get("/api/workflows/runs-index")
        assert resp.status_code == 200
        body = resp.json()
        assert "runs" in body and "next_cursor" in body
        assert any(r["run_id"] == "seed-run" for r in body["runs"])

    def test_runs_index_not_treated_as_a_workflow_lookup(self, client):
        # If the /{workflow_id} catch-all shadowed us this would 404 the
        # "runs-index" workflow instead of returning a page envelope.
        resp = client.get("/api/workflows/runs-index?limit=1")
        assert resp.status_code == 200
        assert "runs" in resp.json()

    def test_legacy_runs_endpoint_unchanged_shape(self, client):
        resp = client.get("/api/workflows/runs?limit=5")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)  # engine.list_runs list, untouched

    def test_runs_index_filters_via_query_params(self, client, run_root):
        _write_run(run_root, "f-ok", status="completed", started_at="2026-07-02T00:00:00")
        _write_run(run_root, "f-bad", status="failed", started_at="2026-07-01T00:00:00")
        resp = client.get("/api/workflows/runs-index?status=failed")
        assert resp.status_code == 200
        ids = [r["run_id"] for r in resp.json()["runs"]]
        assert ids == ["f-bad"]
