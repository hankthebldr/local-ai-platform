import os
from api.services.sandbox_fs import SandboxedFS
from api.services.engine_executors import code_promote as cp
from api.models.workflow_models import CodeStepConfig


def test_promote_auto_on_green_copies_files_out(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    canon = SandboxedFS("data/sandboxes/wf-r1/_workspace")
    scratch = SandboxedFS("data/sandboxes/wf-r1/c1")
    scratch.write("out.txt", "promoted-content")
    cfg = CodeStepConfig(code="x", files_out=["out.txt"], promote="auto_on_green")
    promoted = cp.promote(scratch, canon, cfg, exit_code=0)
    assert promoted == ["out.txt"] and canon.read("out.txt") == "promoted-content"


def test_promote_never_keeps_canon_empty(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    canon = SandboxedFS("data/sandboxes/wf-r2/_workspace")
    scratch = SandboxedFS("data/sandboxes/wf-r2/c1")
    scratch.write("out.txt", "x")
    cfg = CodeStepConfig(code="x", files_out=["out.txt"], promote="never")
    assert cp.promote(scratch, canon, cfg, exit_code=0) == []
    assert not canon.exists("out.txt")


def test_promote_auto_on_green_skips_on_failure(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    canon = SandboxedFS("data/sandboxes/wf-r3/_workspace")
    scratch = SandboxedFS("data/sandboxes/wf-r3/c1")
    scratch.write("out.txt", "x")
    cfg = CodeStepConfig(code="x", files_out=["out.txt"], promote="auto_on_green")
    assert cp.promote(scratch, canon, cfg, exit_code=1) == []


def test_promote_skips_traversal_files_out(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    canon = SandboxedFS("data/sandboxes/wf-r4/_workspace")
    scratch = SandboxedFS("data/sandboxes/wf-r4/c1")
    cfg = CodeStepConfig(code="x", files_out=["../escape.txt"], promote="auto_on_green")
    # traversal path fails re-validation -> skipped, nothing promoted
    assert cp.promote(scratch, canon, cfg, exit_code=0) == []
