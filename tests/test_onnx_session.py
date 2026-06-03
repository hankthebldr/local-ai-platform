import api.services.onnx.session as sess_mod
from api.services.architecture import ArchClass
from api.services.arch_impl.unified import UnifiedArchitecture


class _FakeSession:
    """Mimics ORT: silently drops providers not in `available`."""

    available = {"CPUExecutionProvider"}

    def __init__(self, path, providers=None, provider_options=None):
        self.path = path
        self._providers = [p for p in (providers or []) if p in self.available]

    def get_providers(self):
        return self._providers or ["CPUExecutionProvider"]


class _FakeOrt:
    InferenceSession = _FakeSession


def _apple():
    return UnifiedArchitecture(
        arch_class=ArchClass.APPLE_UNIFIED, total_memory_gb=48.0, bandwidth_gbps=273.0
    )


def test_build_session_cpu_x86_runs_on_cpu(monkeypatch):
    monkeypatch.setattr(sess_mod, "ort", _FakeOrt)
    cpu_arch = UnifiedArchitecture(
        arch_class=ArchClass.CPU_X86, total_memory_gb=96.0, bandwidth_gbps=89.0
    )
    session, active = sess_mod.build_session("/fake/model.onnx", arch=cpu_arch)
    assert active == ["CPUExecutionProvider"]


def test_build_session_degrades_when_accelerator_unavailable(monkeypatch, caplog):
    # apple plan requests [CoreML, CPU]; FakeOrt only has CPU -> falls back, warns.
    import logging

    # The project logger has propagate=False; enable propagation so caplog
    # (which intercepts the root logger) can capture the warning.
    monkeypatch.setattr(sess_mod.logger, "propagate", True)
    caplog.set_level(logging.WARNING)
    monkeypatch.setattr(sess_mod, "ort", _FakeOrt)
    session, active = sess_mod.build_session("/fake/model.onnx", arch=_apple())
    assert active == ["CPUExecutionProvider"]
    assert any("CoreMLExecutionProvider" in r.message for r in caplog.records)
