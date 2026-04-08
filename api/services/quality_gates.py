"""
Quality Gates — Automated validation checks between workflow steps

Evaluates gate conditions against step outputs to ensure data quality
before downstream steps consume the results. Supports comparison operators,
regex matching, JSON structure validation, and length checks.
"""

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from ..logging_config import logger
from ..models.workflow_models import GateOperator, QualityGate


class QualityGateEvaluator:
    """
    Evaluates quality gates against step outputs.

    Each gate produces a pass/fail result with a reason.
    Gates with severity="error" cause step failure.
    Gates with severity="warning" log but continue.
    """

    def evaluate(
        self,
        gates: List[QualityGate],
        outputs: Dict[str, Any],
    ) -> Tuple[bool, List[Dict[str, Any]]]:
        """
        Evaluate all quality gates against the given outputs.

        Returns:
            (all_passed, results) where results is a list of gate evaluation dicts
        """
        results: List[Dict[str, Any]] = []
        all_passed = True

        for gate in gates:
            value = self._resolve_field(gate.field, outputs)
            passed, reason = self._evaluate_gate(gate, value)

            result = {
                "gate": gate.name,
                "field": gate.field,
                "operator": gate.operator.value,
                "expected": gate.value,
                "actual_type": type(value).__name__ if value is not None else "null",
                "passed": passed,
                "severity": gate.severity,
                "reason": reason,
            }
            results.append(result)

            if not passed:
                if gate.severity == "error":
                    all_passed = False
                    logger.error(
                        f"Quality gate FAILED: {gate.name} — {reason}"
                    )
                else:
                    logger.warning(
                        f"Quality gate WARNING: {gate.name} — {reason}"
                    )
            else:
                logger.debug(f"Quality gate passed: {gate.name}")

        return all_passed, results

    def _resolve_field(self, field: str, outputs: Dict[str, Any]) -> Any:
        """Resolve a dotted field path against the outputs dict"""
        parts = field.split(".")
        value: Any = outputs
        for part in parts:
            if isinstance(value, dict):
                value = value.get(part)
            elif isinstance(value, (list, tuple)):
                try:
                    value = value[int(part)]
                except (ValueError, IndexError):
                    return None
            else:
                return None
        return value

    def _evaluate_gate(
        self,
        gate: QualityGate,
        value: Any,
    ) -> Tuple[bool, str]:
        """Evaluate a single gate condition"""
        op = gate.operator
        expected = gate.value
        msg = gate.message or ""

        try:
            if op == GateOperator.NOT_EMPTY:
                if value is None or value == "" or value == [] or value == {}:
                    return False, msg or f"Field '{gate.field}' is empty"
                return True, "not empty"

            if op == GateOperator.EQUALS:
                passed = value == expected
                return passed, msg or (f"Expected {expected}, got {value}" if not passed else "equal")

            if op == GateOperator.NOT_EQUALS:
                passed = value != expected
                return passed, msg or (f"Expected not {expected}, got {value}" if not passed else "not equal")

            if op == GateOperator.CONTAINS:
                if isinstance(value, str):
                    passed = str(expected) in value
                elif isinstance(value, (list, tuple)):
                    passed = expected in value
                elif isinstance(value, dict):
                    passed = expected in value
                else:
                    passed = False
                return passed, msg or (f"'{gate.field}' does not contain '{expected}'" if not passed else "contains")

            if op == GateOperator.NOT_CONTAINS:
                if isinstance(value, str):
                    passed = str(expected) not in value
                elif isinstance(value, (list, tuple)):
                    passed = expected not in value
                else:
                    passed = True
                return passed, msg or (f"'{gate.field}' contains '{expected}'" if not passed else "not contains")

            if op == GateOperator.GT:
                passed = float(value) > float(expected)
                return passed, msg or (f"{value} not > {expected}" if not passed else f"{value} > {expected}")

            if op == GateOperator.LT:
                passed = float(value) < float(expected)
                return passed, msg or (f"{value} not < {expected}" if not passed else f"{value} < {expected}")

            if op == GateOperator.GTE:
                passed = float(value) >= float(expected)
                return passed, msg or (f"{value} not >= {expected}" if not passed else f"{value} >= {expected}")

            if op == GateOperator.LTE:
                passed = float(value) <= float(expected)
                return passed, msg or (f"{value} not <= {expected}" if not passed else f"{value} <= {expected}")

            if op == GateOperator.MATCHES:
                if not isinstance(value, str):
                    return False, msg or f"Cannot regex match non-string: {type(value).__name__}"
                passed = bool(re.search(str(expected), value))
                return passed, msg or (f"No regex match for '{expected}'" if not passed else "matches")

            if op == GateOperator.IS_JSON:
                try:
                    if isinstance(value, str):
                        json.loads(value)
                    elif isinstance(value, (dict, list)):
                        pass  # Already structured
                    else:
                        return False, msg or f"Not valid JSON: {type(value).__name__}"
                    return True, "valid JSON"
                except (json.JSONDecodeError, TypeError):
                    return False, msg or "Not valid JSON"

            if op == GateOperator.LENGTH_GT:
                length = len(value) if hasattr(value, "__len__") else 0
                passed = length > int(expected)
                return passed, msg or (f"Length {length} not > {expected}" if not passed else f"length {length}")

            if op == GateOperator.LENGTH_LT:
                length = len(value) if hasattr(value, "__len__") else 0
                passed = length < int(expected)
                return passed, msg or (f"Length {length} not < {expected}" if not passed else f"length {length}")

            if op == GateOperator.HAS_KEY:
                if not isinstance(value, dict):
                    return False, msg or f"Not a dict: {type(value).__name__}"
                passed = str(expected) in value
                return passed, msg or (f"Missing key '{expected}'" if not passed else f"has key '{expected}'")

            if op == GateOperator.ALL_KEYS:
                if not isinstance(value, dict):
                    return False, msg or f"Not a dict: {type(value).__name__}"
                required_keys = expected if isinstance(expected, list) else [expected]
                missing = [k for k in required_keys if k not in value]
                passed = len(missing) == 0
                return passed, msg or (f"Missing keys: {missing}" if not passed else "all keys present")

            return False, f"Unknown operator: {op}"

        except Exception as e:
            return False, msg or f"Gate evaluation error: {e}"
