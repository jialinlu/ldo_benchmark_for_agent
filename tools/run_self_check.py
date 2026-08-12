#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from evoldo_bench.aggregate import aggregate_scores
from evoldo_bench.bundle import build_runtime_bundle
from evoldo_bench.contamination import audit_task_collection
from evoldo_bench.discovery import discover_tasks, inventory
from evoldo_bench.grading import grade_one
from evoldo_bench.utils import load_json

TRACK = ROOT / "benchmarks" / "ldo_v07"
TASKS = TRACK / "tasks"
ORACLES = TRACK / "dev_reference" / "oracles"


def main() -> int:
    tasks = discover_tasks(TASKS)
    inv = inventory(tasks)
    assert inv["task_count"] == 27 and inv["family_count"] == 27, inv
    audit = audit_task_collection(TASKS, ORACLES)
    assert audit["passed"], audit
    scores = []
    for task in tasks:
        score = grade_one(TASKS, ORACLES, task.root / "solution" / "answer.json")
        assert score["score"] == 100.0, (task.task_id, score)
        assert score["deployment_tier"] == task.data["deployment_tier"], task.task_id
        scores.append(score)
    report = aggregate_scores(scores, mode="public_dev_self_check")
    assert report["family_macro_score"] == 100.0, report
    with TemporaryDirectory() as temporary:
        manifest = build_runtime_bundle(tasks[0], Path(temporary) / "app")
        assert not manifest["oracle_included"]
    print(json.dumps({
        "passed": True,
        "tasks": inv["task_count"],
        "families": inv["family_count"],
        "suites": inv["suite_counts"],
        "reference_score": report["family_macro_score"],
        "audit": "PASS",
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
