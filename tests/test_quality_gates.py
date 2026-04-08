"""Tests for QualityGateEvaluator — automated validation checks"""

import pytest
from api.models.workflow_models import GateOperator, QualityGate
from api.services.quality_gates import QualityGateEvaluator


@pytest.fixture
def evaluator():
    return QualityGateEvaluator()


class TestNotEmpty:
    def test_non_empty_passes(self, evaluator):
        gates = [QualityGate(name="check", field="data", operator=GateOperator.NOT_EMPTY)]
        passed, results = evaluator.evaluate(gates, {"data": "value"})
        assert passed is True

    def test_empty_string_fails(self, evaluator):
        gates = [QualityGate(name="check", field="data", operator=GateOperator.NOT_EMPTY)]
        passed, results = evaluator.evaluate(gates, {"data": ""})
        assert passed is False

    def test_none_fails(self, evaluator):
        gates = [QualityGate(name="check", field="data", operator=GateOperator.NOT_EMPTY)]
        passed, results = evaluator.evaluate(gates, {"data": None})
        assert passed is False

    def test_empty_list_fails(self, evaluator):
        gates = [QualityGate(name="check", field="data", operator=GateOperator.NOT_EMPTY)]
        passed, results = evaluator.evaluate(gates, {"data": []})
        assert passed is False


class TestComparisons:
    def test_equals(self, evaluator):
        gates = [QualityGate(name="eq", field="status", operator=GateOperator.EQUALS, value="ok")]
        passed, _ = evaluator.evaluate(gates, {"status": "ok"})
        assert passed is True

    def test_not_equals(self, evaluator):
        gates = [QualityGate(name="ne", field="status", operator=GateOperator.NOT_EQUALS, value="error")]
        passed, _ = evaluator.evaluate(gates, {"status": "ok"})
        assert passed is True

    def test_gt(self, evaluator):
        gates = [QualityGate(name="gt", field="score", operator=GateOperator.GT, value=5)]
        passed, _ = evaluator.evaluate(gates, {"score": 8})
        assert passed is True
        passed, _ = evaluator.evaluate(gates, {"score": 3})
        assert passed is False

    def test_gte(self, evaluator):
        gates = [QualityGate(name="gte", field="score", operator=GateOperator.GTE, value=5)]
        passed, _ = evaluator.evaluate(gates, {"score": 5})
        assert passed is True

    def test_lt(self, evaluator):
        gates = [QualityGate(name="lt", field="count", operator=GateOperator.LT, value=10)]
        passed, _ = evaluator.evaluate(gates, {"count": 3})
        assert passed is True


class TestContains:
    def test_string_contains(self, evaluator):
        gates = [QualityGate(name="c", field="text", operator=GateOperator.CONTAINS, value="hello")]
        passed, _ = evaluator.evaluate(gates, {"text": "say hello world"})
        assert passed is True

    def test_list_contains(self, evaluator):
        gates = [QualityGate(name="c", field="items", operator=GateOperator.CONTAINS, value="x")]
        passed, _ = evaluator.evaluate(gates, {"items": ["x", "y"]})
        assert passed is True

    def test_not_contains(self, evaluator):
        gates = [QualityGate(name="nc", field="text", operator=GateOperator.NOT_CONTAINS, value="error")]
        passed, _ = evaluator.evaluate(gates, {"text": "all good"})
        assert passed is True


class TestRegex:
    def test_matches(self, evaluator):
        gates = [QualityGate(name="rx", field="text", operator=GateOperator.MATCHES, value=r"\d{3}-\d{4}")]
        passed, _ = evaluator.evaluate(gates, {"text": "call 555-1234"})
        assert passed is True

    def test_no_match(self, evaluator):
        gates = [QualityGate(name="rx", field="text", operator=GateOperator.MATCHES, value=r"^\d+$")]
        passed, _ = evaluator.evaluate(gates, {"text": "not a number"})
        assert passed is False


class TestJsonCheck:
    def test_is_json_string(self, evaluator):
        gates = [QualityGate(name="j", field="data", operator=GateOperator.IS_JSON)]
        passed, _ = evaluator.evaluate(gates, {"data": '{"key": "value"}'})
        assert passed is True

    def test_is_json_dict(self, evaluator):
        gates = [QualityGate(name="j", field="data", operator=GateOperator.IS_JSON)]
        passed, _ = evaluator.evaluate(gates, {"data": {"key": "value"}})
        assert passed is True


class TestLength:
    def test_length_gt(self, evaluator):
        gates = [QualityGate(name="lg", field="items", operator=GateOperator.LENGTH_GT, value=2)]
        passed, _ = evaluator.evaluate(gates, {"items": [1, 2, 3, 4]})
        assert passed is True

    def test_length_lt(self, evaluator):
        gates = [QualityGate(name="ll", field="items", operator=GateOperator.LENGTH_LT, value=5)]
        passed, _ = evaluator.evaluate(gates, {"items": [1, 2]})
        assert passed is True


class TestDictKeys:
    def test_has_key(self, evaluator):
        gates = [QualityGate(name="hk", field="obj", operator=GateOperator.HAS_KEY, value="name")]
        passed, _ = evaluator.evaluate(gates, {"obj": {"name": "test", "age": 5}})
        assert passed is True

    def test_all_keys(self, evaluator):
        gates = [QualityGate(name="ak", field="obj", operator=GateOperator.ALL_KEYS, value=["a", "b"])]
        passed, _ = evaluator.evaluate(gates, {"obj": {"a": 1, "b": 2, "c": 3}})
        assert passed is True

    def test_missing_key(self, evaluator):
        gates = [QualityGate(name="ak", field="obj", operator=GateOperator.ALL_KEYS, value=["a", "z"])]
        passed, _ = evaluator.evaluate(gates, {"obj": {"a": 1}})
        assert passed is False


class TestNestedFields:
    def test_nested_field(self, evaluator):
        gates = [QualityGate(name="n", field="scores.overall", operator=GateOperator.GTE, value=3)]
        passed, _ = evaluator.evaluate(gates, {"scores": {"overall": 4}})
        assert passed is True


class TestSeverity:
    def test_warning_doesnt_fail(self, evaluator):
        gates = [QualityGate(name="w", field="x", operator=GateOperator.NOT_EMPTY, severity="warning")]
        passed, results = evaluator.evaluate(gates, {"x": ""})
        # Warning gates don't cause overall failure
        assert passed is True
        assert results[0]["passed"] is False

    def test_error_fails(self, evaluator):
        gates = [QualityGate(name="e", field="x", operator=GateOperator.NOT_EMPTY, severity="error")]
        passed, _ = evaluator.evaluate(gates, {"x": ""})
        assert passed is False
