#!/usr/bin/env python3
import json, math, os
from pathlib import Path

app = Path(os.environ.get("EVOLDO_APP", "/app"))
here = Path(__file__).resolve().parent
reward_path = Path(os.environ.get("EVOLDO_REWARD", "/logs/verifier/reward.json"))
reward_path.parent.mkdir(parents=True, exist_ok=True)

def get(value, path):
    for part in path.split("."):
        value = value[part]
    return value

def lcs(left, right):
    previous = [0] * (len(right) + 1)
    for a in left:
        current = [0]
        for index, b in enumerate(right, 1):
            current.append(previous[index - 1] + 1 if a == b else max(previous[index], current[-1]))
        previous = current
    return previous[-1]

def evaluate(check, value):
    kind = check["kind"]
    expected = check.get("expected")
    if kind == "exact": return float(value == expected)
    if kind == "choice_credit": return float(check["credits"].get(value, 0.0))
    if kind == "set_f1":
        actual, target = set(value), set(expected)
        overlap = len(actual & target)
        return 2.0 * overlap / (len(actual) + len(target)) if actual or target else 1.0
    if kind == "sequence_alignment":
        if len(value) != len(set(value)): return 0.0
        overlap = lcs(value, expected)
        p = overlap / len(value) if value else 0.0
        r = overlap / len(expected) if expected else 0.0
        return 2.0 * p * r / (p + r) if p + r else 0.0
    if kind == "mapping_credit":
        keys = set(expected)
        return sum(key in value and key in expected and value[key] == expected[key] for key in keys) / len(keys)
    if kind == "multilabel_mapping_credit":
        keys = set(expected)
        if not keys: return 0.0
        credit = 0.0
        for key in keys:
            actual_values = value.get(key, []) if isinstance(value, dict) else []
            expected_values = expected.get(key, [])
            if not isinstance(actual_values, list): continue
            actual_set, expected_set = set(actual_values), set(expected_values)
            if not actual_set and not expected_set: credit += 1.0
            elif actual_set or expected_set:
                credit += 2.0 * len(actual_set & expected_set) / (len(actual_set) + len(expected_set))
        return credit / len(keys)
    if kind == "numeric_score":
        distance = abs(float(value) - float(expected))
        full, zero = float(check["full_tolerance"]), float(check["zero_tolerance"])
        return 1.0 if distance <= full else max(0.0, (zero - distance) / (zero - full))
    if kind == "numeric_range":
        value = float(value); lo = float(check["minimum"]); hi = float(check["maximum"])
        plo = float(check.get("partial_minimum", lo)); phi = float(check.get("partial_maximum", hi))
        if lo <= value <= hi: return 1.0
        if plo <= value < lo and lo > plo: return (value - plo) / (lo - plo)
        if hi < value <= phi and phi > hi: return (phi - value) / (phi - hi)
        return 0.0
    if kind == "nonempty": return float(isinstance(value, (str, list, dict)) and len(value) > 0)
    raise ValueError("unsupported check " + kind)

try:
    answer = json.loads((app / "answer.json").read_text())
    oracle = json.loads((here / "expected.json").read_text())
    raw = 0.0; critical = []; details = []
    for check in oracle["checks"]:
        try: credit = evaluate(check, get(answer, check["path"]))
        except Exception: credit = 0.0
        raw += float(check["weight"]) * credit
        if check.get("critical") and credit < float(check.get("critical_credit_threshold", 1.0)):
            critical.append(check["id"])
        details.append({"id": check["id"], "credit_fraction": credit})
    score = min(raw, float(oracle.get("critical_failure_cap", 49.0))) if critical else raw
    payload = {"reward": score / 100.0, "tests_total": len(details),
               "tests_passed": sum(row["credit_fraction"] == 1.0 for row in details),
               "details": details, "critical_failed": critical}
except Exception as exc:
    payload = {"reward": 0.0, "tests_total": 0, "tests_passed": 0, "details": [{"error": str(exc)}]}
reward_path.write_text(json.dumps(payload) + "\n")
