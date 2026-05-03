"""
A2A Router — JSON-RPC 2.0 + SSE endpoints for Google's Agent-to-Agent protocol.

Routes:
  GET  /.well-known/agent.json            — Agent Card (discovery)
  POST /a2a                               — JSON-RPC dispatch:
        tasks/send, tasks/sendSubscribe (SSE), tasks/get, tasks/cancel

Spec: https://google.github.io/A2A/

Design notes:
  - The Agent Card URL is dynamically built from the inbound request so it
    matches whatever public host/port the operator exposes.
  - tasks/sendSubscribe returns a text/event-stream of JSON-encoded
    TaskStatusUpdateEvent / TaskArtifactUpdateEvent payloads framed inside
    JSON-RPC responses (one per SSE `data:` line) — the spec form.
  - All errors funnel through _error_response so non-RPC handlers (e.g.
    the parse-error path) still emit valid JSON-RPC envelopes.
"""

from __future__ import annotations

import json
import os
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from ..logging_config import logger
from ..models.a2a_models import (
    A2AErrorCode,
    AgentCapabilities,
    AgentCard,
    AgentProvider,
    AgentSkill,
    JsonRpcError,
    JsonRpcRequest,
    JsonRpcResponse,
    Message,
    TaskIdParams,
    TaskQueryParams,
    TaskSendParams,
    parse_skill_id,
)
from ..services.a2a_service import A2AService


router = APIRouter(tags=["a2a"])

# Lazily constructed by api/main.py via init_a2a_service(); see that module
# for wiring against the live OllamaService and WorkflowEngine.
_service: A2AService | None = None


def init_a2a_service(service: A2AService) -> None:
    global _service
    _service = service


def _get_service() -> A2AService:
    if _service is None:
        raise RuntimeError("A2A service not initialized — call init_a2a_service()")
    return _service


# ── Agent Card ─────────────────────────────────────────────────────────────


@router.get("/.well-known/agent.json")
async def agent_card(request: Request) -> JSONResponse:
    """Serve the Agent Card describing this Enclave instance."""
    svc = _get_service()
    base_url = str(request.base_url).rstrip("/")
    auth_enabled = os.getenv("ENABLE_API_AUTH", "false").lower() == "true"

    skills = [AgentSkill(**s) for s in svc.discoverable_skills()]

    card = AgentCard(
        name=os.getenv("A2A_AGENT_NAME", "Enclave"),
        description=(
            "Self-hosted local LLM platform with multi-agent workflow engine. "
            "Exposes chat and YAML-defined workflows as A2A skills."
        ),
        url=f"{base_url}/a2a",
        provider=AgentProvider(organization="ohno llc"),
        version=os.getenv("A2A_AGENT_VERSION", "0.1.0"),
        capabilities=AgentCapabilities(
            streaming=True,
            pushNotifications=False,
            stateTransitionHistory=True,
        ),
        authentication=(
            {"schemes": ["bearer"]} if auth_enabled else None
        ),
        defaultInputModes=["text"],
        defaultOutputModes=["text", "data"],
        skills=skills,
    )
    return JSONResponse(card.model_dump(by_alias=True, exclude_none=True))


# ── JSON-RPC dispatch ──────────────────────────────────────────────────────


@router.post("/a2a")
async def a2a_rpc(request: Request):
    """JSON-RPC 2.0 dispatch for A2A methods."""
    raw = await request.body()
    try:
        payload = json.loads(raw.decode() or "{}")
    except json.JSONDecodeError as exc:
        return _error_response(None, A2AErrorCode.PARSE_ERROR, f"parse error: {exc}")

    try:
        rpc = JsonRpcRequest.model_validate(payload)
    except Exception as exc:
        return _error_response(
            payload.get("id") if isinstance(payload, dict) else None,
            A2AErrorCode.INVALID_REQUEST,
            f"invalid jsonrpc envelope: {exc}",
        )

    method = rpc.method
    params = rpc.params or {}
    rpc_id = rpc.id

    try:
        if method == "tasks/send":
            return await _handle_send(rpc_id, params)
        if method == "tasks/sendSubscribe":
            return await _handle_send_subscribe(rpc_id, params)
        if method == "tasks/get":
            return await _handle_get(rpc_id, params)
        if method == "tasks/cancel":
            return await _handle_cancel(rpc_id, params)
        if method in {
            "tasks/pushNotification/set",
            "tasks/pushNotification/get",
            "tasks/resubscribe",
        }:
            return _error_response(
                rpc_id,
                A2AErrorCode.UNSUPPORTED_OPERATION,
                f"method {method} not supported in this build (push notifications "
                "and resubscribe are scheduled for a follow-up release)",
            )
        return _error_response(
            rpc_id, A2AErrorCode.METHOD_NOT_FOUND, f"unknown method: {method}"
        )
    except Exception as exc:
        logger.exception("a2a method %s crashed", method)
        return _error_response(
            rpc_id, A2AErrorCode.INTERNAL_ERROR, f"internal error: {exc}"
        )


# ── Method handlers ────────────────────────────────────────────────────────


def _skill_from_metadata(message: Message, params_metadata: dict | None) -> str:
    """
    Pull the target skill id out of (in order): params.metadata.skillId,
    message.metadata.skillId, or default to "chat".
    """
    if params_metadata and "skillId" in params_metadata:
        return params_metadata["skillId"]
    if message.metadata and "skillId" in message.metadata:
        return message.metadata["skillId"]
    return "chat"


async def _handle_send(rpc_id, params: dict[str, Any]):
    parsed = TaskSendParams.model_validate(params)
    skill = _skill_from_metadata(parsed.message, parsed.metadata)
    # Validate skill exists before kicking off work.
    try:
        parse_skill_id(skill)
    except ValueError as exc:
        return _error_response(
            rpc_id, A2AErrorCode.INVALID_PARAMS, str(exc)
        )

    svc = _get_service()
    task = await svc.send(
        skill_id=skill,
        message=parsed.message,
        task_id=parsed.id,
        session_id=parsed.session_id,
    )
    return _ok_response(rpc_id, task.model_dump(by_alias=True, exclude_none=True))


async def _handle_send_subscribe(rpc_id, params: dict[str, Any]):
    parsed = TaskSendParams.model_validate(params)
    skill = _skill_from_metadata(parsed.message, parsed.metadata)
    try:
        parse_skill_id(skill)
    except ValueError as exc:
        return _error_response(rpc_id, A2AErrorCode.INVALID_PARAMS, str(exc))

    svc = _get_service()
    stream = await svc.send_subscribe(
        skill_id=skill,
        message=parsed.message,
        task_id=parsed.id,
        session_id=parsed.session_id,
    )

    async def _sse_gen():
        async for event in stream:
            envelope = JsonRpcResponse(
                id=rpc_id,
                result=event.model_dump(by_alias=True, exclude_none=True),
            ).model_dump(by_alias=True, exclude_none=True)
            yield f"data: {json.dumps(envelope)}\n\n"
        # spec doesn't require a [DONE] sentinel but it's harmless and
        # mirrors our existing OpenAI-compatible streaming endpoints.
        yield "data: [DONE]\n\n"

    return StreamingResponse(_sse_gen(), media_type="text/event-stream")


async def _handle_get(rpc_id, params: dict[str, Any]):
    parsed = TaskQueryParams.model_validate(params)
    svc = _get_service()
    task = svc.get(parsed.id)
    if task is None:
        return _error_response(
            rpc_id, A2AErrorCode.TASK_NOT_FOUND, f"task not found: {parsed.id}"
        )
    payload = task.model_dump(by_alias=True, exclude_none=True)
    if parsed.history_length is not None:
        payload["history"] = payload.get("history", [])[-parsed.history_length :]
    return _ok_response(rpc_id, payload)


async def _handle_cancel(rpc_id, params: dict[str, Any]):
    parsed = TaskIdParams.model_validate(params)
    svc = _get_service()
    try:
        task = await svc.cancel(parsed.id)
    except KeyError:
        return _error_response(
            rpc_id, A2AErrorCode.TASK_NOT_FOUND, f"task not found: {parsed.id}"
        )
    except ValueError as exc:
        return _error_response(rpc_id, A2AErrorCode.TASK_NOT_CANCELABLE, str(exc))
    return _ok_response(rpc_id, task.model_dump(by_alias=True, exclude_none=True))


# ── JSON-RPC envelope helpers ──────────────────────────────────────────────


def _ok_response(rpc_id, result) -> JSONResponse:
    env = JsonRpcResponse(id=rpc_id, result=result)
    return JSONResponse(env.model_dump(by_alias=True, exclude_none=True))


def _error_response(rpc_id, code: int, message: str, data=None) -> JSONResponse:
    env = JsonRpcResponse(
        id=rpc_id,
        error=JsonRpcError(code=code, message=message, data=data),
    )
    # JSON-RPC errors still return HTTP 200 — the error is in-band.
    return JSONResponse(env.model_dump(by_alias=True, exclude_none=True))
