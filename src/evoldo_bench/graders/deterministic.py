from __future__ import annotations

import math
from typing import Any, Dict, List, Tuple

from ..contracts import Task, validate_answer_for_grading, validate_oracle
from ..errors import ContractError
from ..utils import dotted_get, utc_timestamp


def _as_set(value: Any, check_id: str) -> set:
    if not isinstance(value, list):
        raise ContractError("check %s expected an answer list" % check_id)
    try:
        values = set(value)
    except TypeError:
        raise ContractError("check %s answer list contains non-scalar values" % check_id)
    if len(values) != len(value):
        raise ContractError("check %s answer list contains duplicates" % check_id)
    return values


def _lcs_length(left: List[Any], right: List[Any]) -> int:
    previous = [0] * (len(right) + 1)
    for left_item in left:
        current = [0]
        for index, right_item in enumerate(right, start=1):
            current.append(
                previous[index - 1] + 1
                if left_item == right_item
                else max(previous[index], current[index - 1])
            )
        previous = current
    return previous[-1]


def _evaluate(check: Dict[str, Any], answer: Dict[str, Any]) -> Tuple[bool, str, Any, float]:
    check_id = check["id"]
    try:
        actual = dotted_get(answer, check["path"])
    except (KeyError, IndexError, ValueError):
        return False, "missing answer path", None, 0.0
    kind = check["kind"]
    expected = check.get("expected")
    if kind == "exact":
        passed = actual == expected
        return passed, "exact match" if passed else "expected %r" % expected, actual, float(passed)
    if kind == "choice_credit":
        credit = float(check["credits"].get(actual, 0.0)) if isinstance(actual, str) else 0.0
        passed = credit == 1.0
        return passed, "full-credit choice" if passed else "choice credit %.3f" % credit, actual, credit
    if kind == "ranking_pairwise":
        if not isinstance(actual, list):
            return False, "ranking must be a list", actual, 0.0
        expected_rank = list(expected)
        actual_rank = {value: index for index, value in enumerate(actual)}
        correct_pairs = 0
        total_pairs = 0
        for left_index, left in enumerate(expected_rank):
            for right in expected_rank[left_index + 1:]:
                total_pairs += 1
                if left in actual_rank and right in actual_rank and actual_rank[left] < actual_rank[right]:
                    correct_pairs += 1
        credit = correct_pairs / total_pairs if total_pairs else 0.0
        passed = actual == expected_rank
        return passed, "exact ranking" if passed else "pairwise ranking credit %.3f" % credit, actual, credit
    if kind == "sequence_alignment":
        if not isinstance(actual, list):
            return False, "sequence must be a list", actual, 0.0
        expected_sequence = list(expected)
        if len(actual) != len(set(actual)):
            return False, "sequence contains duplicate items", actual, 0.0
        overlap = _lcs_length(actual, expected_sequence)
        precision = overlap / len(actual) if actual else 0.0
        recall = overlap / len(expected_sequence) if expected_sequence else 0.0
        credit = 2.0 * precision * recall / (precision + recall) if precision + recall else 0.0
        passed = actual == expected_sequence
        return passed, "exact sequence" if passed else "sequence alignment credit %.3f" % credit, actual, credit
    if kind == "boolean":
        passed = isinstance(actual, bool) and actual is bool(expected)
        return passed, "boolean match" if passed else "expected %r" % expected, actual, float(passed)
    if kind == "set_contains":
        actual_set = _as_set(actual, check_id)
        expected_set = set(expected)
        missing = sorted(expected_set - actual_set)
        passed = not missing
        return passed, "contains required values" if passed else "missing %r" % missing, actual, float(passed)
    if kind == "set_equals":
        actual_set = _as_set(actual, check_id)
        expected_set = set(expected)
        missing = sorted(expected_set - actual_set)
        unexpected = sorted(actual_set - expected_set)
        passed = not missing and not unexpected
        if passed:
            return True, "exact set match", actual, 1.0
        return False, "missing %r; unexpected %r" % (missing, unexpected), actual, 0.0
    if kind == "set_f1":
        actual_set = _as_set(actual, check_id)
        expected_set = set(expected)
        if not actual_set:
            return False, "empty selection", actual, 0.0
        overlap = len(actual_set.intersection(expected_set))
        credit = 2.0 * overlap / (len(actual_set) + len(expected_set))
        passed = actual_set == expected_set
        return passed, "exact evidence set" if passed else "set F1 credit %.3f" % credit, actual, credit
    if kind == "set_excludes":
        actual_set = _as_set(actual, check_id)
        forbidden = sorted(actual_set.intersection(set(expected)))
        passed = not forbidden
        return passed, "excludes forbidden values" if passed else "contains forbidden %r" % forbidden, actual, float(passed)
    if kind == "nonempty":
        passed = isinstance(actual, (str, list, dict)) and len(actual) > 0
        return passed, "non-empty" if passed else "value is empty", actual, float(passed)
    if kind == "numeric_close":
        if not isinstance(actual, (int, float)) or isinstance(actual, bool):
            return False, "answer value is not numeric", actual, 0.0
        absolute = float(check.get("absolute_tolerance", 0.0))
        relative = float(check.get("relative_tolerance", 0.0))
        passed = math.isclose(float(actual), float(expected), rel_tol=relative, abs_tol=absolute)
        return passed, "within tolerance" if passed else "expected %r within tolerance" % expected, actual, float(passed)
    if kind == "numeric_score":
        if not isinstance(actual, (int, float)) or isinstance(actual, bool):
            return False, "answer value is not numeric", actual, 0.0
        distance = abs(float(actual) - float(expected))
        full = float(check["full_tolerance"])
        zero = float(check["zero_tolerance"])
        credit = 1.0 if distance <= full else max(0.0, (zero - distance) / (zero - full))
        return credit == 1.0, "full numeric credit" if credit == 1.0 else "numeric credit %.3f" % credit, actual, credit
    if kind == "numeric_range":
        if not isinstance(actual, (int, float)) or isinstance(actual, bool):
            return False, "answer value is not numeric", actual, 0.0
        value = float(actual)
        minimum = float(check["minimum"])
        maximum = float(check["maximum"])
        partial_minimum = float(check.get("partial_minimum", minimum))
        partial_maximum = float(check.get("partial_maximum", maximum))
        if minimum <= value <= maximum:
            return True, "inside full-credit range", actual, 1.0
        if partial_minimum <= value < minimum and minimum > partial_minimum:
            credit = (value - partial_minimum) / (minimum - partial_minimum)
        elif maximum < value <= partial_maximum and partial_maximum > maximum:
            credit = (partial_maximum - value) / (partial_maximum - maximum)
        else:
            credit = 0.0
        return False, "range credit %.3f" % credit, actual, credit
    if kind == "mapping_credit":
        if not isinstance(actual, dict):
            return False, "mapping must be an object", actual, 0.0
        expected_mapping = dict(expected)
        expected_keys = set(expected_mapping)
        if not expected_keys:
            return False, "empty mapping", actual, 0.0
        matches = sum(
            key in actual and actual[key] == expected_mapping[key] for key in expected_keys
        )
        credit = matches / len(expected_keys)
        passed = actual == expected_mapping
        return passed, "exact mapping" if passed else "mapping credit %.3f" % credit, actual, credit
    if kind == "multilabel_mapping_credit":
        if not isinstance(actual, dict):
            return False, "multilabel mapping must be an object", actual, 0.0
        expected_mapping = dict(expected)
        keys = set(expected_mapping)
        if not keys:
            return False, "empty multilabel mapping", actual, 0.0
        credits = []
        for key in keys:
            actual_values = actual.get(key, [])
            expected_values = expected_mapping.get(key, [])
            if not isinstance(actual_values, list):
                credits.append(0.0)
                continue
            try:
                actual_set = set(actual_values)
            except TypeError:
                credits.append(0.0)
                continue
            if len(actual_set) != len(actual_values):
                credits.append(0.0)
                continue
            expected_set = set(expected_values)
            if not actual_set and not expected_set:
                credits.append(1.0)
                continue
            overlap = len(actual_set.intersection(expected_set))
            credits.append(2.0 * overlap / (len(actual_set) + len(expected_set)))
        credit = sum(credits) / len(credits)
        passed = actual == expected_mapping
        return (
            passed,
            "exact multilabel mapping" if passed else "multilabel mapping credit %.3f" % credit,
            actual,
            credit,
        )
    raise ContractError("unsupported check kind: %s" % kind)


def grade_answer(task: Task, answer: Dict[str, Any], oracle: Dict[str, Any]) -> Dict[str, Any]:
    validate_answer_for_grading(answer, task)
    validate_oracle(oracle)
    if answer["task_id"] != task.task_id:
        raise ContractError("answer task_id does not match task")
    if oracle["task_id"] != task.task_id or oracle["family_id"] != task.family_id:
        raise ContractError("oracle identity does not match task")
    checks: List[Dict[str, Any]] = []
    raw_score = 0.0
    critical_failed = []
    for check in oracle["checks"]:
        try:
            passed, message, actual, credit = _evaluate(check, answer)
        except (ContractError, TypeError, ValueError, OverflowError):
            try:
                actual = dotted_get(answer, check["path"])
            except (KeyError, IndexError, TypeError, ValueError):
                actual = None
            passed, message, credit = False, "invalid value for atomic check", 0.0
        earned = float(check["weight"]) * credit
        raw_score += earned
        critical_threshold = float(check.get("critical_credit_threshold", 1.0))
        if check.get("critical", False) and credit < critical_threshold:
            critical_failed.append(check["id"])
        checks.append(
            {
                "id": check["id"],
                "dimension": check.get("dimension", check["id"]),
                "path": check["path"],
                "kind": check["kind"],
                "weight": float(check["weight"]),
                "earned": earned,
                "credit_fraction": credit,
                "passed": passed,
                "message": message,
                "actual": actual,
                "critical": bool(check.get("critical", False)),
            }
        )
    cap = float(oracle.get("critical_failure_cap", 49.0))
    final_score = min(raw_score, cap) if critical_failed else raw_score
    return {
        "schema_version": "1.0",
        "task_id": task.task_id,
        "family_id": task.family_id,
        "lineage_id": task.data["lineage_id"],
        "suite": task.suite,
        "level": task.data["level"],
        "variant": task.variant,
        "evaluation_role": task.data.get("evaluation_role", "legacy"),
        "deployment_tier": task.data.get("deployment_tier", "legacy"),
        "split": task.split,
        "score": round(final_score, 6),
        "raw_score": round(raw_score, 6),
        "max_score": 100.0,
        "passed": final_score >= float(oracle.get("pass_threshold", 70.0)),
        "critical_failed": critical_failed,
        "checks": checks,
        "explanation_judge": "not_run",
        "graded_at": utc_timestamp(),
    }
