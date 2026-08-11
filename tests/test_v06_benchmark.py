from __future__ import annotations

import tempfile
import unittest
from collections import Counter
from pathlib import Path

from evoldo_bench.bundle import build_runtime_bundle
from evoldo_bench.discovery import discover_tasks, validate_registry
from evoldo_bench.grading import grade_one


ROOT = Path(__file__).resolve().parents[1]
TRACK = ROOT / "benchmarks" / "ldo_v06"
TASKS = TRACK / "tasks"
ORACLES = TRACK / "dev_reference" / "oracles"


class V06BenchmarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tasks = discover_tasks(TASKS)

    def test_inventory_and_roles(self):
        self.assertEqual(len(self.tasks), 69)
        roles = Counter(task.data["evaluation_role"] for task in self.tasks)
        self.assertEqual(roles["atomic"], 24)
        self.assertEqual(roles["coupled"], 16)
        self.assertEqual(roles["existing_architecture_optimization"], 8)
        self.assertEqual(roles["tool_sizing_treatment"], 6)
        self.assertEqual(roles["eda_live"], 6)
        self.assertEqual(roles["companion"], 9)

    def test_demo_top_level_layout_only(self):
        expected = {"task.toml", "instruction.md", "environment", "tests", "solution"}
        for task in self.tasks:
            self.assertEqual({path.name for path in task.root.iterdir()}, expected, task.task_id)
            self.assertFalse((task.root / "task.json").exists())
            self.assertTrue((task.root / "environment" / "starter" / "task_contract.json").is_file())

    def test_registry_and_reference_answers(self):
        self.assertTrue(validate_registry(self.tasks, TRACK / "registry.jsonl")["passed"])
        for task in self.tasks:
            score = grade_one(TASKS, ORACLES, task.root / "solution" / "answer.json")
            self.assertEqual(score["score"], 100.0, task.task_id)

    def test_runtime_bundle_excludes_verifier_and_solution(self):
        task = self.tasks[0]
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory) / "app"
            build_runtime_bundle(task, bundle)
            names = {path.relative_to(bundle).parts[0] for path in bundle.rglob("*") if path.is_file()}
            self.assertNotIn("tests", names)
            self.assertNotIn("solution", names)
            self.assertIn("case.json", names)


if __name__ == "__main__":
    unittest.main()
