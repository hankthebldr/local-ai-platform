#!/usr/bin/env python3
"""
Conversation store + agent-tuning persistence tests (gap-closure Phase 3).

Covers:
  * ConversationStore upsert / get / list / delete + created_at preservation
  * path-traversal rejection on conversation id
  * /api/conversations HTTP surface
  * /api/feedback/agent-tuning aggregation (up/down counters, prefer/avoid cap)

No Ollama, no network.

Run:  pytest tests/test_conversation_persistence.py -v
"""

import os

import pytest

from api.models.conversation_models import SavedConversation
from api.services.conversation_store import ConversationStore


@pytest.fixture
def store(tmp_path):
    return ConversationStore(str(tmp_path / "conv"))


def _conv(cid="t123", n=2):
    return SavedConversation(
        id=cid,
        title="My Thread",
        model="llama3",
        messages=[
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "yo"},
        ][:n],
        html="<div>yo</div>",
        pins=[{"code": "print(1)"}],
    )


def test_upsert_and_get(store):
    store.save(_conv())
    got = store.get("t123")
    assert got is not None
    assert got.title == "My Thread"
    assert len(got.messages) == 2
    assert got.pins and got.pins[0]["code"] == "print(1)"


def test_created_at_preserved_on_update(store):
    first = store.save(_conv())
    created = first.created_at
    # update with new content
    store.save(_conv(n=1))
    again = store.get("t123")
    assert again.created_at == created
    assert again.updated_at >= created
    assert len(again.messages) == 1


def test_list_summaries_no_bodies(store):
    store.save(_conv("a"))
    store.save(_conv("b"))
    rows = store.list()
    assert {r["id"] for r in rows} == {"a", "b"}
    # summary carries counts, not message bodies
    assert all("messages" not in r for r in rows)
    assert all(r["message_count"] == 2 for r in rows)


def test_delete(store):
    store.save(_conv("z"))
    assert store.delete("z") is True
    assert store.get("z") is None
    assert store.delete("z") is False


@pytest.mark.parametrize("bad", ["../etc/passwd", "a/b", "..", ""])
def test_path_traversal_rejected(store, bad):
    with pytest.raises(ValueError):
        store.save(SavedConversation(id=bad))
    assert store.get(bad) is None
    assert store.delete(bad) is False


# ── HTTP surface ────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    os.environ["ENABLE_API_AUTH"] = "false"
    os.environ["RATE_LIMIT_RPM"] = "0"
    os.environ["CONVERSATION_DATA_DIR"] = str(tmp_path_factory.mktemp("conv-http"))
    os.environ["DATA_FEEDBACK_DIR"] = str(tmp_path_factory.mktemp("feedback-http"))
    import importlib

    import api.middleware

    importlib.reload(api.middleware)
    # Rebind store singletons to the temp dirs the env now points at.
    import api.services.conversation_store as cs

    importlib.reload(cs)
    import api.routers.feedback as fb

    importlib.reload(fb)
    import api.main

    importlib.reload(api.main)
    from api.main import app
    from fastapi.testclient import TestClient

    return TestClient(app)


def test_conversations_endpoint_round_trip(client):
    r = client.post(
        "/api/conversations",
        json={
            "id": "http-thread-1",
            "title": "HTTP Thread",
            "messages": [{"role": "user", "content": "ping"}],
            "html": "<div>ping</div>",
            "pins": [],
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["id"] == "http-thread-1"

    lst = client.get("/api/conversations")
    assert lst.status_code == 200
    assert any(c["id"] == "http-thread-1" for c in lst.json()["conversations"])

    full = client.get("/api/conversations/http-thread-1")
    assert full.status_code == 200
    assert full.json()["messages"][0]["content"] == "ping"

    d = client.delete("/api/conversations/http-thread-1")
    assert d.status_code == 200
    assert client.get("/api/conversations/http-thread-1").status_code == 404


def test_agent_tuning_aggregation(client):
    # Three ups + one down on the same agent key.
    for txt in ["a", "b", "c", "d"]:
        client.post(
            "/api/feedback/agent-tuning",
            json={"agent_key": "role:analyst", "kind": "up", "text": txt},
        )
    client.post(
        "/api/feedback/agent-tuning",
        json={"agent_key": "role:analyst", "kind": "down", "text": "nope"},
    )
    one = client.get("/api/feedback/agent-tuning/role:analyst").json()
    assert one["up"] == 4
    assert one["down"] == 1
    # prefer is capped to the most recent few examples
    assert one["prefer"] == ["b", "c", "d"]
    assert one["avoid"] == ["nope"]

    full = client.get("/api/feedback/agent-tuning").json()
    assert "role:analyst" in full
