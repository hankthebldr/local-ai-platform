#!/usr/bin/env python3
"""LB2-U1 — hook prompt kind, meta sidecars, master-key-gated prompt writes.

Covers the unit's verify list:
  - hook CRUD roundtrip in the user layer (frontmatter-validated at save);
  - bad stage / stage-mismatch / unknown target / unknown config key /
    missing required config → 400;
  - meta sidecar write / patch-merge / delete-unlink (roles+templates);
    hooks merge meta into their frontmatter (no sidecar file);
  - oob meta PATCH copies-on-write into the user layer;
  - listing ignores `*.meta.json` sidecars (guard test);
  - all prompt writes 401 with auth on (reads stay open);
  - POST /hook/{pid}/test returns factory-instantiation + HookResult
    action/feedback dry-run on a sample;
  - traversal ids rejected on the new meta + hook-test routes (this repo
    had a real glob-traversal incident — every new file route gets this);
  - custom api/hooks/custom/*.py hooks list as read-only always-on entries
    WITHOUT being imported/executed;
  - shipped seed presets in prompts/hooks/ all pass save-time validation;
  - frozen engine files untouched (validation uses read-only imports only).

Run:  pytest tests/test_prompts_hooks.py -q
"""

from __future__ import annotations

import importlib
import json
import os
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from api.routers import prompts as prompts_router
from api.services import prompt_meta

_REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def client():
    os.environ["ENABLE_API_AUTH"] = "false"
    os.environ["RATE_LIMIT_RPM"] = "0"
    import api.middleware

    importlib.reload(api.middleware)
    import api.main

    importlib.reload(api.main)
    from api.main import app

    return TestClient(app)


@pytest.fixture
def layers(tmp_path, monkeypatch):
    """Isolated two-layer prompt store: seeded oob tree + empty user tree."""
    oob = tmp_path / "oob-prompts"
    user = tmp_path / "user-prompts"
    for sub in ("roles", "templates", "hooks"):
        (oob / sub).mkdir(parents=True)
    (oob / "roles" / "shipped_role.md").write_text(
        "# Shipped Role\nYou review {{ artifact }} carefully.", encoding="utf-8"
    )
    (oob / "hooks" / "shipped_gate.md").write_text(_hook_body(), encoding="utf-8")
    monkeypatch.setattr(prompts_router, "_OOB_ROOT", oob)
    monkeypatch.setattr(prompts_router, "_user_root", lambda: user)
    return {"oob": oob, "user": user}


def _hook_body(
    stage="validate_output",
    target="json_schema",
    config=None,
    tags=("json", "gate"),
    rationale="# Gate\n\nRationale text.",
):
    cfg = (
        {"schema": {"type": "object", "required": ["a"]}} if config is None else config
    )
    fm = {
        "stage": stage,
        "target": target,
        "config": cfg,
        "tags": list(tags),
        "intended_output": "Validated JSON object",
    }
    return "---\n" + yaml.safe_dump(fm, sort_keys=False) + "---\n\n" + rationale


# ── Hook CRUD in the user layer ─────────────────────────────────────────────


def test_hook_crud_roundtrip_user_layer(client, layers):
    r = client.post(
        "/api/prompts",
        json={"id": "my_gate", "kind": "hook", "body": _hook_body()},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["provenance"] == "user"
    assert body["stage"] == "validate_output"
    assert body["target"] == "json_schema"
    assert body["tags"] == ["json", "gate"]
    assert (layers["user"] / "hooks" / "my_gate.md").is_file()
    assert not (layers["oob"] / "hooks" / "my_gate.md").exists()

    # listed under kind=hook with frontmatter-derived fields
    rows = client.get("/api/prompts?kind=hook").json()
    mine = next(x for x in rows if x["id"] == "my_gate")
    assert mine["stage"] == "validate_output" and mine["target"] == "json_schema"
    assert isinstance(mine["token_estimate"], int) and mine["token_estimate"] > 0

    # PATCH replaces the body (still validated)
    r = client.patch(
        "/api/prompts/hook/my_gate",
        json={"body": _hook_body(rationale="# Gate v2\n\nUpdated.")},
    )
    assert r.status_code == 200
    assert "v2" in r.json()["body"]

    # GET carries the full frontmatter as meta
    got = client.get("/api/prompts/hook/my_gate").json()
    assert got["meta"]["config"]["schema"]["type"] == "object"

    # DELETE removes the user file
    assert client.delete("/api/prompts/hook/my_gate").status_code == 200
    assert client.get("/api/prompts/hook/my_gate").status_code == 404


def test_hook_oob_patch_copy_on_write_and_delete_403(client, layers):
    oob_file = layers["oob"] / "hooks" / "shipped_gate.md"
    original = oob_file.read_text(encoding="utf-8")
    r = client.patch(
        "/api/prompts/hook/shipped_gate",
        json={"body": _hook_body(rationale="# Edited preset")},
    )
    assert r.status_code == 200
    assert r.json()["provenance"] == "user"
    assert oob_file.read_text(encoding="utf-8") == original
    assert (layers["user"] / "hooks" / "shipped_gate.md").is_file()
    # revert, then pure-oob delete is refused
    assert client.delete("/api/prompts/hook/shipped_gate").status_code == 200
    assert client.delete("/api/prompts/hook/shipped_gate").status_code == 403


# ── Save-time validation ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "body,fragment",
    [
        ("# no frontmatter at all", "frontmatter"),
        (_hook_body(stage="not_a_stage"), "StepHooks stages"),
        # before_step is a legal stage but json_schema declares validate_output
        (_hook_body(stage="before_step"), "declares stage"),
        (_hook_body(target="not_a_builtin"), "built-in"),
        (_hook_body(config={"schema": {}, "bogus_key": 1}), "unknown config key"),
        # plugin_tool_invoker requires plugin_id/tool_id/store_as
        (
            _hook_body(
                stage="before_step",
                target="plugin_tool_invoker",
                config={"plugin_id": "xdm-toolkit"},
            ),
            "missing required",
        ),
    ],
)
def test_hook_validation_rejects_400(client, layers, body, fragment):
    r = client.post(
        "/api/prompts", json={"id": "bad_hook", "kind": "hook", "body": body}
    )
    assert r.status_code == 400, r.text
    assert fragment.lower() in r.json()["detail"].lower()
    assert not (layers["user"] / "hooks" / "bad_hook.md").exists()


def test_hook_stage_vocabulary_is_step_scoped():
    """The five StepHooks stages, read via read-only model import."""
    assert prompts_router._hook_stages() == (
        "before_step",
        "transform_prompt",
        "after_step",
        "validate_output",
        "on_failure",
    )
    assert len(prompts_router._hook_factories()) == 10


def test_seed_presets_ship_valid():
    """Every repo-shipped prompts/hooks/*.md passes save-time validation."""
    seeds = sorted((_REPO / "prompts" / "hooks").glob("*.md"))
    assert len(seeds) >= 3, "seed presets derived from the xdm workflows must ship"
    for f in seeds:
        meta = prompts_router._validate_hook_document(f.read_text(encoding="utf-8"))
        assert meta["target"] in prompts_router._hook_factories()


# ── Hook test route (factory instantiation + dry-run) ──────────────────────


def test_hook_test_returns_hookresult_action_feedback(client, layers):
    client.post(
        "/api/prompts", json={"id": "js_gate", "kind": "hook", "body": _hook_body()}
    )

    # conforming sample → continue
    r = client.post(
        "/api/prompts/hook/js_gate/test", json={"sample_output": '{"a": 1}'}
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["ok"] is True and d["target"] == "json_schema"
    assert d["dry_run"]["action"] == "continue"

    # schema-violating sample → fail with feedback
    r = client.post(
        "/api/prompts/hook/js_gate/test", json={"sample_output": '{"b": 2}'}
    )
    assert r.json()["dry_run"]["action"] == "fail"
    assert r.json()["dry_run"]["feedback"]

    # non-validate stages: instantiation only, no dry_run
    client.post(
        "/api/prompts",
        json={
            "id": "budget",
            "kind": "hook",
            "body": _hook_body(
                stage="before_step",
                target="token_budget",
                config={"max_prompt_tokens": 2000},
            ),
        },
    )
    r = client.post("/api/prompts/hook/budget/test", json={"sample_output": "x"})
    assert r.status_code == 200
    assert r.json()["ok"] is True and "dry_run" not in r.json()

    # missing hook → 404; hooks never render → 400
    assert client.post("/api/prompts/hook/nope/test", json={}).status_code == 404
    assert client.post("/api/prompts/hook/js_gate/render", json={}).status_code == 400


# ── Meta sidecars (roles/templates) ─────────────────────────────────────────


def test_meta_sidecar_write_patch_delete_unlink(client, layers):
    client.post(
        "/api/prompts", json={"id": "tagged", "kind": "role", "body": "# T\nBody."}
    )
    r = client.patch(
        "/api/prompts/role/tagged/meta",
        json={
            "tags": ["xql", "review"],
            "category": "review",
            "technique": ["persona"],
            "intended_output": "Review notes",
            "model_fit": ["reasoning", "qwen3-coder"],
            "input_scope": "one diff",
        },
    )
    assert r.status_code == 200, r.text
    meta = r.json()["meta"]
    assert meta["tags"] == ["xql", "review"]
    assert meta["category"] == "review"
    assert isinstance(meta["token_estimate"], int)
    sc = layers["user"] / "roles" / "tagged.meta.json"
    assert sc.is_file()
    assert json.loads(sc.read_text())["model_fit"] == ["reasoning", "qwen3-coder"]

    # second PATCH merges — untouched fields survive
    r = client.patch("/api/prompts/role/tagged/meta", json={"output_scope": "markdown"})
    assert r.json()["meta"]["category"] == "review"
    assert r.json()["meta"]["output_scope"] == "markdown"

    # list surfaces sidecar tags; GET carries full meta
    rows = client.get("/api/prompts?kind=role").json()
    assert next(x for x in rows if x["id"] == "tagged")["tags"] == ["xql", "review"]
    assert client.get("/api/prompts/role/tagged").json()["meta"]["category"] == "review"

    # delete unlinks the sidecar with the prompt
    assert client.delete("/api/prompts/role/tagged").status_code == 200
    assert not sc.exists()


def test_meta_patch_of_oob_prompt_copies_on_write(client, layers):
    r = client.patch(
        "/api/prompts/role/shipped_role/meta",
        json={"tags": ["shipped"], "category": "analysis"},
    )
    assert r.status_code == 200
    # prompt body copied user-side; sidecar lands next to the USER copy
    assert (layers["user"] / "roles" / "shipped_role.md").is_file()
    assert (layers["user"] / "roles" / "shipped_role.meta.json").is_file()
    assert not (layers["oob"] / "roles" / "shipped_role.meta.json").exists()
    assert client.get("/api/prompts/role/shipped_role").json()["provenance"] == "user"


def test_meta_taxonomy_validated(client, layers):
    client.post("/api/prompts", json={"id": "tx", "kind": "role", "body": "# X"})
    r = client.patch("/api/prompts/role/tx/meta", json={"category": "bogus"})
    assert r.status_code == 400 and "category" in r.json()["detail"]
    r = client.patch("/api/prompts/role/tx/meta", json={"technique": ["telepathy"]})
    assert r.status_code == 400 and "technique" in r.json()["detail"]
    # taxonomy constants stay one vocabulary (shared with LB4/LB6)
    assert "security" in prompt_meta.CATEGORIES
    assert "chain-of-thought" in prompt_meta.TECHNIQUES
    assert prompt_meta.MODEL_ROLE_CLASSES == (
        "reasoning",
        "coding",
        "fast",
        "general",
        "uncensored",
    )


def test_hook_meta_merges_into_frontmatter_no_sidecar(client, layers):
    client.post(
        "/api/prompts", json={"id": "fm_hook", "kind": "hook", "body": _hook_body()}
    )
    r = client.patch(
        "/api/prompts/hook/fm_hook/meta",
        json={"tags": ["merged"], "category": "security"},
    )
    assert r.status_code == 200
    hooks_dir = layers["user"] / "hooks"
    assert not (hooks_dir / "fm_hook.meta.json").exists()
    text = (hooks_dir / "fm_hook.md").read_text(encoding="utf-8")
    fm = yaml.safe_load(text.split("\n---", 1)[0][3:])
    assert fm["tags"] == ["merged"] and fm["category"] == "security"
    # the merged document still validates as a hook (stage/target intact)
    assert fm["stage"] == "validate_output"
    rows = client.get("/api/prompts?kind=hook").json()
    assert next(x for x in rows if x["id"] == "fm_hook")["tags"] == ["merged"]


# ── Listing ignores sidecars (guard) ────────────────────────────────────────


def test_listing_ignores_meta_sidecars(client, layers):
    before = {(x["kind"], x["id"]) for x in client.get("/api/prompts").json()}
    # a real sidecar plus a stray hand-planted one
    client.post("/api/prompts", json={"id": "guard", "kind": "role", "body": "# G"})
    client.patch("/api/prompts/role/guard/meta", json={"tags": ["g"]})
    (layers["user"] / "roles" / "stray.meta.json").write_text("{}", encoding="utf-8")
    (layers["user"] / "hooks").mkdir(parents=True, exist_ok=True)
    (layers["user"] / "hooks" / "stray2.meta.json").write_text("{}", encoding="utf-8")
    after = {(x["kind"], x["id"]) for x in client.get("/api/prompts").json()}
    assert after - before == {("role", "guard")}
    assert not any(pid.endswith(".meta") or "meta.json" in pid for _, pid in after)


# ── Auth: every write 401 with auth on; reads stay open ────────────────────


def test_all_prompt_writes_401_with_auth_on(client, layers, monkeypatch):
    monkeypatch.setenv("ENABLE_API_AUTH", "true")
    monkeypatch.delenv("MASTER_API_KEY", raising=False)
    assert (
        client.post(
            "/api/prompts", json={"id": "x1", "kind": "role", "body": "b"}
        ).status_code
        == 401
    )
    assert (
        client.patch("/api/prompts/role/shipped_role", json={"body": "b"}).status_code
        == 401
    )
    assert client.delete("/api/prompts/role/shipped_role").status_code == 401
    assert (
        client.patch(
            "/api/prompts/role/shipped_role/meta", json={"tags": ["t"]}
        ).status_code
        == 401
    )
    assert (
        client.post("/api/prompts/hook/shipped_gate/test", json={}).status_code == 401
    )
    assert client.post("/api/prompts/role/shipped_role/promote").status_code == 401
    # reads carry no require_master_key dependency — with the admin gate
    # lifted (auth off) they answer without any key (the global API-key
    # middleware, not the master gate, is what guards reads when auth is on)
    monkeypatch.setenv("ENABLE_API_AUTH", "false")
    assert client.get("/api/prompts").status_code == 200
    assert client.get("/api/prompts/role/shipped_role").status_code == 200


# ── Traversal discipline on the NEW routes ──────────────────────────────────


def test_new_routes_reject_traversal_ids(client, layers):
    for bad in ("..", "a/b", ".hidden", "x" * 90, "%2e%2e"):
        r = client.patch(f"/api/prompts/role/{bad}/meta", json={"tags": ["t"]})
        assert r.status_code in (400, 404), f"meta: {bad!r} must not reach the fs"
        r = client.post(f"/api/prompts/hook/{bad}/test", json={})
        assert r.status_code in (400, 404), f"test: {bad!r} must not reach the fs"
    # nothing leaked into either user subtree
    for sub in ("roles", "hooks"):
        d = layers["user"] / sub
        assert not d.exists() or not any(d.iterdir())
    # custom- prefix is reserved: cannot be created or tested as a preset
    r = client.post(
        "/api/prompts", json={"id": "custom-evil", "kind": "hook", "body": _hook_body()}
    )
    assert r.status_code == 400
    assert client.post("/api/prompts/hook/custom-evil/test", json={}).status_code == 400


# ── Custom always-on hooks (api/hooks/custom) ───────────────────────────────


def test_custom_hooks_list_read_only_without_execution(
    client, layers, tmp_path, monkeypatch
):
    custom = tmp_path / "custom-hooks"
    custom.mkdir()
    (custom / "__init__.py").write_text("", encoding="utf-8")
    # a module that would EXPLODE if imported — listing must never execute it
    (custom / "audit_trail.py").write_text(
        '"""Audit-trail hook — logs every step output."""\n'
        "raise RuntimeError('listing must not import custom hook modules')\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(prompts_router, "_CUSTOM_HOOKS_DIR", custom)

    rows = client.get("/api/prompts?kind=hook").json()
    entry = next(x for x in rows if x["id"] == "custom-audit_trail")
    assert entry["always_on"] is True
    assert "__init__" not in {x["id"] for x in rows}
    # shipped file-backed presets keep always_on False
    assert next(x for x in rows if x["id"] == "shipped_gate")["always_on"] is False

    # read-only detail serves the source; writes cannot touch it
    got = client.get("/api/prompts/hook/custom-audit_trail")
    assert got.status_code == 200
    assert "RuntimeError" in got.json()["body"]
    assert client.patch(
        "/api/prompts/hook/custom-audit_trail", json={"body": _hook_body()}
    ).status_code in (400, 404)
    assert client.delete("/api/prompts/hook/custom-audit_trail").status_code == 404


# ── Frozen-engine guard ─────────────────────────────────────────────────────


def test_frozen_engine_files_untouched():
    """LB2-U1 consumes StepHooks + builtins via read-only imports only."""
    import subprocess

    out = subprocess.run(
        [
            "git",
            "diff",
            "--name-only",
            "HEAD",
            "--",
            "api/services/workflow_engine.py",
            "api/services/step_executor.py",
            "api/models/workflow_models.py",
        ],
        capture_output=True,
        text=True,
        cwd=_REPO,
    )
    assert out.stdout.strip() == "", f"frozen files modified: {out.stdout}"
