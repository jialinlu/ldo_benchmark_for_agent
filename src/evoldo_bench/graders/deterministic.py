from __future__ import annotations

import math
from typing import Any, Dict, List, Tuple

from ..contracts import Task, validate_answer, validate_oracle
from ..errors import ContractError
from ..utils import dotted_get, utc_timestamp


def _as_set(value: Any, check_id: str) -> set:
    if not isinstance(value, list):
        raise ContractError("check %s expected an answer list" % check_id)
    return set(value)


def _evaluate(check: Dict[str, Any], answer: Dict[str, Any]) -> Tuple[bool, str, Any]:
    check_id = check["id"]
    try:
        actual = dotted_get(answer, check["path"])
    except (KeyError, IndexError, ValueError):
        return False, "missing answer path", None
    kind = check["kind"]
    expected = check.get("expected")
    if kind == "exact":
        passed = actual == expected
        return passed, "exact match" if passed else "expected %r" % expected, actual
    if kind == "boolean":
        passed = isinstance(actual, bool) and actual is bool(expected)
        return passed, "boolean match" if passed else "expected %r" % expected, actual
    if kind == "set_contains":
        actual_set = _as_set(actual, check_id)
        expected_set = set(expected)
        missing = sorted(expected_set - actual_set)
        return not missing, "contains required values" if not missing else "missing %r" % missing, actual
    if kind == "set_equals":
        actual_set = _as_set(actual, check_id)
        expected_set = set(expected)
        missing = sorted(expected_set - actual_set)
        unexpected = sorted(actual_set - expected_set)
        passed = not missing and not unexpected
        if passed:
            return True, "exact set match", actual
        return False, "missing %r; unexpected %r" % (missing, unexpected), actual
    if kind == "set_excludes":
        actual_set = _as_set(actual, check_id)
        forbidden = sorted(actual_set.intersection(set(expected)))
        return not forbidden, "excludes forbidden values" if not forbidden else "contains forbidden %r" % forbidden, actual
    if kind == "nonempty":
        passed = isinstance(actual, (str, list, dict)) and len(actual) > 0
        return passed, "non-empty" if passed else "value is empty", actual
    if kind == "numeric_close":
        if not isinstance(actual, (int, float)) or isinstance(actual, bool):
            return False, "answer value is not numeric", actual
        absolute = float(check.get("absolute_tolerance", 0.0))
        relative = float(check.get("relative_tolerance", 0.0))
        passed = math.isclose(float(actual), float(expected), rel_tol=relative, abs_tol=absolute)
        return passed, "within tolerance" if passed else "expected %r within tolerance" % expected, actual
    raise ContractError("unsupported check kind: %s" % kind)


def grade_answer(task: Task, answer: Dict[str, Any], oracle: Dict[str, Any]) -> Dict[str, Any]:
    validate_answer(answer, task)
    validate_oracle(oracle)
    if answer["task_id"] != task.task_id:
        raise ContractError("answer task_id does not match task")
    if oracle["task_id"] != task.task_id or oracle["family_id"] != task.family_id:
        raise ContractError("oracle identity does not match task")
    checks: List[Dict[str, Any]] = []
    raw_score = 0.0
    critical_failed = []
    for check in oracle["checks"]:
        passed, message, actual = _evaluate(check, answer)
        earned = float(check["weight"]) if passed else 0.0
        raw_score += earned
        if check.get("critical", False) and not passed:
            critical_failed.append(check["id"])
        checks.append(
            {
                "id": check["id"],
                "path": check["path"],
                "kind": check["kind"],
                "weight": float(check["weight"]),
                "earned": earned,
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
