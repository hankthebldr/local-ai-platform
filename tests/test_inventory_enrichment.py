#!/usr/bin/env python3
"""
Model enrichment endpoint tests — GET /api/inventory/enrichment.

Feeds the AssetPeek deep-dive benchmark cards from local repo data
(data/discovery/model_benchmarks.json) — privacy-first, no phone-home. The
three branches (missing file → {}, valid JSON passthrough, unreadable → {})
were unasserted. The endpoint resolves the path relative to CWD, so each test
chdirs into an isolated tmp dir to control which branch fires.

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


def test_enrichment_missing_file_returns_empty(client, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # no data/discovery/ here
    resp = client.get("/api/inventory/enrichment")
    assert resp.status_code == 200
    assert resp.json() == {}
    assert resp.headers["content-type"].startswith("application/json")


def test_enrichment_valid_json_passes_through(client, tmp_path, monkeypatch):
    payload = {"qwen2.5:7b": {"mmlu": 74.2, "tokens_per_s": 48}}
    _write_benchmarks(tmp_path, json.dumps(payload))
    monkeypatch.chdir(tmp_path)
    resp = client.get("/api/inventory/enrichment")
    assert resp.status_code == 200
    assert resp.json() == payload


def test_enrichment_corrupt_json_returns_empty(client, tmp_path, monkeypatch):
    _write_benchmarks(tmp_path, "{ this is not valid json ]")
    monkeypatch.chdir(tmp_path)
    resp = client.get("/api/inventory/enrichment")
    # The except branch swallows the parse error and returns {} — never 500.
    assert resp.status_code == 200
    assert resp.json() == {}
