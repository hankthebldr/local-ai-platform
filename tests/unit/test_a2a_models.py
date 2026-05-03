"""Unit tests for A2A protocol Pydantic models."""

import pytest

from api.models.a2a_models import (
    AgentCard,
    AgentCapabilities,
    AgentSkill,
    A2AErrorCode,
    Artifact,
    DataPart,
    JsonRpcError,
    JsonRpcRequest,
    JsonRpcResponse,
    Message,
    MessageRole,
    Task,
    TaskIdParams,
    TaskQueryParams,
    TaskSendParams,
    TaskState,
    TaskStatus,
    TextPart,
    CHAT_SKILL_ID,
    parse_skill_id,
    workflow_skill_id,
)


# ── parse_skill_id ─────────────────────────────────────────────────────────


def test_parse_skill_id_chat():
    assert parse_skill_id(CHAT_SKILL_ID) == ("chat", None)


def test_parse_skill_id_workflow():
    assert parse_skill_id(workflow_skill_id("data-model")) == ("workflow", "data-model")


def test_parse_skill_id_unknown_raises():
    with pytest.raises(ValueError):
        parse_skill_id("nope")


# ── Task / Message round-tripping ──────────────────────────────────────────


def test_task_alias_serialization():
    """sessionId / lastChunk must serialize as camelCase per A2A spec."""
    t = Task(
        session_id="s1",
        status=TaskStatus(state=TaskState.WORKING),
        artifacts=[
            Artifact(name="out", parts=[TextPart(text="hi")], last_chunk=True)
        ],
    )
    dumped = t.model_dump(by_alias=True)
    assert "sessionId" in dumped
    assert "session_id" not in dumped
    assert dumped["artifacts"][0]["lastChunk"] is True


def test_message_text_concatenates_text_parts_only():
    msg = Message(
        role=MessageRole.USER,
        parts=[
            TextPart(text="line one"),
            DataPart(data={"k": "v"}),
            TextPart(text="line two"),
        ],
    )
    assert msg.text() == "line one\nline two"


# ── JSON-RPC envelope invariants ───────────────────────────────────────────


def test_jsonrpc_response_requires_exactly_one_of_result_error():
    # Both set
    with pytest.raises(Exception):
        JsonRpcResponse(id=1, result={}, error=JsonRpcError(code=-32600, message="x"))
    # Neither set
    with pytest.raises(Exception):
        JsonRpcResponse(id=1)


def test_jsonrpc_response_ok():
    env = JsonRpcResponse(id="abc", result={"k": 1})
    dumped = env.model_dump(by_alias=True, exclude_none=True)
    assert dumped == {"jsonrpc": "2.0", "id": "abc", "result": {"k": 1}}


def test_jsonrpc_response_error():
    env = JsonRpcResponse(
        id=42,
        error=JsonRpcError(code=A2AErrorCode.TASK_NOT_FOUND, message="missing"),
    )
    dumped = env.model_dump(by_alias=True, exclude_none=True)
    assert dumped["error"]["code"] == -32001


def test_jsonrpc_request_id_optional():
    rpc = JsonRpcRequest(method="tasks/get")
    assert rpc.id is None
    assert rpc.jsonrpc == "2.0"


# ── Method param validation ────────────────────────────────────────────────


def test_task_send_params_camelcase_aliases():
    parsed = TaskSendParams.model_validate(
        {
            "id": "t1",
            "sessionId": "s1",
            "message": {"role": "user", "parts": [{"type": "text", "text": "hi"}]},
            "acceptedOutputModes": ["text"],
        }
    )
    assert parsed.session_id == "s1"
    assert parsed.accepted_output_modes == ["text"]


def test_task_query_params_history_length_alias():
    parsed = TaskQueryParams.model_validate({"id": "t1", "historyLength": 3})
    assert parsed.history_length == 3


def test_task_id_params():
    p = TaskIdParams(id="t1")
    assert p.id == "t1" and p.metadata is None


# ── Agent Card ─────────────────────────────────────────────────────────────


def test_agent_card_default_capabilities():
    card = AgentCard(name="x", url="http://x", version="0.1")
    assert card.capabilities.streaming is False
    assert card.capabilities.push_notifications is False


def test_agent_card_alias_keys():
    card = AgentCard(
        name="x",
        url="http://x",
        version="0.1",
        capabilities=AgentCapabilities(streaming=True, pushNotifications=False),
        skills=[AgentSkill(id="chat", name="Chat")],
    )
    dumped = card.model_dump(by_alias=True, exclude_none=True)
    assert "defaultInputModes" in dumped
    assert "pushNotifications" in dumped["capabilities"]
