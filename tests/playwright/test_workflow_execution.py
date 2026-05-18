"""
Workflow execution — validates the multi-stage, multi-model
xsiam-detection-engineering workflow shipped this iteration.

API-driven (not browser-driven) because the workflow runs against the
real models and takes several minutes. The UI's role is to surface
results; the workflow ENGINE's correctness lives at the API layer.

Two flavors:
  * Smoke (default): workflow is discoverable + has the expected shape.
  * Slow (@pytest.mark.slow): actually execute against ollama. Skipped
    unless `pytest -m slow` is passed.
"""

from __future__ import annotations

import pytest
import requests


def test_xsiam_detection_workflow_in_catalogue(base_url, api_headers):
    """The 6-stage detection-engineering workflow must be listed."""
    r = requests.get(f"{base_url}/api/workflows", headers=api_headers, timeout=10)
    r.raise_for_status()
    wfs = r.json()
    by_id = {w["id"]: w for w in wfs}
    assert "xsiam-detection-engineering" in by_id, (
        f"xsiam-detection-engineering missing from catalogue. Found: "
        f"{sorted(by_id.keys())}"
    )
    wf = by_id["xsiam-detection-engineering"]
    assert wf["steps"] == 6, f"Expected 6 steps, got {wf['steps']}"


def test_xsiam_detection_workflow_uses_three_models(base_url, api_headers):
    """Inspect the parsed workflow definition: every step must declare a
    model, and the set across steps must include at least 3 distinct
    models (the value-prop of the multi-model design)."""
    r = requests.get(
        f"{base_url}/api/workflows/xsiam-detection-engineering",
        headers=api_headers,
        timeout=10,
    )
    r.raise_for_status()
    defn = r.json()
    steps = defn.get("steps", [])
    models = {s.get("model") for s in steps if s.get("model")}
    assert (
        len(models) >= 3
    ), f"Workflow must use ≥3 distinct models; got {sorted(models)}"
    # Sanity: the three specific models we shipped with
    expected_models = {"llama3.2:3b", "qwen2.5:1.5b", "qwen2.5-coder:1.5b"}
    assert expected_models.issubset(
        models
    ), f"Missing expected models. Want {expected_models}, got {models}"


def test_xsiam_detection_workflow_has_complex_context_wiring(base_url, api_headers):
    """Steps after the first must reference upstream step outputs via
    namespace.key inputs. This is the 'complex context' the design
    requires — not just seed-only steps."""
    r = requests.get(
        f"{base_url}/api/workflows/xsiam-detection-engineering",
        headers=api_headers,
        timeout=10,
    )
    r.raise_for_status()
    steps = r.json().get("steps", [])
    # Step 4 (draft_detection) is the heaviest consumer — must pull from
    # multiple upstream steps.
    draft = next((s for s in steps if s["id"] == "draft_detection"), None)
    assert draft is not None, "draft_detection step missing"
    upstream_refs = [i for i in draft.get("inputs", []) if not i.startswith("seed.")]
    assert len(upstream_refs) >= 4, (
        f"draft_detection should consume ≥4 upstream-step outputs; "
        f"got {upstream_refs}"
    )
    namespaces = {i.split(".", 1)[0] for i in upstream_refs}
    assert len(namespaces) >= 3, (
        f"draft_detection should aggregate from ≥3 upstream steps; "
        f"got namespaces {namespaces}"
    )


def test_xsiam_detection_workflow_references_skill_keywords(base_url, api_headers):
    """At least one step's prompt must mention an xdm-toolkit skill
    trigger ('xql' / 'xdm') and one must mention a web-search trigger
    ('search' / 'find online'). This is how the workflow couples to the
    2 skills the design calls for."""
    r = requests.get(
        f"{base_url}/api/workflows/xsiam-detection-engineering",
        headers=api_headers,
        timeout=10,
    )
    r.raise_for_status()
    steps = r.json().get("steps", [])
    all_prompts = " ".join(
        (s.get("system_prompt") or "") + " " + str(s.get("prompt") or "") for s in steps
    ).lower()
    assert (
        "xdm" in all_prompts or "xql" in all_prompts
    ), "No step prompt references xdm-toolkit skill triggers (xql/xdm)"
    assert (
        "search" in all_prompts
    ), "No step prompt references web-search skill trigger (search)"


@pytest.mark.slow
def test_xsiam_detection_workflow_executes_end_to_end(base_url, api_headers):
    """Full execution against the real models. Marked @slow because it
    takes ~4-5 minutes wall-clock on a small dev box."""
    sample_alert = {
        "alert_id": "ALR-PLAYWRIGHT-001",
        "raw_log": (
            "May 17 03:42:18 sso-edge AcmeAuth[2031]: AUTH_FAIL "
            "src_ip=185.220.101.45 user=alice@example.com "
            "host=workstation-07 reason=invalid_credentials attempts=14"
        ),
        "asset_info": {
            "hostname": "workstation-07",
            "owner": "alice@example.com",
            "criticality": "high",
        },
    }
    r = requests.post(
        f"{base_url}/api/workflows/run",
        headers=api_headers,
        json={"workflow_id": "xsiam-detection-engineering", "seed": sample_alert},
        timeout=600,
    )
    assert (
        r.status_code == 200
    ), f"Workflow run failed: HTTP {r.status_code} — {r.text[:300]}"
    run = r.json()
    assert (
        run["status"] == "completed"
    ), f"Workflow status={run['status']!r}, expected 'completed'. error={run.get('error')!r}"
    results = run.get("step_results", [])
    assert len(results) == 6, f"Expected 6 step results, got {len(results)}"
    for s in results:
        assert (
            s["status"] == "completed"
        ), f"Step {s['step_id']!r} did not complete: {s.get('error')}"
    # All 3 models actually used
    used_models = {s.get("model_used") for s in results}
    assert len(used_models) >= 3, f"Expected ≥3 distinct models used; got {used_models}"
