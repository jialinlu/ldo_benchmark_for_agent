#!/usr/bin/env python3
import json
import os
from pathlib import Path

from evoldo_bench.public_pdk import run_closure_task


def main() -> None:
    task_id = os.environ["EVOLDO_CLOSURE_TASK_ID"]
    output = Path("/logs/verifier/evidence")
    result = run_closure_task(
        task_id,
        Path(os.environ.get("EVOLDO_PDK_ROOT", "/opt/sky130")),
        output,
        candidate=Path("/app/circuit.spi"),
        track_root=Path("/app/evoldo_tests/track"),
    )
    checks = [check for scenario in result.get("scenarios", []) for check in scenario.get("checks", [])]
    total = len(checks) or 1
    passed = sum(check.get("status") == "PASS" for check in checks)
    reward = passed / total if checks else float(bool(result.get("passed")))
    payload = {
        "reward": reward,
        "partial": reward,
        "tests_total": total,
        "tests_passed": passed if checks else int(bool(result.get("passed"))),
        "outcome": result.get("status", "UNKNOWN"),
        "task_id": task_id,
    }
    target = Path("/logs/verifier")
    target.mkdir(parents=True, exist_ok=True)
    (target / "reward.json").write_text(json.dumps(payload) + "\n")
    (target / "result.json").write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
