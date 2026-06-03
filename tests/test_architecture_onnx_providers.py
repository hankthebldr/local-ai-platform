import pytest
from pydantic import ValidationError

from api.services.architecture import ArchClass, OnnxExecutionPlan, UnknownArchitecture
from api.services.arch_impl.nvidia_multi import NvidiaMultiArchitecture
from api.services.arch_impl.nvidia_single import NvidiaSingleArchitecture
from api.services.arch_impl.unified import UnifiedArchitecture


def test_onnx_execution_plan_shape():
    plan = OnnxExecutionPlan(
        providers=["CPUExecutionProvider"], quant="int8", provider_options=[{}]
    )
    assert plan.providers == ["CPUExecutionProvider"]
    assert plan.quant == "int8"
    assert plan.provider_options == [{}]


def test_unknown_arch_recommends_cpu_int8():
    plan = UnknownArchitecture().recommended_onnx_providers()
    assert plan.providers == ["CPUExecutionProvider"]
    assert plan.quant == "int8"


def _unified(arch_class):
    return UnifiedArchitecture(
        arch_class=arch_class, total_memory_gb=48.0, bandwidth_gbps=273.0
    )


def test_apple_unified_recommends_coreml_fp16():
    plan = _unified(ArchClass.APPLE_UNIFIED).recommended_onnx_providers()
    assert plan.providers == ["CoreMLExecutionProvider", "CPUExecutionProvider"]
    assert plan.quant == "fp16"
    assert len(plan.provider_options) == len(plan.providers)


def test_cpu_x86_recommends_cpu_int8_amd_first():
    # "AMD-first": int8/CPU is the AMD-optimal default; Intel OpenVINO is deferred.
    plan = _unified(ArchClass.CPU_X86).recommended_onnx_providers()
    assert plan.providers == ["CPUExecutionProvider"]
    assert plan.quant == "int8"


_FAKE_GPU = {"name": "RTX PRO 4000", "vram_total_gb": 24.0}


def test_nvidia_single_recommends_cuda_fp16(monkeypatch):
    monkeypatch.setattr(
        "api.services.arch_impl._nvml.estimate_bandwidth_gbps", lambda n: 600.0
    )
    arch = NvidiaSingleArchitecture(gpu_meta=_FAKE_GPU, driver_version="575")
    plan = arch.recommended_onnx_providers()
    assert plan.providers == ["CUDAExecutionProvider", "CPUExecutionProvider"]
    assert plan.quant == "fp16"


def test_nvidia_multi_recommends_cuda_fp16(monkeypatch):
    monkeypatch.setattr(
        "api.services.arch_impl._nvml.estimate_bandwidth_gbps", lambda n: 600.0
    )
    arch = NvidiaMultiArchitecture(
        gpus=[_FAKE_GPU, _FAKE_GPU], nvlink_topology=[], driver_version="575"
    )
    plan = arch.recommended_onnx_providers()
    assert plan.providers == ["CUDAExecutionProvider", "CPUExecutionProvider"]
    assert plan.quant == "fp16"


def test_onnx_execution_plan_rejects_missing_cpu_floor():
    with pytest.raises(ValidationError):
        OnnxExecutionPlan(
            providers=["CUDAExecutionProvider"], quant="fp16", provider_options=[{}]
        )


def test_onnx_execution_plan_rejects_mismatched_options():
    with pytest.raises(ValidationError):
        OnnxExecutionPlan(
            providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
            quant="fp16",
            provider_options=[{}],
        )


def test_onnx_execution_plan_rejects_empty_providers():
    with pytest.raises(ValidationError):
        OnnxExecutionPlan(providers=[], quant="int8", provider_options=[])
