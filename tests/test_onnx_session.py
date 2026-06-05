import pytest

# onnxruntime is an optional substrate (setup/requirements-onnx.txt); CI installs
# only core+dev, so skip rather than error at collection when it's absent.
pytest.importorskip("onnxruntime")

import api.services.onnx.session as sess_mod  # noqa: E402
from api.services.architecture import ArchClass  # noqa: E402
from api.services.arch_impl.nvidia_single import NvidiaSingleArchitecture  # noqa: E402
from api.services.arch_impl.unified import UnifiedArchitecture  # noqa: E402


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


def _nvidia():
    # A real arch whose ONNX plan requests a non-CPU EP (CUDA), to exercise the
    # EP-availability degrade path. apple_unified/cpu_x86 are CPU-only in Phase 1.
    return NvidiaSingleArchitecture(
        gpu_meta={"name": "RTX PRO 4000", "vram_total_gb": 24.0}, driver_version="575"
    )


def test_build_session_cpu_x86_runs_on_cpu(monkeypatch):
    monkeypatch.setattr(sess_mod, "ort", _FakeOrt)
    cpu_arch = UnifiedArchitecture(
        arch_class=ArchClass.CPU_X86, total_memory_gb=96.0, bandwidth_gbps=89.0
    )
    session, active = sess_mod.build_session("/fake/model.onnx", arch=cpu_arch)
    assert active == ["CPUExecutionProvider"]


def test_build_session_degrades_when_accelerator_unavailable(monkeypatch, caplog):
    # The nvidia plan requests [CUDA, CPU]; FakeOrt only has CPU -> CUDA is
    # dropped, build_session degrades to CPU and logs which EP was unavailable.
    import logging

    # The project logger has propagate=False; enable propagation so caplog
    # (which intercepts the root logger) can capture the warning.
    monkeypatch.setattr(sess_mod.logger, "propagate", True)
    caplog.set_level(logging.WARNING)
    monkeypatch.setattr(sess_mod, "ort", _FakeOrt)
    session, active = sess_mod.build_session("/fake/model.onnx", arch=_nvidia())
    assert active == ["CPUExecutionProvider"]
    assert any("CUDAExecutionProvider" in r.message for r in caplog.records)
