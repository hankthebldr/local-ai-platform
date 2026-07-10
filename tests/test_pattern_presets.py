"""BU4 — Composer pattern presets round-trip the frozen workflow model.

The Composer's Patterns bench (``dfPatternTemplates`` in
``api/static/js/main.js``) is the single source of truth for the
pattern → engine-kind presets. The presets live as a strict-JSON block
inside a ``String.raw`` template literal precisely so THIS test can parse
the same bytes the browser executes — no mirrored copy to drift.

Every preset's ``steps`` must construct through ``WorkflowDefinition``
(api/models/workflow_models.py — the frozen model IS the validator), and
the pattern table's invariants are pinned explicitly:

  * orchestrator ships >=1 pre-filled worker whose inputs are all seed.*
  * research fan-out is PLAIN parallel (no sharded variant anywhere),
    >=2 branches, gather.outputs set-equal to parent.outputs
  * TDD loop's LAST body step (the critic) produces every loop output
  * ralph body = plan -> execute -> verify -> consolidate with a
    ralph:{journal_path, halt} block; both budget presets validate
  * cross-field exclusivity: non-llm steps never carry a step-level
    system_prompt/prompt; a2a never carries model/role
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from api.models.workflow_models import WorkflowDefinition

MAIN_JS = Path(__file__).resolve().parent.parent / "api" / "static" / "js" / "main.js"

# Matches the strict-JSON block inside main.js:
#   const dfPatternTemplatesJson = String.raw`\n[ ... ]\n`;
_BLOCK_RE = re.compile(
    r"const dfPatternTemplatesJson = String\.raw`\n(.*?)\n`;", re.DOTALL
)


def _load_presets() -> list[dict]:
    src = MAIN_JS.read_text(encoding="utf-8")
    m = _BLOCK_RE.search(src)
    assert m, (
        "dfPatternTemplatesJson block not found in main.js — the Patterns "
        "bench presets moved or the String.raw wrapper changed; update "
        "_BLOCK_RE to keep this test pinned to the JS source of truth."
    )
    return json.loads(m.group(1))


PRESETS = _load_presets()
PRESET_BY_KEY = {p["key"]: p for p in PRESETS}


def _workflow_for(preset: dict, steps: list[dict] | None = None) -> dict:
    """The workflow dict dfExportYaml would emit around this preset's steps."""
    return {
        "id": f"pattern-{preset['key']}",
        "name": preset["name"],
        "version": "1.0",
        "context": {"inputs": [{"key": "query"}, {"key": "task"}]},
        "steps": steps if steps is not None else preset["steps"],
    }


@pytest.mark.parametrize("preset", PRESETS, ids=[p["key"] for p in PRESETS])
def test_preset_round_trips_workflow_definition(preset):
    """Every preset constructs through the frozen model without error."""
    defn = WorkflowDefinition(**_workflow_for(preset))
    assert len(defn.steps) == len(preset["steps"])
    # The card's declared kind matches the (last) engine step it emits —
    # research fan-out's leading index step is a plain llm helper.
    assert defn.steps[-1].kind == preset["kind"]


@pytest.mark.parametrize("preset", PRESETS, ids=[p["key"] for p in PRESETS])
def test_cross_field_exclusivity(preset):
    """kind != llm never carries a step-level prompt; a2a never model/role."""
    for step in preset["steps"]:
        kind = step.get("kind", "llm")
        if kind != "llm":
            assert "system_prompt" not in step and "prompt" not in step, (
                f"{preset['key']}: step {step['id']} (kind={kind}) must not "
                "declare a step-level prompt"
            )
        if kind == "a2a":
            assert "model" not in step and "role" not in step


def test_llm_step_contract():
    step = PRESET_BY_KEY["llm_step"]["steps"][0]
    assert ("system_prompt" in step) ^ ("prompt" in step)
    assert step["outputs"] == ["text"]


def test_orchestrator_ships_one_valid_worker_with_seed_inputs():
    step = PRESET_BY_KEY["orchestrator"]["steps"][0]
    workers = step["workers"]
    assert len(workers) >= 1, "validator requires >=1 worker"
    for worker_id, worker in workers.items():
        for ref in worker.get("inputs", []):
            assert ref.startswith("seed."), (
                f"orchestrator worker {worker_id!r} input {ref!r} must be seed.*"
            )


def test_research_fanout_is_plain_parallel_with_matching_gather():
    steps = PRESET_BY_KEY["research_fanout"]["steps"]
    parent = steps[-1]
    assert parent["kind"] == "parallel"
    assert len(parent["branches"]) >= 2
    assert set(parent["gather"]["outputs"]) == set(parent["outputs"])
    # No sharded variant in v1 — anywhere in the catalog.
    for preset in PRESETS:
        blob = json.dumps(preset)
        assert '"sharded"' not in blob and '"sharder"' not in blob


def test_tdd_loop_last_body_step_produces_every_loop_output():
    step = PRESET_BY_KEY["tdd_loop"]["steps"][0]
    assert step["kind"] == "loop"
    assert step["until"]["type"] == "gate"
    last_body = step["body"][-1]
    assert last_body["id"] == "critic"
    assert set(step["outputs"]) <= set(last_body["outputs"])
    # The middle test step is a real sandboxed code step.
    assert step["body"][1]["kind"] == "code"


def test_ralph_body_shape_and_journal():
    step = PRESET_BY_KEY["ralph_loop"]["steps"][0]
    assert step["kind"] == "ralph"
    assert [b["id"] for b in step["body"]] == [
        "plan",
        "execute",
        "verify",
        "consolidate",
    ]
    assert step["ralph"]["journal_path"]
    assert "halt" in step["ralph"]
    # Every parent output is produced by SOME body step (ralph contract).
    produced = {o for b in step["body"] for o in b["outputs"]}
    assert set(step["outputs"]) <= produced


@pytest.mark.parametrize("budget", ["standard", "long_running"])
def test_ralph_budget_presets_validate(budget):
    """Both halt-cap presets behind the card's toggle round-trip cleanly —
    mirrors what dfScaffoldPattern stamps onto ralph.halt on drop."""
    preset = PRESET_BY_KEY["ralph_loop"]
    caps = preset["budget_presets"][budget]
    step = json.loads(json.dumps(preset["steps"][0]))  # deep copy
    step["ralph"]["halt"] = {**step["ralph"]["halt"], **caps}
    defn = WorkflowDefinition(**_workflow_for(preset, steps=[step]))
    assert defn.steps[0].ralph.halt.max_iterations == caps["max_iterations"]


def test_code_sandbox_id_is_sandbox_path_safe():
    step = PRESET_BY_KEY["code_sandbox"]["steps"][0]
    assert "/" not in step["id"] and "\\" not in step["id"] and ".." not in step["id"]
    assert step["code"]["source"] == "inline" and step["code"]["code"]
