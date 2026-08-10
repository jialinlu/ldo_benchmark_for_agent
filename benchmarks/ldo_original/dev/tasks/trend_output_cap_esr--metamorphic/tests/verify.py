#!/usr/bin/env python3
"""Self-contained public-development verifier for one structured reasoning task."""
import json
import os
from pathlib import Path

ANSWER = Path(os.environ.get("EVOLDO_ANSWER_PATH", "/app/answer.json"))
EXPECTED = Path(os.environ.get("EVOLDO_EXPECTED_PATH", "/app/evoldo_tests/expected.json"))
OUTPUT = Path(os.environ.get("EVOLDO_VERIFIER_OUTPUT", "/logs/verifier"))
REQUIRED = {
    "schema_version", "task_id", "conclusion", "analysis_regime", "held_fixed",
    "evidence_facts", "mechanism_tags", "recommended_actions", "mechanism",
    "claim_boundary", "confidence",
}


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    try:
        answer = json.loads(ANSWER.read_text())
        oracle = json.loads(EXPECTED.read_text())
        if not isinstance(answer, dict) or not REQUIRED.issubset(answer):
            raise ValueError("answer contract is incomplete")
        if not isinstance(answer["mechanism"], str) or not answer["mechanism"].strip():
            raise ValueError("mechanism is empty")
        if not isinstance(answer["claim_boundary"], str) or not answer["claim_boundary"].strip():
            raise ValueError("claim_boundary is empty")
        if not isinstance(answer["confidence"], (int, float)) or isinstance(answer["confidence"], bool) or not 0 <= answer["confidence"] <= 1:
            raise ValueError("confidence is outside [0, 1]")
    except Exception as exc:
        write(0.0, [], "invalid_answer: %s" % exc)
        return

    raw = 0.0
    critical = []
    results = []
    for check in oracle["checks"]:
        actual = answer.get(check["path"])
        kind = check["kind"]
        expected = check.get("expected")
        if kind == "exact":
            passed = actual == expected
        elif kind == "set_equals":
            passed = isinstance(actual, list) and set(actual) == set(expected) and len(actual) == len(set(actual))
        elif kind == "set_excludes":
            passed = isinstance(actual, list) and not set(actual).intersection(expected)
        else:
            passed = False
        if passed:
            raw += float(check["weight"])
        elif check.get("critical", False):
            critical.append(check["id"])
        results.append({"name": check["id"], "status": "passed" if passed else "failed"})
    score = min(raw, float(oracle.get("critical_failure_cap", 49.0))) if critical else raw
    write(score / 100.0, results, "ok", score=score, critical=critical)


def write(reward: float, results: list, outcome: str, score: float = 0.0, critical: list | None = None) -> None:
    passed = sum(result.get("status") == "passed" for result in results)
    total = len(results) or 8
    payload = {
        "reward": reward, "tests_total": total, "tests_passed": passed,
        "partial": reward, "score": score, "outcome": outcome,
        "critical_failed": critical or [],
    }
    (OUTPUT / "reward.json").write_text(json.dumps(payload) + "\n")
    (OUTPUT / "new-ctrf.json").write_text(json.dumps({
        "results": {"summary": {"tests": total, "passed": passed, "failed": total - passed}, "tests": results}
    }, indent=2) + "\n")


if __name__ == "__main__":
    main()
