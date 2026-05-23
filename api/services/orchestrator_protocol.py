"""
Orchestrator text protocol — JSON-directive grammar for kind=orchestrator.

The lead agent (planner) is given a system prompt that documents this
protocol along with the worker catalog. On each turn, the planner emits
exactly one JSON object as a fenced code block. The engine extracts and
executes the directive, then re-prompts the planner with the result.

Two directives are defined:

  {"action": "spawn_worker", "worker_id": "...", "task": "...",
   "inputs": {"key": "value", ...}}

  {"action": "complete", "outputs": {"key": "value", ...}}

Why a text protocol rather than native function-calling: many local Ollama
models (uncensored finetunes, older releases, smaller quants) lack reliable
tool-call output. A simple JSON-fenced block works on every model that can
hold the protocol in its system prompt — which is essentially all of them.
Native function-calling can be layered on top later for models that support it
without changing the dispatch logic.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

# Action constants — exposed so callers can grep without re-typing the string.
ACTION_SPAWN = "spawn_worker"
ACTION_COMPLETE = "complete"


# A directive is parsed into one of these two records. `kind` discriminates;
# the other fields are populated only when relevant.
@dataclass
class SpawnDirective:
    worker_id: str
    task: str
    inputs: Dict[str, Any]


@dataclass
class CompleteDirective:
    outputs: Dict[str, Any]


@dataclass
class ParseError:
    message: str
    raw_snippet: str  # Up to ~200 chars of the offending content for the lead


Directive = "SpawnDirective | CompleteDirective | ParseError"


# Match fenced code blocks. We accept ```json (preferred) and bare ``` since
# many models drop the language tag.
_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def parse_last_directive(model_output: str) -> Directive:
    """Extract the LAST directive in the lead's response.

    Why "last": models often think out loud before emitting the directive,
    and may include example JSON earlier in the text (especially in failure
    explanations from prior turns). Anchoring on the last block matches the
    pattern operators expect from chain-of-thought-style responses.

    Falls back to greedy-balanced parsing if no fence is present. Returns a
    ParseError when the response yields nothing the engine can dispatch.
    """
    if not model_output or not isinstance(model_output, str):
        return ParseError(
            message="lead emitted empty response",
            raw_snippet=(model_output or "")[:200],
        )

    candidates = _FENCE_RE.findall(model_output)
    raw_json: Optional[str] = None
    if candidates:
        raw_json = candidates[-1].strip()
    else:
        # No fenced block — try the last balanced {...} in the text.
        raw_json = _last_balanced_object(model_output)

    if not raw_json:
        return ParseError(
            message=(
                "no JSON directive found in lead response — emit one fenced "
                "```json {...}``` block per turn"
            ),
            raw_snippet=model_output[-200:],
        )

    try:
        parsed = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        return ParseError(
            message=f"directive JSON is malformed: {exc}",
            raw_snippet=raw_json[:200],
        )

    if not isinstance(parsed, dict) or "action" not in parsed:
        return ParseError(
            message=(
                "directive must be a JSON object with an `action` field "
                f"({ACTION_SPAWN!r} or {ACTION_COMPLETE!r})"
            ),
            raw_snippet=raw_json[:200],
        )

    action = parsed.get("action")
    if action == ACTION_SPAWN:
        worker_id = parsed.get("worker_id")
        task = parsed.get("task")
        inputs = parsed.get("inputs") or {}
        if not isinstance(worker_id, str) or not worker_id:
            return ParseError(
                message="spawn_worker requires non-empty `worker_id`",
                raw_snippet=raw_json[:200],
            )
        if not isinstance(task, str) or not task.strip():
            return ParseError(
                message="spawn_worker requires non-empty `task`",
                raw_snippet=raw_json[:200],
            )
        if not isinstance(inputs, dict):
            return ParseError(
                message="spawn_worker `inputs` must be a JSON object",
                raw_snippet=raw_json[:200],
            )
        return SpawnDirective(worker_id=worker_id, task=task, inputs=inputs)

    if action == ACTION_COMPLETE:
        outputs = parsed.get("outputs")
        if not isinstance(outputs, dict):
            return ParseError(
                message="complete requires `outputs` as a JSON object",
                raw_snippet=raw_json[:200],
            )
        return CompleteDirective(outputs=outputs)

    return ParseError(
        message=(
            f"unknown action {action!r}; expected {ACTION_SPAWN!r} or "
            f"{ACTION_COMPLETE!r}"
        ),
        raw_snippet=raw_json[:200],
    )


def _last_balanced_object(text: str) -> Optional[str]:
    """Return the last balanced {...} substring, or None.

    Walks the text from the right, finding the closing brace then scanning
    backward for the matching opener. Returns the matched substring on
    success — not a guarantee of valid JSON, just a balanced shape.
    """
    last_close = text.rfind("}")
    if last_close == -1:
        return None
    depth = 0
    for i in range(last_close, -1, -1):
        ch = text[i]
        if ch == "}":
            depth += 1
        elif ch == "{":
            depth -= 1
            if depth == 0:
                return text[i : last_close + 1]
    return None


def render_worker_catalog(workers: Dict[str, Any]) -> str:
    """Render the worker catalog for inclusion in the planner system prompt.

    Each worker becomes a line listing its id, the input keys it expects
    (from its `seed.<name>` declarations), the output keys it produces,
    and a one-line description (the worker's `name` field).
    """
    if not workers:
        return "(no workers registered — this orchestrator step is misconfigured)"
    lines: List[str] = []
    for worker_id in sorted(workers.keys()):
        worker = workers[worker_id]
        input_names = [
            ref.split(".", 1)[1] if ref.startswith("seed.") else ref
            for ref in (worker.inputs or [])
        ]
        outputs = list(worker.outputs or [])
        descr = getattr(worker, "name", None) or worker_id
        lines.append(
            f"  - {worker_id} — {descr}\n"
            f"      inputs:  {input_names}\n"
            f"      outputs: {outputs}"
        )
    return "\n".join(lines)


def render_protocol_instructions(
    workers: Dict[str, Any],
    declared_outputs: List[str],
    budget_summary: str,
) -> str:
    """Build the protocol-aware system prompt addendum.

    Appended to the planner's own role/task block when the engine builds the
    chat messages. Operators don't write this — the engine renders it from
    the worker catalog so it stays in sync with what the step actually accepts.
    """
    return (
        "## Orchestration Protocol\n"
        "\n"
        "You are the lead agent for a multi-agent investigation. You may call "
        "specialist workers to gather information, then synthesize their "
        "findings.\n"
        "\n"
        "On every turn, emit EXACTLY ONE JSON object inside a fenced code block. "
        "Two actions are valid:\n"
        "\n"
        "**spawn_worker** — dispatch one worker. Wait for the engine to return "
        "its result before deciding next steps.\n"
        "```json\n"
        '{"action": "spawn_worker", "worker_id": "<id>", '
        '"task": "<one-line directive>", "inputs": {"<key>": "<value>"}}\n'
        "```\n"
        "\n"
        "**complete** — finish the task. `outputs` must include every "
        f"declared output key: {sorted(declared_outputs)}.\n"
        "```json\n"
        '{"action": "complete", "outputs": {<every-declared-output-key>: <value>}}\n'
        "```\n"
        "\n"
        f"### Worker Catalog\n{render_worker_catalog(workers)}\n"
        "\n"
        f"### Budget\n{budget_summary}\n"
        "\n"
        "Spawn workers in waves: gather information, synthesize, spawn follow-ups "
        "only if needed. Emit `complete` as soon as you have enough.\n"
    )


def format_worker_result(
    worker_id: str,
    outputs: Optional[Dict[str, Any]],
    error: Optional[str] = None,
) -> str:
    """Format a worker's outputs as a user-role message to feed back to the
    lead. Always returns a JSON-formatted string so the lead can parse it
    structurally if it chooses to."""
    if error is not None:
        body = {"worker_id": worker_id, "status": "failed", "error": error}
    else:
        body = {"worker_id": worker_id, "status": "completed", "outputs": outputs or {}}
    return (
        f"Worker `{worker_id}` returned:\n```json\n"
        + json.dumps(body, indent=2, default=str)
        + "\n```"
    )


def format_parse_error_feedback(err: ParseError) -> str:
    """Format a directive parse error as a user-role message that nudges
    the lead toward valid output without revealing the engine's internals."""
    return (
        f"Your last response could not be parsed as an orchestrator directive: "
        f"{err.message}\n"
        f"Snippet: {err.raw_snippet!r}\n"
        f"Re-emit the directive as a single fenced ```json {{...}}``` block."
    )
