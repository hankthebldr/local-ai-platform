#!/usr/bin/env python3
"""
Inventory metadata tests — LB4-U1.

Covers the unit's verify list:
  - every MODEL_REGISTRY entry carries the intrinsic metadata fields
    (iterates items() — deliberately no count literal, per spec F8);
  - catalog entries surface fit:{score,class,budget_gb,required_gb,basis}
    with fits_ram retained;
  - PATCH /api/inventory/model/{name}/tags accepts HF-style ids
    (nvidia/Qwen3-8B-NVFP4), rejects bad charset / traversal-shaped names,
    stores a PURE dict (no filesystem resolution — nothing but the store
    file is ever written), atomic;
  - GET /api/inventory/recommendations ranks role_fit × fit-class and
    includes not-installed catalog models with a Pull affordance;
  - inventory writes (/pull /remove /unload /discover/refresh, tags PATCH)
    401 with auth on; reads stay open;
  - hardware-profile extraction is behavior-identical (router re-exports).

Run:  pytest tests/test_inventory_meta.py -v
"""

import json
import os
from unittest.mock import patch

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


@pytest.fixture(autouse=True)
def _isolated_tags_store(tmp_path, monkeypatch):
    """Point the tag-override store at a tmp file per test."""
    import api.routers.inventory as inv

    monkeypatch.setattr(inv, "_MODEL_TAGS_FILE", tmp_path / "model_tags.json")
    yield tmp_path


# ── Registry intrinsic metadata ────────────────────────────────────────────


def test_every_registry_entry_carries_intrinsic_fields():
    """Iterates MODEL_REGISTRY.items() — no count literal anywhere (F8)."""
    from models.download import MODEL_REGISTRY

    assert MODEL_REGISTRY  # non-empty, but never a hardcoded size
    for model_id, info in MODEL_REGISTRY.items():
        for field in (
            "quant",
            "params_b",
            "arch_family",
            "context_tokens",
            "size_gb",
            "min_arch",
            "task_tags",
        ):
            assert field in info, f"{model_id} missing {field}"
        assert isinstance(info["quant"], str) and info["quant"]
        assert isinstance(info["params_b"], (int, float)) and info["params_b"] > 0
        assert isinstance(info["arch_family"], str) and info["arch_family"]
        assert isinstance(info["context_tokens"], int) and info["context_tokens"] > 0
        assert isinstance(info["size_gb"], (int, float)) and info["size_gb"] > 0
        assert info["min_arch"] is None or isinstance(info["min_arch"], str)
        assert isinstance(info["task_tags"], list) and info["task_tags"]


def test_task_tags_use_the_composer_task_vocabulary():
    """task_tags are dfStepTemplates keys — the same strings LB2/LB6 use."""
    from api.routers.inventory import TASK_ROLE_MAP
    from models.download import MODEL_REGISTRY

    for model_id, info in MODEL_REGISTRY.items():
        for t in info["task_tags"]:
            assert t in TASK_ROLE_MAP, f"{model_id}: unknown task tag {t!r}"


def test_size_gb_matches_size_string():
    from models.download import MODEL_REGISTRY

    for model_id, info in MODEL_REGISTRY.items():
        parsed = float(info["size"].lower().replace("gb", "").strip())
        assert info["size_gb"] == pytest.approx(parsed), model_id


# ── Catalog fit fields ─────────────────────────────────────────────────────


@patch("api.routers.inventory.requests.get")
def test_catalog_entries_carry_fit_and_intrinsics(mock_get, client):
    mock_get.side_effect = Exception("Connection refused")
    data = client.get("/api/inventory/catalog").json()
    assert data["models"]
    for m in data["models"]:
        assert "fits_ram" in m  # retained for old consumers
        fit = m["fit"]
        for key in ("score", "class", "budget_gb", "required_gb", "basis"):
            assert key in fit, f"{m['id']} fit missing {key}"
        assert fit["class"] in ("good", "tight", "no-fit", "unknown")
        if "extra" not in m.get("tags", []):
            # Registry-backed rows also surface the intrinsic metadata.
            assert "quant" in m and "arch_family" in m
            assert "context_tokens" in m and "task_tags" in m


# ── Tag override PATCH ─────────────────────────────────────────────────────


@patch("api.routers.inventory.requests.get")
def test_tags_patch_accepts_hf_style_name(mock_get, client, _isolated_tags_store):
    mock_get.side_effect = Exception("Connection refused")
    r = client.patch(
        "/api/inventory/model/nvidia/Qwen3-8B-NVFP4/tags",
        json={"tags": ["code_gen", "fast_extract"]},
    )
    assert r.status_code == 200
    assert r.json() == {
        "status": "saved",
        "model": "nvidia/Qwen3-8B-NVFP4",
        "task_tags": ["code_gen", "fast_extract"],
    }
    store = json.loads((_isolated_tags_store / "model_tags.json").read_text())
    assert store == {"nvidia/Qwen3-8B-NVFP4": ["code_gen", "fast_extract"]}


def test_tags_patch_accepts_ollama_style_name(client):
    r = client.patch(
        "/api/inventory/model/huihui_ai/qwen2.5-abliterated:7b/tags",
        json={"tags": ["analyzer"]},
    )
    assert r.status_code == 200


@pytest.mark.parametrize(
    "bad",
    [
        "bad name",  # space
        "a;b",  # shell char
        "x" * 129,  # too long
        "%2e%2e%2fescape",  # encoded junk
    ],
)
def test_tags_patch_rejects_bad_charset(client, bad):
    r = client.patch(f"/api/inventory/model/{bad}/tags", json={"tags": ["analyzer"]})
    assert r.status_code == 400


@pytest.mark.parametrize("shaped", ["../evil", "a/../../etc/passwd", ".hidden", "a..b"])
def test_tags_patch_rejects_traversal_shaped_names(
    client, shaped, _isolated_tags_store
):
    """Dots and slashes are legal id chars, but leading-dot and `..` shapes
    are refused outright — defense in depth on top of the pure dict store.
    `../` segments are URL-normalized away before routing (404); shapes that
    survive normalization reach the route guard and 400. Either way the
    request never succeeds and nothing is written."""
    r = client.patch(f"/api/inventory/model/{shaped}/tags", json={"tags": ["analyzer"]})
    assert r.status_code in (400, 404, 405)
    # No file was written anywhere for the rejected name.
    assert not (_isolated_tags_store / "model_tags.json").exists()


def test_tags_route_guard_rejects_dotdot_directly():
    """Route-level guard check without URL normalization in the way."""
    from fastapi import HTTPException

    import api.routers.inventory as inv

    for bad in ("../evil", "a/../../etc/passwd", ".hidden", "a..b", "/abs"):
        assert (
            not inv._MODEL_NAME_RE.match(bad)
            or ".." in bad
            or bad.startswith(("/", "."))
        ), f"{bad!r} must be refused by the guard"
    assert inv._MODEL_NAME_RE.match("nvidia/Qwen3-8B-NVFP4")
    # And the handler itself 400s on a guard hit.
    import anyio

    async def _call():
        return await inv.patch_model_tags("a..b", inv.ModelTagsRequest(tags=[]))

    with pytest.raises(HTTPException) as exc:
        anyio.run(_call)
    assert exc.value.status_code == 400


def test_tags_patch_never_resolves_name_as_path(client, _isolated_tags_store):
    """A slashed name is a dict KEY — the only file touched is the store."""
    r = client.patch(
        "/api/inventory/model/deep/nested/model:tag/tags", json={"tags": ["custom"]}
    )
    assert r.status_code == 200
    written = sorted(p.name for p in _isolated_tags_store.iterdir())
    assert written == ["model_tags.json"]  # no deep/nested/... tree
    store = json.loads((_isolated_tags_store / "model_tags.json").read_text())
    assert store == {"deep/nested/model:tag": ["custom"]}


def test_tags_patch_rejects_bad_tag_charset(client):
    r = client.patch(
        "/api/inventory/model/dolphin3/tags", json={"tags": ["ok", "bad tag!"]}
    )
    assert r.status_code == 400


def test_tags_patch_empty_list_clears_override(client, _isolated_tags_store):
    client.patch("/api/inventory/model/dolphin3/tags", json={"tags": ["analyzer"]})
    r = client.patch("/api/inventory/model/dolphin3/tags", json={"tags": []})
    assert r.status_code == 200
    store = json.loads((_isolated_tags_store / "model_tags.json").read_text())
    assert "dolphin3" not in store


@patch("api.routers.inventory.requests.get")
def test_tag_override_surfaces_in_catalog(mock_get, client):
    mock_get.side_effect = Exception("Connection refused")
    client.patch(
        "/api/inventory/model/dolphin3/tags", json={"tags": ["decision", "planner"]}
    )
    data = client.get("/api/inventory/catalog").json()
    row = next(m for m in data["models"] if m["id"] == "dolphin3")
    assert row["task_tags"] == ["decision", "planner"]


# ── Recommendations ────────────────────────────────────────────────────────


def _stable_budget(monkeypatch, budget=80.0, arch="cpu_x86"):
    """Pin detect_budget so rankings don't depend on the CI host's RAM."""
    from api.services import model_fit

    monkeypatch.setattr(
        model_fit,
        "detect_budget",
        lambda: (budget, "profile:max_model_ram_gb", arch, None),
    )


@patch("api.routers.inventory.requests.get")
def test_recommendations_ranked_descending(mock_get, client, monkeypatch):
    mock_get.side_effect = Exception("Connection refused")
    _stable_budget(monkeypatch)
    data = client.get("/api/inventory/recommendations?intent=code_gen").json()
    assert data["intent"] == "code_gen"
    assert data["role"] == "coding"  # task → role derivation
    scores = [r["score"] for r in data["results"]]
    assert scores == sorted(scores, reverse=True)
    for r in data["results"]:
        assert "factors" in r and "fit" in r
        assert r["factors"]["role_fit"]["role"] == "coding"


@patch("api.routers.inventory.requests.get")
def test_recommendations_coding_intent_prefers_coder_model(
    mock_get, client, monkeypatch
):
    """Benchmarked coding role_fit (95) + task-tag boost puts the coder 7B
    on top for code_gen on a CPU-class host where every small model fits."""
    mock_get.side_effect = Exception("Connection refused")
    _stable_budget(monkeypatch)
    data = client.get("/api/inventory/recommendations?intent=code_gen").json()
    assert data["results"][0]["id"] == "qwen2.5-coder-7b-abliterated"


@patch("api.routers.inventory.requests.get")
def test_recommendations_include_not_installed_with_pull(mock_get, client, monkeypatch):
    mock_get.side_effect = Exception("Connection refused")  # nothing installed
    _stable_budget(monkeypatch)
    data = client.get("/api/inventory/recommendations?intent=analyzer&limit=50").json()
    not_installed = [r for r in data["results"] if not r["installed"]]
    assert not_installed, "catalog models must appear even when not installed"
    for r in not_installed:
        assert r["pull"] is not None and r["pull"]["action"] == "pull"


@patch("api.routers.inventory.requests.get")
def test_recommendations_no_fit_zeroes_score(mock_get, client, monkeypatch):
    """On a tiny budget, an over-budget model's fit-class multiplier (0.0)
    zeroes its score regardless of role_fit."""
    mock_get.side_effect = Exception("Connection refused")
    _stable_budget(monkeypatch, budget=5.0)
    data = client.get("/api/inventory/recommendations?intent=reasoning&limit=50").json()
    big = next(r for r in data["results"] if r["id"] == "qwen3.5-uncensored-35b")
    assert big["fit"]["class"] == "no-fit"
    assert big["score"] == 0.0


@patch("api.routers.inventory.requests.get")
def test_recommendations_role_intent_passthrough(mock_get, client, monkeypatch):
    mock_get.side_effect = Exception("Connection refused")
    _stable_budget(monkeypatch)
    data = client.get("/api/inventory/recommendations?intent=coding").json()
    assert data["role"] == "coding"


# ── Auth gates ─────────────────────────────────────────────────────────────


def test_inventory_writes_401_with_auth_on(client, monkeypatch):
    monkeypatch.setenv("ENABLE_API_AUTH", "true")
    monkeypatch.delenv("MASTER_API_KEY", raising=False)
    posts = [
        ("/api/inventory/pull", {"model": "m"}),
        ("/api/inventory/remove", {"model": "m"}),
        ("/api/inventory/unload", {"model": "m"}),
        ("/api/inventory/discover/refresh", {}),
    ]
    for path, body in posts:
        r = client.post(path, json=body)
        assert r.status_code == 401, f"{path} should 401 without a master key"
    r = client.patch("/api/inventory/model/dolphin3/tags", json={"tags": ["a"]})
    assert r.status_code == 401


def test_inventory_reads_carry_no_master_key_gate():
    """Read-open annotation: GET catalog/recommendations/enrichment have no
    require_master_key dependency, while the write routes do. (The global
    API-key middleware still fronts everything when auth is on — read-open
    is relative to the master-key admin tier, matching prompts /recommend.)"""
    from api.routers.inventory import router

    def _has_gate(path, method):
        # Name-based match — the client fixture reloads api.middleware, so
        # identity comparison would see a different function object.
        for route in router.routes:
            if route.path == path and method in route.methods:
                return any(
                    getattr(getattr(d, "call", None), "__name__", "")
                    == "require_master_key"
                    for d in route.dependant.dependencies
                )
        raise AssertionError(f"route {method} {path} not found")

    for path in (
        "/api/inventory/catalog",
        "/api/inventory/recommendations",
        "/api/inventory/enrichment",
    ):
        assert not _has_gate(path, "GET"), f"{path} must stay read-open"
    for path, method in (
        ("/api/inventory/pull", "POST"),
        ("/api/inventory/remove", "POST"),
        ("/api/inventory/unload", "POST"),
        ("/api/inventory/discover/refresh", "POST"),
        ("/api/inventory/model/{name:path}/tags", "PATCH"),
    ):
        assert _has_gate(path, method), f"{path} must be master-key gated"


# ── Hardware-profile extraction (behavior-identical re-export) ─────────────


def test_router_reexports_hardware_profile_service():
    """The router's names ARE the service's objects — one table, one detector."""
    import api.routers.inventory as inv
    from api.services import hardware_profile as hp

    assert inv.detect_hardware is hp.detect_hardware
    assert inv.HARDWARE_PROFILES is hp.HARDWARE_PROFILES
    assert inv._host_ram_gb is hp._host_ram_gb


def test_detect_hardware_shape_unchanged():
    from api.services.hardware_profile import detect_hardware

    hw = detect_hardware()
    for key in ("profile", "name", "cpu", "threads", "ram_gb", "max_model_ram_gb"):
        assert key in hw
    assert hw["max_model_ram_gb"] <= hw["ram_gb"]
