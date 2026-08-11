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
    for check in expected["checks"]:
        total += 1
        value = answer
        try:
            for part in check["path"].split("."):
                value = value[part]
            ok = value == check["expected"]
        except Exception:
            ok = False
        passed += int(ok)
        details.append({"id": check["id"], "passed": ok})
    reward = sum(check["weight"] for check, detail in zip(expected["checks"], details) if detail["passed"]) / 100.0
except Exception as exc:
    reward, details = 0.0, [{"error": str(exc)}]
reward_path.write_text(json.dumps({"reward": reward, "tests_total": total, "tests_passed": passed, "details": details}) + "\n")
