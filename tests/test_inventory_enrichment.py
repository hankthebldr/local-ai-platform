#!/usr/bin/env python3
"""
Model enrichment endpoint tests — GET /api/inventory/enrichment.

Feeds the AssetPeek deep-dive benchmark cards from local repo data
(data/discovery/model_benchmarks.json) — privacy-first, no phone-home. The
three branches (missing file → {}, valid JSON passthrough, unreadable → {})
were unasserted. The endpoint resolves the benchmarks path relative to CWD,
so each test chdirs into an isolated tmp dir to control which branch fires.

LB4-U1: the response additionally merges the repo-shipped curated sidecar
api/config/model_meta.json (module-relative — found regardless of CWD) under
the reserved 'model_meta' key. The merge is additive: benchmark keys pass
through untouched, so assertions compare the benchmark subset and treat
'model_meta' as the sidecar's own channel.

Run:  pytest tests/test_inventory_enrichment.py -v
"""

import json
import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    os.environ["ENABLE_API_AUTH"] = "false"
    os.environ["RATE_LIMIT_RPM"] = "0"
    import importlib
    import api.middleware

    importlib.reload(api.middleware)
    import api.main

    importlib.reload(api.main)
    from api.main import app

    return TestClient(app)


def _write_benchmarks(root, payload: str):
    d = root / "data" / "discovery"
    d.mkdir(parents=True, exist_ok=True)
    (d / "model_benchmarks.json").write_text(payload)


def _benchmark_part(body: dict) -> dict:
    """The response minus the sidecar channel — the benchmarks passthrough."""
    return {k: v for k, v in body.items() if k != "model_meta"}


def test_enrichment_missing_file_returns_empty(client, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # no data/discovery/ here
    resp = client.get("/api/inventory/enrichment")
    assert resp.status_code == 200
    assert _benchmark_part(resp.json()) == {}
    assert resp.headers["content-type"].startswith("application/json")


def test_enrichment_valid_json_passes_through(client, tmp_path, monkeypatch):
    payload = {"qwen2.5:7b": {"mmlu": 74.2, "tokens_per_s": 48}}
    _write_benchmarks(tmp_path, json.dumps(payload))
    monkeypatch.chdir(tmp_path)
    resp = client.get("/api/inventory/enrichment")
    assert resp.status_code == 200
    assert _benchmark_part(resp.json()) == payload


def test_enrichment_corrupt_json_returns_empty(client, tmp_path, monkeypatch):
    _write_benchmarks(tmp_path, "{ this is not valid json ]")
    monkeypatch.chdir(tmp_path)
    resp = client.get("/api/inventory/enrichment")
    # The except branch swallows the parse error and returns {} — never 500.
    assert resp.status_code == 200
    assert _benchmark_part(resp.json()) == {}


def test_enrichment_model_meta_sidecar_merged(client, tmp_path, monkeypatch):
    """The repo-shipped sidecar rides the response additively (LB4-U1)."""
    payload = {"qwen2.5:7b": {"mmlu": 74.2}}
    _write_benchmarks(tmp_path, json.dumps(payload))
    monkeypatch.chdir(tmp_path)
    body = client.get("/api/inventory/enrichment").json()
    # Sidecar present (module-relative resolution — CWD-independent) …
    assert "model_meta" in body
    meta = body["model_meta"]
    assert "arch_class_perf" in meta
    assert "intent_configs" in meta
    assert "vram_notes" in meta
    # … and the benchmarks passthrough is untouched by the merge.
    assert _benchmark_part(body) == payload
