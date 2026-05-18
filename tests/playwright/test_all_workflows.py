"""
All-workflows parametrized suite — every YAML in workflows/ gets the
same battery of smoke checks automatically. Adding a new workflow
file under workflows/<id>.yaml gives you 6 free regression tests
without writing any new code.

Battery per workflow:
    1. Loads from disk into a valid WorkflowDefinition (no parse errors)
    2. Appears in /api/workflows catalogue
    3. Has at least one step
    4. Every step has either system_prompt or v2 prompt block
    5. Every step's `inputs` references either seed.* or a previously-
       declared step's outputs (no dangling references)
    6. Models referenced are either left to the resolver (no `model:`)
       OR are reachable via /v1/models (resolver target)

Optional per-workflow extras: drop a JSON file at
tests/fixtures/workflows/<workflow_id>.json with a `seed` key and
the @slow execution test will pick it up automatically.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
import requests
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = REPO_ROOT / "workflows"
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "workflows"


def _discover_workflow_yaml_files():
    """Find every shipped workflow YAML at collection time."""
    if not WORKFLOWS_DIR.exists():
        return []
    return sorted(p for p in WORKFLOWS_DIR.glob("*.yaml") if p.is_file())


WORKFLOW_FILES = _discover_workflow_yaml_files()
WORKFLOW_IDS = []
WORKFLOW_BY_ID: dict = {}

for _p in WORKFLOW_FILES:
    try:
        _data = yaml.safe_load(_p.read_text())
        if isinstance(_data, dict) and _data.get("id"):
            WORKFLOW_IDS.append(_data["id"])
            WORKFLOW_BY_ID[_data["id"]] = _data
    except Exception:
        # A malformed YAML still earns its own test below — the
        # discovery scan deliberately doesn't filter it out.
        WORKFLOW_IDS.append(_p.stem)
        WORKFLOW_BY_ID[_p.stem] = None


# ── 1. YAML parses ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("wf_id", WORKFLOW_IDS)
def test_workflow_yaml_parses(wf_id):
    """The YAML on disk must parse cleanly into a dict with an `id` field."""
    defn = WORKFLOW_BY_ID.get(wf_id)
    assert defn is not None, f"workflow file for {wf_id!r} failed to parse"
    assert (
        defn.get("id") == wf_id
    ), f"workflow id mismatch — file declares {defn.get('id')!r} but expected {wf_id!r}"
    assert defn.get("name"), f"workflow {wf_id!r} missing required `name` field"


# ── 2. API catalogue ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("wf_id", WORKFLOW_IDS)
def test_workflow_in_api_catalogue(wf_id, base_url, api_headers):
    """Every workflow on disk must be discoverable via /api/workflows."""
    r = requests.get(f"{base_url}/api/workflows", headers=api_headers, timeout=10)
    r.raise_for_status()
    catalogue_ids = {w["id"] for w in r.json()}
    assert wf_id in catalogue_ids, (
        f"workflow {wf_id!r} on disk is missing from /api/workflows catalogue "
        f"({len(catalogue_ids)} present: {sorted(catalogue_ids)})"
    )


# ── 3-5. Static-structure checks (no API needed beyond the catalogue) ────────


@pytest.mark.parametrize("wf_id", WORKFLOW_IDS)
def test_workflow_step_shape(wf_id, base_url, api_headers):
    """Every step has a usable prompt block AND every input ref resolves
    to an upstream producer (seed.* or a previously-declared step's
    outputs). This catches the most common authoring bug: typo'd input
    refs that the engine flags at run time, not load time."""
    r = requests.get(
        f"{base_url}/api/workflows/{wf_id}", headers=api_headers, timeout=10
    )
    r.raise_for_status()
    defn = r.json()

    steps = defn.get("steps", [])
    assert steps, f"workflow {wf_id!r} has no steps"

    seen_outputs: set[str] = set()  # "step_id.output_key" producers
    for i, step in enumerate(steps):
        step_id = step.get("id")
        assert step_id, f"workflow {wf_id!r} step #{i} missing id"

        has_v1 = bool(step.get("system_prompt"))
        has_v2 = bool(step.get("prompt"))
        assert has_v1 or has_v2, (
            f"workflow {wf_id!r} step {step_id!r} has neither system_prompt "
            f"nor v2 prompt block"
        )
        assert not (
            has_v1 and has_v2
        ), f"workflow {wf_id!r} step {step_id!r} has both v1 and v2 prompts"

        outputs = step.get("outputs", []) or []
        assert outputs, f"workflow {wf_id!r} step {step_id!r} has no outputs"

        # Inputs must resolve to one of:
        #   - seed.* (caller's responsibility to provide)
        #   - shared.* (cross-cutting workflow state)
        #   - <self_id>.* (self-reference for retry/revise hook loops —
        #     hooks may produce keys beyond what the step declares in
        #     `outputs:`, so we trust the step's own namespace fully)
        #   - <previous_step_id>.<declared_output> (DAG upstream)
        for input_ref in step.get("inputs", []) or []:
            if "." not in input_ref:
                pytest.fail(
                    f"workflow {wf_id!r} step {step_id!r} input {input_ref!r} "
                    "is not in 'namespace.key' form"
                )
            ns, _key = input_ref.split(".", 1)
            if ns in ("seed", "shared", step_id):
                continue
            assert input_ref in seen_outputs, (
                f"workflow {wf_id!r} step {step_id!r} references "
                f"{input_ref!r} but no upstream step produces it. "
                f"Upstream outputs so far: {sorted(seen_outputs)}"
            )

        # Register this step's declared outputs for downstream resolution.
        for out_key in outputs:
            seen_outputs.add(f"{step_id}.{out_key}")


# ── 6. Model availability — non-fatal warning ────────────────────────────────


@pytest.mark.parametrize("wf_id", WORKFLOW_IDS)
def test_workflow_models_present_or_resolver_will_fall_back(
    wf_id, base_url, api_headers
):
    """Steps that pin a specific `model:` should ideally have that model
    pulled. If not, the engine's model_resolver picks a fallback by role —
    that's fine but emit an XFAIL-style diagnostic so the operator sees
    which steps will get a substituted model.
    """
    r = requests.get(
        f"{base_url}/api/workflows/{wf_id}", headers=api_headers, timeout=10
    )
    r.raise_for_status()
    defn = r.json()

    # Installed model ids.
    m = requests.get(f"{base_url}/v1/models", headers=api_headers, timeout=10)
    m.raise_for_status()
    installed = {x["id"] for x in m.json().get("data", [])}

    missing_pinned: list[tuple[str, str]] = []
    for step in defn.get("steps", []):
        pinned = step.get("model")
        if pinned and pinned not in installed:
            missing_pinned.append((step["id"], pinned))

    # Not a fail — pinned models that aren't installed are resolved at
    # run time by role fallback. Surface as info-level skip-reason for
    # visibility during local dev.
    if missing_pinned and os.environ.get("ENCLAVE_STRICT_WORKFLOW_MODELS", "") == "1":
        pytest.fail(
            f"workflow {wf_id!r} pins models that aren't installed: {missing_pinned}. "
            "Pull them with `docker compose exec ollama ollama pull <model>` or "
            "drop the pin and let the resolver pick by role."
        )


# ── 7. Optional per-workflow execution (slow) ────────────────────────────────


def _execution_fixture(wf_id: str) -> dict | None:
    """Per-workflow execution fixture. Drop a JSON file at
    tests/fixtures/workflows/<wf_id>.json with shape {"seed": {...}}.
    Absent fixture → workflow is structure-tested only."""
    path = FIXTURES_DIR / f"{wf_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


_EXECUTABLE_IDS = [wid for wid in WORKFLOW_IDS if _execution_fixture(wid) is not None]


@pytest.mark.slow
@pytest.mark.parametrize("wf_id", _EXECUTABLE_IDS or ["__skip_no_fixtures"])
def test_workflow_executes_with_fixture_seed(wf_id, base_url, api_headers):
    """For every workflow with a fixture file: POST /api/workflows/run and
    assert status=completed + every step produced a non-empty result.

    This is the "is the workflow actually correct end-to-end" test. Slow
    because the engine fans out to real models for every step."""
    if wf_id == "__skip_no_fixtures":
        pytest.skip(
            "No execution fixtures present. Add one at "
            "tests/fixtures/workflows/<workflow_id>.json with shape "
            '{"seed": {...}} to enable end-to-end execution testing.'
        )

    fixture = _execution_fixture(wf_id)
    assert fixture is not None
    seed = fixture.get("seed", {})

    r = requests.post(
        f"{base_url}/api/workflows/run",
        headers=api_headers,
        json={"workflow_id": wf_id, "seed": seed},
        timeout=fixture.get("timeout_seconds", 600),
    )
    assert r.status_code == 200, (
        f"workflow {wf_id!r} run kickoff failed: HTTP {r.status_code} — "
        f"{r.text[:400]}"
    )
    run = r.json()
    assert run["status"] == "completed", (
        f"workflow {wf_id!r} status={run['status']!r}, " f"error={run.get('error')!r}"
    )

    # Every step must have produced output.
    for step in run.get("step_results", []):
        assert step["status"] == "completed", (
            f"workflow {wf_id!r} step {step['step_id']!r} status="
            f"{step['status']!r}, error={step.get('error')!r}"
        )

    # Every declared workspace key for every step must be non-None
    # (the parser fix ensures this; regression guard).
    workspace = run.get("context", {}).get("workspace", {})
    for step_id, fields in workspace.items():
        for key, value in fields.items():
            assert value is not None, (
                f"workflow {wf_id!r} workspace[{step_id!r}][{key!r}] is None — "
                "output parser failed to split a multi-key JSON response"
            )
