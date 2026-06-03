from api.services.architecture import (
    OnnxExecutionPlan,
    UnknownArchitecture,
)


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
    assert plan.providers[-1] == "CPUExecutionProvider"


from api.services.architecture import ArchClass
from api.services.arch_impl.unified import UnifiedArchitecture


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
    plan = _unified(ArchClass.CPU_X86).recommended_onnx_providers()
    assert plan.providers == ["CPUExecutionProvider"]
    assert plan.quant == "int8"
