"""
A2A Client — Outbound HTTP client for `kind: a2a` workflow steps.

The companion to `a2a_service.py`: that one serves Enclave's own A2A surface
(workflows advertised as skills at /.well-known/agent.json), this one *calls*
external A2A agents from inside a workflow.

Flow for one a2a step:
  1. GET agent_card_url, parse the AgentCard
  2. Confirm the requested skill_id is advertised
  3. POST JSON-RPC tasks/send (or tasks/sendSubscribe for streaming) to the
     agent's `url`, with the step's resolved inputs packaged as the Message
  4. Poll/stream until task.status.state is terminal
  5. Return Artifacts the caller can map onto the step's declared outputs

Synchronous on purpose — the engine's step executor returns a synchronous
StepResult and we don't want to leak async semantics into composite step
dispatch (which already runs each step in a ThreadPoolExecutor worker).

Phase 3a/c scope:
  - Auth: bearer (`Authorization: Bearer …`) or api_key (configurable header,
    default `X-API-Key`); secret resolved from a named env var at request time
  - tasks/send + polling tasks/get (default) OR tasks/sendSubscribe with SSE
    streaming (`streaming=True` on the step); streaming accumulates artifacts
    as they arrive and terminates on the first status event with final=true
  - Best-effort artifact → output mapping by name match; falls back to first
    artifact's text content when names don't align
"""

from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

import httpx

from ..models.a2a_models import (
    AgentCard,
    Artifact,
    DataPart,
    Message,
    MessageRole,
    Task,
    TaskState,
    TextPart,
)
from ..models.workflow_models import A2AAuth


class A2AClientError(RuntimeError):
    """Anything that prevents an a2a step from completing.

    Subclass-less on purpose — operators see the message, not the type. The
    engine wraps this in a normal StepResult.failed.
    """


# Hard timeouts in seconds. The step-level `timeout` field on AgentStep
# caps the whole step; these constants are inner per-operation bounds that
# even an "unlimited" step honors.
_DEFAULT_CARD_TIMEOUT = 10
_DEFAULT_RPC_TIMEOUT = 60
_POLL_INTERVAL_SECONDS = 1.0
_TERMINAL_STATES = {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELED}


def _resolve_auth_headers(auth: Optional[A2AAuth]) -> Dict[str, str]:
    """Build outbound auth headers. Empty dict for no-auth.

    Both `bearer` and `api_key` resolve the secret from the named env var at
    request time (never from YAML). `api_key` sends it under a configurable
    header (default X-API-Key); `bearer` sends `Authorization: Bearer ...`.
    """
    if auth is None or auth.type == "none":
        return {}
    if auth.type in ("bearer", "api_key"):
        token = os.getenv(auth.token_env or "")
        if not token:
            raise A2AClientError(
                f"{auth.type} auth requested but env var {auth.token_env!r} is unset"
            )
        if auth.type == "bearer":
            return {"Authorization": f"Bearer {token}"}
        return {auth.header_name: token}
    raise A2AClientError(f"unsupported auth type: {auth.type!r}")


def _inputs_to_message(resolved_inputs: Dict[str, Any]) -> Message:
    """Package the step's resolved inputs into an A2A Message.

    Strings become TextParts; everything else becomes a single DataPart so
    the remote agent receives the structured shape it expects. The order
    is insertion order of resolved_inputs (which preserves YAML declaration).
    """
    parts: List[Any] = []
    text_chunks: List[str] = []
    data_payload: Dict[str, Any] = {}
    for key, value in resolved_inputs.items():
        if isinstance(value, str):
            text_chunks.append(value)
        else:
            data_payload[key] = value
    if text_chunks:
        parts.append(TextPart(text="\n".join(text_chunks)))
    if data_payload:
        parts.append(DataPart(data=data_payload))
    if not parts:
        # A2A doesn't allow a fully empty message — surface what the step is
        # asking for so the remote agent has something to dispatch on.
        parts.append(TextPart(text=""))
    return Message(role=MessageRole.USER, parts=parts)


def _artifacts_to_outputs(
    artifacts: List[Artifact], declared_outputs: List[str]
) -> Dict[str, Any]:
    """Map remote artifacts onto the step's declared output keys.

    Strategy, in priority order:
      1. Exact name match: artifact.name == output key → use its part value
      2. Single declared output + single artifact: use that artifact regardless
      3. Best-effort: walk artifacts in order, pick DataPart whose keys overlap
         with declared outputs; missing keys default to None

    The contract is intentionally forgiving — many A2A agents return a single
    artifact named after the skill, and we don't want to force operators to
    align names exactly.
    """
    outputs: Dict[str, Any] = {k: None for k in declared_outputs}

    name_to_artifact = {a.name: a for a in artifacts if a.name}

    for key in declared_outputs:
        if key in name_to_artifact:
            outputs[key] = _artifact_value(name_to_artifact[key])

    # If everything is still None and there's exactly one artifact, use it.
    if (
        all(v is None for v in outputs.values())
        and len(artifacts) == 1
        and declared_outputs
    ):
        outputs[declared_outputs[0]] = _artifact_value(artifacts[0])

    # Walk artifacts looking for DataParts whose keys map onto declared outputs.
    if any(v is None for v in outputs.values()):
        for artifact in artifacts:
            for part in artifact.parts:
                if isinstance(part, DataPart) and isinstance(part.data, dict):
                    for key in declared_outputs:
                        if outputs[key] is None and key in part.data:
                            outputs[key] = part.data[key]
    return outputs


def _artifact_value(artifact: Artifact) -> Any:
    """Extract a usable value from an Artifact.

    Single DataPart → return its `data` dict. Otherwise concatenate TextParts.
    """
    data_parts = [p for p in artifact.parts if isinstance(p, DataPart)]
    if len(data_parts) == 1:
        return data_parts[0].data
    text_parts = [p for p in artifact.parts if isinstance(p, TextPart)]
    if text_parts:
        return "\n".join(p.text for p in text_parts)
    if data_parts:
        return [p.data for p in data_parts]
    return None


def _agent_rpc_url(card: AgentCard) -> str:
    """The Agent Card declares the agent's RPC URL in `url`. Use that
    verbatim — we don't second-guess the remote's routing."""
    if not card.url:
        raise A2AClientError("AgentCard.url is empty — agent is not callable")
    return card.url


class A2AClient:
    """Thin HTTP client for outbound A2A calls.

    One instance can serve many steps — the underlying httpx.Client is
    created lazily and reused. Callers can construct an A2AClient per step
    or share one across the engine; this module's only state is the lazy
    client, so either pattern is safe.
    """

    def __init__(self, http_client: Optional[httpx.Client] = None):
        self._http = http_client

    def _client(self) -> httpx.Client:
        if self._http is None:
            self._http = httpx.Client(
                timeout=httpx.Timeout(
                    _DEFAULT_RPC_TIMEOUT, connect=_DEFAULT_CARD_TIMEOUT
                ),
                follow_redirects=True,
            )
        return self._http

    # ── Public API ────────────────────────────────────────────────────

    def call_skill(
        self,
        agent_card_url: str,
        skill_id: str,
        resolved_inputs: Dict[str, Any],
        declared_outputs: List[str],
        auth: Optional[A2AAuth] = None,
        timeout: Optional[int] = None,
        streaming: bool = False,
    ) -> Tuple[Dict[str, Any], Task]:
        """End-to-end: fetch card, post task, wait for terminal, map outputs.

        When `streaming` is True the client uses `tasks/sendSubscribe` and
        consumes the SSE stream of TaskStatusUpdateEvent / TaskArtifactUpdateEvent
        payloads until a status event marks the task `final: true`. Otherwise it
        polls `tasks/get` until terminal.

        Returns (outputs_dict, final_task). Raises A2AClientError on any
        unrecoverable failure (card fetch failure, skill not advertised,
        remote returned `failed` state, wall-clock timeout, etc.).
        """
        card = self.fetch_agent_card(agent_card_url, auth=auth)
        self._assert_skill_advertised(card, skill_id)

        message = _inputs_to_message(resolved_inputs)
        if streaming:
            task = self._send_task_subscribe(
                card, skill_id, message, auth=auth, timeout=timeout
            )
        else:
            task = self._send_task(card, skill_id, message, auth=auth, timeout=timeout)
            task = self._wait_for_terminal(card, task, auth=auth, timeout=timeout)

        if task.status.state == TaskState.FAILED:
            err = (
                task.status.message.text()
                if task.status.message
                else "(no error message)"
            )
            raise A2AClientError(f"remote task failed: {err}")
        if task.status.state == TaskState.CANCELED:
            raise A2AClientError("remote task was canceled")
        if task.status.state != TaskState.COMPLETED:
            raise A2AClientError(
                f"remote task did not reach a terminal state: {task.status.state}"
            )

        outputs = _artifacts_to_outputs(task.artifacts, declared_outputs)
        return outputs, task

    # ── Building blocks (also useful in tests) ────────────────────────

    def fetch_agent_card(self, url: str, auth: Optional[A2AAuth] = None) -> AgentCard:
        headers = _resolve_auth_headers(auth)
        try:
            response = self._client().get(
                url, headers=headers, timeout=_DEFAULT_CARD_TIMEOUT
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise A2AClientError(
                f"AgentCard fetch failed: HTTP {exc.response.status_code} from {url}"
            )
        except httpx.HTTPError as exc:
            raise A2AClientError(f"AgentCard fetch failed: {exc}")
        try:
            return AgentCard.model_validate(response.json())
        except Exception as exc:
            raise A2AClientError(f"AgentCard payload invalid: {exc}")

    def _assert_skill_advertised(self, card: AgentCard, skill_id: str) -> None:
        advertised = {s.id for s in card.skills}
        if skill_id not in advertised:
            raise A2AClientError(
                f"skill {skill_id!r} not advertised by agent {card.name!r} "
                f"({sorted(advertised)})"
            )

    def _send_task(
        self,
        card: AgentCard,
        skill_id: str,
        message: Message,
        auth: Optional[A2AAuth] = None,
        timeout: Optional[int] = None,
    ) -> Task:
        rpc_id = str(uuid.uuid4())
        # The skill is encoded into the params per the A2A spec — Enclave's
        # own server (a2a_service.py) reads `skillId` from params; that's
        # the convention we follow outbound too.
        payload = {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "method": "tasks/send",
            "params": {
                "id": str(uuid.uuid4()),
                "skillId": skill_id,
                "message": message.model_dump(by_alias=True),
            },
        }
        headers = {"Content-Type": "application/json", **_resolve_auth_headers(auth)}
        url = _agent_rpc_url(card)
        try:
            response = self._client().post(
                url,
                json=payload,
                headers=headers,
                timeout=timeout or _DEFAULT_RPC_TIMEOUT,
            )
            response.raise_for_status()
            body = response.json()
        except httpx.HTTPStatusError as exc:
            raise A2AClientError(
                f"tasks/send failed: HTTP {exc.response.status_code} from {url}"
            )
        except httpx.HTTPError as exc:
            raise A2AClientError(f"tasks/send failed: {exc}")
        except json.JSONDecodeError as exc:
            raise A2AClientError(f"tasks/send returned non-JSON: {exc}")

        if "error" in body and body["error"]:
            raise A2AClientError(f"tasks/send returned RPC error: {body['error']}")
        result = body.get("result")
        if not result:
            raise A2AClientError("tasks/send response missing result")
        try:
            return Task.model_validate(result)
        except Exception as exc:
            raise A2AClientError(f"tasks/send result invalid Task: {exc}")

    def _wait_for_terminal(
        self,
        card: AgentCard,
        task: Task,
        auth: Optional[A2AAuth] = None,
        timeout: Optional[int] = None,
    ) -> Task:
        """Poll tasks/get until terminal or timeout."""
        if task.status.state in _TERMINAL_STATES:
            return task

        deadline = time.monotonic() + (timeout or _DEFAULT_RPC_TIMEOUT)
        url = _agent_rpc_url(card)
        headers = {"Content-Type": "application/json", **_resolve_auth_headers(auth)}
        while True:
            if time.monotonic() > deadline:
                raise A2AClientError(
                    f"remote task {task.id} did not reach terminal state within "
                    f"{timeout or _DEFAULT_RPC_TIMEOUT}s (last state: {task.status.state})"
                )
            payload = {
                "jsonrpc": "2.0",
                "id": str(uuid.uuid4()),
                "method": "tasks/get",
                "params": {"id": task.id},
            }
            try:
                response = self._client().post(url, json=payload, headers=headers)
                response.raise_for_status()
                body = response.json()
            except (httpx.HTTPError, json.JSONDecodeError) as exc:
                raise A2AClientError(f"tasks/get failed: {exc}")
            if "error" in body and body["error"]:
                raise A2AClientError(f"tasks/get returned RPC error: {body['error']}")
            try:
                task = Task.model_validate(body.get("result") or {})
            except Exception as exc:
                raise A2AClientError(f"tasks/get result invalid Task: {exc}")
            if task.status.state in _TERMINAL_STATES:
                return task
            time.sleep(_POLL_INTERVAL_SECONDS)

    def _send_task_subscribe(
        self,
        card: AgentCard,
        skill_id: str,
        message: Message,
        auth: Optional[A2AAuth] = None,
        timeout: Optional[int] = None,
    ) -> Task:
        """Stream tasks/sendSubscribe and assemble a final Task from the
        SSE events.

        Event format mirrors what Enclave's own a2a router emits — each
        line is `data: <JSON-RPC envelope whose result is either a
        TaskStatusUpdateEvent or a TaskArtifactUpdateEvent>` with an
        optional `data: [DONE]` sentinel at the end. We accumulate
        artifacts as they arrive and terminate on the first status event
        with `final: true`; whichever comes first.
        """
        task_id = str(uuid.uuid4())
        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "tasks/sendSubscribe",
            "params": {
                "id": task_id,
                "skillId": skill_id,
                "message": message.model_dump(by_alias=True),
            },
        }
        headers = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            **_resolve_auth_headers(auth),
        }
        url = _agent_rpc_url(card)

        artifacts: List[Artifact] = []
        final_status: Optional[Any] = None  # TaskStatus when set
        saw_final = False  # whether ANY event arrived with final=True
        from ..models.a2a_models import TaskStatus

        try:
            with self._client().stream(
                "POST",
                url,
                json=payload,
                headers=headers,
                timeout=timeout or _DEFAULT_RPC_TIMEOUT,
            ) as response:
                response.raise_for_status()
                for raw in response.iter_lines():
                    line = raw.decode() if isinstance(raw, bytes) else raw
                    line = line.strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[len("data:") :].strip()
                    if not data or data == "[DONE]":
                        if final_status is None:
                            continue  # let the loop end naturally
                        break
                    try:
                        envelope = json.loads(data)
                    except json.JSONDecodeError:
                        # Tolerate a stray non-JSON keepalive line.
                        continue
                    if isinstance(envelope, dict) and envelope.get("error"):
                        raise A2AClientError(
                            f"tasks/sendSubscribe RPC error: {envelope['error']}"
                        )
                    event = (
                        envelope.get("result") if isinstance(envelope, dict) else None
                    ) or {}
                    if "artifact" in event:
                        try:
                            artifacts.append(Artifact.model_validate(event["artifact"]))
                        except Exception:
                            # An invalid artifact shouldn't poison the rest of
                            # the stream — skip it and keep reading.
                            continue
                    elif "status" in event:
                        try:
                            status = TaskStatus.model_validate(event["status"])
                        except Exception:
                            continue
                        final_status = status
                        if event.get("final") is True:
                            saw_final = True
                            break
        except httpx.HTTPStatusError as exc:
            raise A2AClientError(
                f"tasks/sendSubscribe failed: HTTP {exc.response.status_code} from {url}"
            )
        except httpx.HTTPError as exc:
            raise A2AClientError(f"tasks/sendSubscribe failed: {exc}")

        if not saw_final:
            raise A2AClientError(
                "SSE stream ended without a final status event "
                "(no event carried final=true)"
            )
        return Task(id=task_id, status=final_status, artifacts=artifacts)
