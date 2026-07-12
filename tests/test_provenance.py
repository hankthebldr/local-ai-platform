#!/usr/bin/env python3
"""
Provenance store + router tests — the #1-gap citation chain.

Covers:
  * ProvenanceStore round-trip (header + edges sidecar)
  * path-traversal rejection on response_id
  * torn/old jsonl lines skipped, not fatal
  * graph_service._build_provenance_nodes emits response→source edges
  * GET /api/provenance/response/{id} + /responses HTTP surface

No Ollama, no network. The chat-emission glue (_record_chat_provenance) is
exercised via the store it writes through.

Run:  pytest tests/test_provenance.py -v
"""

import os
import tempfile

import pytest

from api.models.provenance_models import ProvenanceEdge, ResponseProvenance
from api.services.provenance_store import ProvenanceStore


@pytest.fixture
def store(tmp_path):
    return ProvenanceStore(str(tmp_path / "prov"))


def _chain(rid="chatcmpl-deadbeef"):
    return ResponseProvenance(
        response_id=rid,
        conversation_id="conv-1",
        model="llama3",
        content_preview="the answer",
        edges=[
            ProvenanceEdge(
                response_id=rid,
                source_type="rag_chunk",
                source_id="docA::chunk_2",
                source_label="docA.pdf",
                metadata={"score": 0.91, "chunk_index": 2},
            ),
            ProvenanceEdge(
                response_id=rid,
                source_type="skill",
                source_id="threat-intel",
                source_label="Threat Intel",
            ),
            ProvenanceEdge(
                response_id=rid,
                source_type="plugin_tool",
                source_id="websearch.query",
                source_label="websearch · query",
            ),
        ],
    )


def test_round_trip(store):
    store.record(_chain())
    got = store.get("chatcmpl-deadbeef")
    assert got is not None
    assert got.conversation_id == "conv-1"
    assert len(got.edges) == 3
    kinds = {e.source_type for e in got.edges}
    assert kinds == {"rag_chunk", "skill", "plugin_tool"}


def test_header_has_no_inline_edges_on_disk(store):
    """Edges live in the jsonl sidecar, not the header json."""
    store.record(_chain())
    import json

    header = json.loads((store.responses_dir / "chatcmpl-deadbeef.json").read_text())
    assert header.get("edges") in (None, [])
    assert (store.edges_dir / "chatcmpl-deadbeef.jsonl").exists()


def test_get_edges_only(store):
    store.record(_chain())
    edges = store.get_edges("chatcmpl-deadbeef")
    assert len(edges) == 3
    assert store.get_edges("nope") == []


@pytest.mark.parametrize("bad", ["../etc/passwd", "a/b", "..", "", "x\x00y"])
def test_path_traversal_rejected(store, bad):
    # record swallows the unsafe id (logged), get returns None / []
    store.record(ResponseProvenance(response_id=bad, edges=[]))
    assert store.get(bad) is None
    assert store.get_edges(bad) == []


def test_torn_jsonl_line_skipped(store):
    store.record(_chain())
    path = store.edges_dir / "chatcmpl-deadbeef.jsonl"
    with open(path, "a") as f:
        f.write("{not valid json\n")
    # the 3 good edges survive; the torn line is skipped
    assert len(store.get_edges("chatcmpl-deadbeef")) == 3


def test_list_responses(store):
    store.record(_chain("chatcmpl-aaa"))
    store.record(_chain("chatcmpl-bbb"))
    rows = store.list_responses()
    assert {r.response_id for r in rows} == {"chatcmpl-aaa", "chatcmpl-bbb"}


def test_missing_response(store):
    assert store.get("chatcmpl-missing") is None


def test_graph_builder_emits_grounding_edges(store, monkeypatch):
    store.record(_chain())
    import api.services.provenance_store as ps

    monkeypatch.setattr(ps, "_store", store)
    from api.services.graph_service import _build_provenance_nodes

    nodes, links = [], []
    count = _build_provenance_nodes(nodes, links)
    assert count == 1
    node_types = {n["type"] for n in nodes}
    assert "response" in node_types
    assert {"chunk", "skill", "tool"} <= node_types
    link_types = {link["type"] for link in links}
    assert link_types == {"grounded_on", "activated_skill", "invoked_tool"}

    # U13: the response node carries the FULL response_id (untruncated) so the
    # Context rail can fetch the exact provenance chain, while the node "id"
    # stays truncated so the grounding links above still resolve to it.
    rnode = next(n for n in nodes if n["type"] == "response")
    assert rnode["response_id"] == "chatcmpl-deadbeef"
    assert rnode["id"] == "response:chatcmpl-deadbeef"
    assert rnode["id"] != rnode["response_id"]
    # Every grounding link's source is the truncated node id, not the full id.
    assert all(link["source"] == rnode["id"] for link in links)


# ── HTTP surface ────────────────────────────────────────────────────────────


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
    from fastapi.testclient import TestClient

    return TestClient(app)


def test_endpoint_round_trip(client, tmp_path, monkeypatch):
    st = ProvenanceStore(str(tmp_path / "http-prov"))
    st.record(_chain("chatcmpl-http1"))
    import api.services.provenance_store as ps

    monkeypatch.setattr(ps, "_store", st)

    r = client.get("/api/provenance/response/chatcmpl-http1")
    assert r.status_code == 200
    body = r.json()
    assert body["response_id"] == "chatcmpl-http1"
    assert len(body["edges"]) == 3

    r2 = client.get("/api/provenance/responses")
    assert r2.status_code == 200
    assert r2.json()["total"] >= 1

    r3 = client.get("/api/provenance/response/does-not-exist")
    assert r3.status_code == 404
