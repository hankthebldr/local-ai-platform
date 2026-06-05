from api.services.sandbox import (
    SandboxKind,
    SandboxCapabilities,
    CodeExecSpec,
    CodeExecResult,
    SandboxBackend,
)


def test_capabilities_and_specs_construct():
    caps = SandboxCapabilities(
        name="subprocess",
        isolation_tier=1,
        network_modes=("none",),
        max_mem_mb=2048,
        languages=("python",),
        can_auto_run=False,
    )
    assert caps.isolation_tier == 1 and caps.can_auto_run is False

    spec = CodeExecSpec(language="python", code="print(1)", scratch_path="/tmp/x")
    assert spec.timeout_s == 60 and spec.network == "none"

    res = CodeExecResult(exit_code=0, stdout="1\n", stderr="", tier_used=1)
    assert res.exit_code == 0 and res.files_produced == []


def test_backend_protocol_is_runtime_checkable():
    class Dummy:
        name = "dummy"

        def capabilities(self):
            ...

        def execute(self, spec):
            ...

    assert isinstance(Dummy(), SandboxBackend)
