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
