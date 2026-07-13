#!/usr/bin/env python3
"""LB3-U1 — skills tree / file / relations / promote backend routes.

Covers the spec's verify list:
  - tree/file containment rejects traversal (../, absolute paths, bad
    charset) — this repo had a real glob-traversal incident, so every
    file-serving route gets explicit traversal tests;
  - a single-file skill renders an honest one-node tree, a skill with a
    ``skills/<id>/`` directory renders its contents;
  - relations returns workflows referencing ``<plugin>.<skill>`` via
    step.skills AND skill_injector configs, plus trigger keywords and an
    honestly-empty agents list;
  - promote copies SKILL.md + registration into a user-layer plugin
    (default user-skills), 201 then 409, and the promoted skill is
    visible after the rescan;
  - every route 401s without a key when auth is on;
  - scan errors degrade to empty lists, never 500.
"""

from __future__ import annotations

import importlib
import os

import pytest
import yaml
from fastapi.testclient import TestClient

import api.routers.plugins as plugins_router
import api.routers.skills as skills_router
from api.services.plugin_service import PluginService


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


SKILL_BODY = "---\nname: Rule Writer\ninject: system\n---\n\nWrite XDM rules.\n"


def _make_plugin(base, plugin_id, skills, extra_files=None):
    pdir = base / plugin_id
    (pdir / "skills").mkdir(parents=True)
    manifest = {
        "id": plugin_id,
        "name": plugin_id,
        "version": "1.0.0",
        "skills": [],
    }
    for sid, triggers in skills:
        (pdir / "skills" / f"{sid}.md").write_text(SKILL_BODY, encoding="utf-8")
        manifest["skills"].append(
            {
                "id": sid,
                "file": f"skills/{sid}.md",
                "triggers": [{"keyword": k} for k in triggers] + [{"manual": True}],
            }
        )
    for rel, text in (extra_files or {}).items():
        p = pdir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    (pdir / "plugin.yaml").write_text(
        yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8"
    )
    return pdir


@pytest.fixture()
def layers(tmp_path, monkeypatch):
    """Two-layer plugin env with a REAL PluginService so path resolution and
    containment are exercised for real, plus an isolated workflows dir."""
    system_dir = tmp_path / "system"
    user_dir = tmp_path / "user"
    system_dir.mkdir()
    user_dir.mkdir()

    _make_plugin(
        system_dir,
        "toolkit",
        [("rule-writer", ["write XQL", "XDM rule"]), ("solo-skill", [])],
        extra_files={
            "skills/rule-writer/examples/basic.md": "# example\n",
            "skills/rule-writer/reference.md": "ref\n",
            "secret.txt": "not for the files tab traversal\n",
        },
    )
    service = PluginService(system_dir=system_dir, user_dir=user_dir)
    service.scan_plugins()
    monkeypatch.setattr(plugins_router, "plugin_service", service)

    workflows = tmp_path / "workflows"
    workflows.mkdir()
    (workflows / "uses-step-skills.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "wf-step",
                "name": "Step Skills WF",
                "steps": [
                    {"id": "s1", "skills": ["toolkit.rule-writer"]},
                    {"id": "s2", "skills": ["other.unrelated"]},
                ],
            }
        ),
        encoding="utf-8",
    )
    (workflows / "uses-injector.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "wf-hook",
                "name": "Injector WF",
                "steps": [
                    {
                        "id": "h1",
                        "hooks": {
                            "transform_prompt": [
                                {
                                    "name": "skill_injector",
                                    "config": {"skills": ["toolkit.rule-writer"]},
                                }
                            ]
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (workflows / "broken.yaml").write_text(
        "steps: [::: not yaml", encoding="utf-8"
    )
    monkeypatch.setattr(skills_router, "_WORKFLOWS_DIR", workflows)
    skills_router._rel_cache.update({"ts": 0.0, "map": {}})
    yield {
        "service": service,
        "system": system_dir,
        "user": user_dir,
        "workflows": workflows,
    }
    skills_router._rel_cache.update({"ts": 0.0, "map": {}})


# ── Auth: every new route 401s without a key when auth is on ──────────────


def test_new_routes_401_with_auth_on_and_no_key(client, layers, monkeypatch):
    monkeypatch.setenv("ENABLE_API_AUTH", "true")
    monkeypatch.delenv("MASTER_API_KEY", raising=False)
    gets = [
        "/api/skills/tree/rule-writer",
        "/api/skills/file?plugin_id=toolkit&path=skills/rule-writer.md",
        "/api/skills/relations/rule-writer",
    ]
    for path in gets:
        assert client.get(path).status_code == 401, f"{path} should 401"
    r = client.post("/api/skills/rule-writer/promote", json={})
    assert r.status_code == 401


# ── Tree ───────────────────────────────────────────────────────────────────


def test_tree_single_file_skill_is_one_node(client, layers):
    r = client.get("/api/skills/tree/solo-skill")
    assert r.status_code == 200
    body = r.json()
    assert body["plugin_id"] == "toolkit"
    assert body["origin"] == "system"
    assert body["registration"]["file"] == "skills/solo-skill.md"
    children = body["root"]["children"]
    assert len(children) == 1  # honest one-node tree, nothing synthetic
    node = children[0]
    assert node == {
        "name": "solo-skill.md",
        "path": "skills/solo-skill.md",
        "type": "file",
        "size": node["size"],
        "declared": True,
        "exists": True,
    }
    assert node["size"] > 0
    assert body["node_count"] == 1


def test_tree_with_skill_dir_lists_contents(client, layers):
    r = client.get("/api/skills/tree/rule-writer?plugin_id=toolkit")
    assert r.status_code == 200
    body = r.json()
    children = body["root"]["children"]
    assert children[0]["declared"] is True
    dir_node = children[1]
    assert dir_node["type"] == "dir"
    assert dir_node["path"] == "skills/rule-writer"
    names = {c["name"] for c in dir_node["children"]}
    assert names == {"examples", "reference.md"}
    examples = next(c for c in dir_node["children"] if c["name"] == "examples")
    assert [c["name"] for c in examples["children"]] == ["basic.md"]
    assert body["node_count"] == 5


def test_tree_rejects_bad_ids(client, layers):
    assert client.get("/api/skills/tree/bad%20id!").status_code == 400
    assert (
        client.get("/api/skills/tree/rule-writer?plugin_id=..%2Fevil").status_code
        == 400
    )


def test_tree_404s_on_unknown_skill_or_plugin(client, layers):
    assert client.get("/api/skills/tree/nope").status_code == 404
    assert client.get("/api/skills/tree/rule-writer?plugin_id=nope").status_code == 404
    # registered in a plugin, but not THIS plugin
    _make = client.get("/api/skills/tree/solo-skill?plugin_id=toolkit")
    assert _make.status_code == 200


def test_tree_manifest_declared_traversal_is_400(client, layers):
    """A manifest ``file:`` edited to escape the plugin dir AFTER the last
    scan (stale registry window) is refused by resolved-path containment."""
    evil = _make_plugin(layers["system"], "evil", [("escaper", [])])
    layers["service"].scan_plugins()  # registry now lists the skill
    manifest = yaml.safe_load((evil / "plugin.yaml").read_text())
    manifest["skills"][0]["file"] = "../../outside.md"
    (evil / "plugin.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    # No rescan — the route reads the manifest fresh and must contain it.
    r = client.get("/api/skills/tree/escaper?plugin_id=evil")
    assert r.status_code == 400
    assert "escapes" in r.json()["detail"]


# ── File ───────────────────────────────────────────────────────────────────


def test_file_reads_body(client, layers):
    r = client.get(
        "/api/skills/file", params={"plugin_id": "toolkit", "path": "skills/rule-writer.md"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "rule-writer.md"
    assert body["body"] == SKILL_BODY
    assert body["size"] == len(SKILL_BODY.encode("utf-8"))


def test_file_rejects_traversal(client, layers):
    bad_paths = [
        "../secret.txt",  # parent escape
        "skills/../../toolkit/secret.txt",  # nested dotdot
        "/etc/passwd",  # absolute
        "skills/..%2F..%2Fetc",  # encoded junk fails charset
        "skills/a b.md",  # space fails charset
        "skills\\rule-writer.md",  # backslash
        "skills/./rule-writer.md",  # dot segment
        "",  # empty
    ]
    for path in bad_paths:
        r = client.get(
            "/api/skills/file", params={"plugin_id": "toolkit", "path": path}
        )
        assert r.status_code == 400, f"path {path!r} should be rejected"
    # bad plugin id charset
    r = client.get(
        "/api/skills/file", params={"plugin_id": "../evil", "path": "skills/x.md"}
    )
    assert r.status_code == 400


def test_file_404s(client, layers):
    r = client.get(
        "/api/skills/file", params={"plugin_id": "toolkit", "path": "skills/nope.md"}
    )
    assert r.status_code == 404
    r = client.get(
        "/api/skills/file", params={"plugin_id": "ghost", "path": "skills/x.md"}
    )
    assert r.status_code == 404


def test_file_never_serves_outside_plugin_dir(client, layers, tmp_path):
    """Even a charset-clean path must not resolve outside the plugin dir
    (symlink escape)."""
    link = layers["system"] / "toolkit" / "skills" / "linked.md"
    outside = tmp_path / "outside.md"
    outside.write_text("outside", encoding="utf-8")
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks unavailable")
    r = client.get(
        "/api/skills/file", params={"plugin_id": "toolkit", "path": "skills/linked.md"}
    )
    assert r.status_code == 400


# ── Relations ──────────────────────────────────────────────────────────────


def test_relations_finds_step_skills_and_injector_refs(client, layers):
    r = client.get("/api/skills/relations/rule-writer")
    assert r.status_code == 200
    body = r.json()
    assert body["plugin_id"] == "toolkit"
    assert body["host_plugins"] == ["toolkit"]
    assert body["triggers"] == ["write XQL", "XDM rule"]
    vias = {(w["id"], w["via"], w["step"]) for w in body["workflows"]}
    assert vias == {
        ("wf-step", "step.skills", "s1"),
        ("wf-hook", "skill_injector", "h1"),
    }
    # broken.yaml degraded per-file, never 500; agents honestly empty
    assert body["agents"] == []
    assert "agents_note" in body


def test_relations_empty_for_unreferenced_skill(client, layers):
    r = client.get("/api/skills/relations/solo-skill")
    assert r.status_code == 200
    body = r.json()
    assert body["workflows"] == []
    assert body["triggers"] == []


def test_relations_scan_is_ttl_cached(client, layers):
    client.get("/api/skills/relations/rule-writer")
    (layers["workflows"] / "late.yaml").write_text(
        yaml.safe_dump(
            {"id": "wf-late", "steps": [{"id": "l1", "skills": ["toolkit.rule-writer"]}]}
        ),
        encoding="utf-8",
    )
    ids = {w["id"] for w in client.get("/api/skills/relations/rule-writer").json()["workflows"]}
    assert "wf-late" not in ids  # within TTL — cached scan served
    skills_router._rel_cache.update({"ts": 0.0})  # expire
    ids = {w["id"] for w in client.get("/api/skills/relations/rule-writer").json()["workflows"]}
    assert "wf-late" in ids


def test_relations_missing_workflows_dir_never_500s(client, layers, monkeypatch):
    monkeypatch.setattr(
        skills_router, "_WORKFLOWS_DIR", layers["workflows"] / "does-not-exist"
    )
    skills_router._rel_cache.update({"ts": 0.0, "map": {}})
    r = client.get("/api/skills/relations/rule-writer")
    assert r.status_code == 200
    assert r.json()["workflows"] == []


def test_relations_400_on_bad_id_404_on_unknown(client, layers):
    assert client.get("/api/skills/relations/bad%20id!").status_code == 400
    assert client.get("/api/skills/relations/ghost-skill").status_code == 404


# ── Promote ────────────────────────────────────────────────────────────────


def test_promote_into_default_user_skills_then_409(client, layers):
    r = client.post("/api/skills/rule-writer/promote", json={})
    assert r.status_code == 201
    body = r.json()
    assert body == {
        "promoted": True,
        "skill_id": "rule-writer",
        "source_plugin_id": "toolkit",
        "target_plugin_id": "user-skills",
        "origin": "user",
        "file": "skills/rule-writer.md",
    }
    # Physical copy landed in the user layer with the source body.
    md = layers["user"] / "user-skills" / "skills" / "rule-writer.md"
    assert md.read_text(encoding="utf-8") == SKILL_BODY
    manifest = yaml.safe_load(
        (layers["user"] / "user-skills" / "plugin.yaml").read_text(encoding="utf-8")
    )
    entry = manifest["skills"][0]
    assert entry["id"] == "rule-writer"
    assert entry["file"] == "skills/rule-writer.md"
    # Source triggers travelled with the registration.
    assert {"keyword": "write XQL"} in entry["triggers"]
    # Visible after the rescan — the chat path can inject it immediately.
    service = layers["service"]
    assert service.get_skill("user-skills", "rule-writer") is not None
    assert service.get_plugin("user-skills")["origin"] == "user"
    # Second promote refuses to clobber.
    r2 = client.post("/api/skills/rule-writer/promote", json={})
    assert r2.status_code == 409


def test_promote_into_explicit_target(client, layers):
    layers["service"].ensure_user_plugin("my-pack")
    layers["service"].scan_plugins()
    r = client.post(
        "/api/skills/solo-skill/promote", json={"target_plugin_id": "my-pack"}
    )
    assert r.status_code == 201
    assert r.json()["target_plugin_id"] == "my-pack"
    assert (layers["user"] / "my-pack" / "skills" / "solo-skill.md").is_file()
    # Skill with no keyword triggers still gets a manual attach handle.
    manifest = yaml.safe_load(
        (layers["user"] / "my-pack" / "plugin.yaml").read_text(encoding="utf-8")
    )
    entry = next(s for s in manifest["skills"] if s["id"] == "solo-skill")
    assert {"manual": True} in entry["triggers"]


def test_promote_refuses_system_plugin_target(client, layers):
    """Creating a user-layer 'toolkit' would shadow the entire shipped
    plugin — the route must refuse rather than silently fork it."""
    r = client.post(
        "/api/skills/rule-writer/promote", json={"target_plugin_id": "toolkit"}
    )
    assert r.status_code == 409
    assert "system-layer" in r.json()["detail"]
    assert not (layers["user"] / "toolkit").exists()


def test_promote_validation_and_404(client, layers):
    assert client.post("/api/skills/ghost/promote", json={}).status_code == 404
    r = client.post(
        "/api/skills/rule-writer/promote", json={"target_plugin_id": "bad id!"}
    )
    assert r.status_code == 400
    r = client.post(
        "/api/skills/rule-writer/promote", json={"plugin_id": "not-a-host"}
    )
    assert r.status_code == 404
