"""Tests for the code_exec chat plugin tool."""


def test_code_exec_handler_runs(monkeypatch, tmp_path):
    monkeypatch.setenv("CODE_EXEC_ENABLED", "true")
    from api.services.sandbox_registry import SandboxRegistry, _set_current
    from api.services.sandbox_impl.subprocess import SubprocessSandbox
    from api.services.sandbox_fs import SandboxedFS

    reg = SandboxRegistry()
    reg.register(SubprocessSandbox())
    _set_current(reg)

    import importlib.util, pathlib

    spec = importlib.util.spec_from_file_location(
        "code_exec_tool", pathlib.Path("plugins/code-exec/tool.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    result = mod.code_exec(code="print(6*7)", __sandbox=SandboxedFS(str(tmp_path)))
    assert result["exit_code"] == 0 and "42" in result["stdout"]


def test_code_exec_disabled_by_default(monkeypatch, tmp_path):
    monkeypatch.delenv("CODE_EXEC_ENABLED", raising=False)
    from api.services.sandbox_fs import SandboxedFS
    import importlib.util, pathlib

    spec = importlib.util.spec_from_file_location(
        "code_exec_tool2", pathlib.Path("plugins/code-exec/tool.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    out = mod.code_exec(code="print(1)", __sandbox=SandboxedFS(str(tmp_path)))
    assert "disabled" in out.get("error", "").lower()
