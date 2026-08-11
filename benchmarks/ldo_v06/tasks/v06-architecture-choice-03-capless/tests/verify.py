#!/usr/bin/env python3
import json, math, os
from pathlib import Path

app = Path(os.environ.get("EVOLDO_APP", "/app"))
here = Path(__file__).resolve().parent
answer_path = app / "answer.json"
expected_path = here / "expected.json"
reward_path = Path(os.environ.get("EVOLDO_REWARD", "/logs/verifier/reward.json"))
reward_path.parent.mkdir(parents=True, exist_ok=True)
passed = 0
total = 0
details = []
try:
    answer = json.loads(answer_path.read_text())
    expected = json.loads(expected_path.read_text())
    raw_reward = 0.0
    critical_failed = []
    for check in expected["checks"]:
        total += 1
        value = answer
        try:
            for part in check["path"].split("."):
                value = value[part]
            if check["kind"] == "choice_credit":
                credit = float(check["credits"].get(value, 0.0))
                ok = credit == 1.0
            elif check["kind"] == "set_f1":
                actual = set(value) if isinstance(value, list) else set()
                target = set(check["expected"])
                overlap = len(actual & target)
                credit = 2.0 * overlap / (len(actual) + len(target)) if actual else 0.0
                ok = actual == target
            else:
                ok = value == check["expected"]
                credit = float(ok)
        except Exception:
            ok, credit = False, 0.0
        passed += int(ok)
        earned = float(check["weight"]) * credit
        raw_reward += earned
        if check.get("critical", False) and credit < float(check.get("critical_credit_threshold", 1.0)):
            critical_failed.append(check["id"])
        details.append({"id": check["id"], "passed": ok, "credit_fraction": credit, "earned": earned})
    score = min(raw_reward, float(expected.get("critical_failure_cap", 49.0))) if critical_failed else raw_reward
    reward = score / 100.0
except Exception as exc:
    reward, details = 0.0, [{"error": str(exc)}]
reward_path.write_text(json.dumps({"reward": reward, "tests_total": total, "tests_passed": passed, "details": details}) + "\n")
