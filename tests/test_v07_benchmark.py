from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest

from evoldo_bench.aggregate import aggregate_scores
from evoldo_bench.contamination import audit_task_collection
from evoldo_bench.discovery import discover_tasks, validate_registry
from evoldo_bench.grading import grade_one
from evoldo_bench.knowledge import load_knowledge_corpus


ROOT = Path(__file__).resolve().parents[1]
TRACK = ROOT / "benchmarks" / "ldo_v07"
TASKS = TRACK / "tasks"
ORACLES = TRACK / "dev_reference" / "oracles"


class V07BenchmarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tasks = discover_tasks(TASKS)

    def test_inventory_layout_and_hard_no_web_policy(self):
        self.assertEqual(27, len(self.tasks))
        self.assertEqual(27, len({task.family_id for task in self.tasks}))
        for task in self.tasks:
            self.assertEqual("demo_task", task.package_style)
            self.assertEqual("forbidden", task.data["network_policy"]["model_web_search"])
            self.assertEqual([], task.data["tool_policy"]["allowed_tools"])
            self.assertEqual(0, task.data["budget"]["max_tool_calls"])
            self.assertTrue({"web_search", "browser", "remote_fetch"}.issubset(
                task.data["tool_policy"]["forbidden_tools"]
            ))
            self.assertEqual(
                {"direct_reasoning", "knowledge_assisted"}, set(task.data["eligible_modes"])
            )
            for relative in (
                "task.toml", "instruction.md", "environment/Dockerfile",
                "tests/Dockerfile", "tests/test.sh", "tests/verify.py",
                "solution/answer.json", "solution/solve.sh",
            ):
                self.assertTrue((task.root / relative).is_file(), (task.task_id, relative))

    def test_registry_collection_and_clean_room_kg(self):
        self.assertTrue(validate_registry(self.tasks, TRACK / "registry.jsonl")["passed"])
        self.assertTrue(audit_task_collection(TASKS, ORACLES)["passed"])
        corpus = load_knowledge_corpus(TRACK / "knowledge" / "ldo_kg_v1.json")
        self.assertGreaterEqual(len(corpus["entries"]), 15)
        knowledge_ids = {entry["id"] for entry in corpus["entries"]}
        for task in self.tasks:
            oracle = json.loads((ORACLES / (task.task_id + ".oracle.json")).read_text())
            self.assertTrue(
                set(oracle.get("relevant_knowledge_ids", [])).issubset(knowledge_ids),
                task.task_id,
            )

    def test_controlled_vocabulary_does_not_leak_reference_sequence_order(self):
        for task in self.tasks:
            case = json.loads((task.root / "environment" / "starter" / "case.json").read_text())
            oracle = json.loads((ORACLES / (task.task_id + ".oracle.json")).read_text())
            candidates = []

            def collect(value):
                if isinstance(value, list):
                    candidates.append(value)
                    for item in value:
                        collect(item)
                elif isinstance(value, dict):
                    for item in value.values():
                        collect(item)

            collect(case["catalogs"])
            collect(case["answer_contract"])
            for check in oracle["checks"]:
                if check["kind"] in {"sequence_alignment", "ranking_pairwise"}:
                    self.assertNotIn(check["expected"], candidates, (task.task_id, check["id"]))

    def test_set_scoring_requires_at_least_one_distractor(self):
        for task in self.tasks:
            case = json.loads((task.root / "environment" / "starter" / "case.json").read_text())
            oracle = json.loads((ORACLES / (task.task_id + ".oracle.json")).read_text())
            fields = case["answer_contract"]["fields"]
            for check in oracle["checks"]:
                if check["kind"] != "set_f1":
                    continue
                field_name = check["path"].split(".")[-1]
                allowed = set(fields[field_name]["allowed"])
                self.assertTrue(
                    allowed.difference(check["expected"]),
                    (task.task_id, field_name, "set answer leaked through allowed vocabulary"),
                )

    def test_result_binding_inputs_are_declared_and_hashable(self):
        for task in self.tasks:
            self.assertTrue(task.prompt_path.is_file(), task.task_id)
            for relative in task.data["input_files"]:
                self.assertTrue(task.source_path(relative).is_file(), (task.task_id, relative))
            self.assertTrue((ORACLES / (task.task_id + ".oracle.json")).is_file(), task.task_id)

    def test_every_reference_answer_scores_100_and_tiers_aggregate(self):
        scores = []
        for task in self.tasks:
            score = grade_one(TASKS, ORACLES, task.root / "solution" / "answer.json")
            self.assertEqual(100.0, score["score"], task.task_id)
            self.assertEqual(task.data["deployment_tier"], score["deployment_tier"])
            scores.append(score)
        report = aggregate_scores(scores, mode="self_check")
        self.assertEqual(100.0, report["family_macro_score"])
        self.assertEqual(5, len(report["by_deployment_tier"]))

    def test_embedded_verifier_matches_official_reference_score(self):
        for task in self.tasks:
            with TemporaryDirectory() as temporary:
                reward = Path(temporary) / "reward.json"
                environment = dict(os.environ)
                environment["EVOLDO_APP"] = str(task.root / "solution")
                environment["EVOLDO_REWARD"] = str(reward)
                completed = subprocess.run(
                    ["python3", str(task.root / "tests" / "verify.py")],
                    env=environment, check=False, capture_output=True, text=True,
                )
                self.assertEqual(0, completed.returncode, (task.task_id, completed.stderr))
                embedded = json.loads(reward.read_text())
                self.assertEqual(1.0, embedded["reward"], task.task_id)


if __name__ == "__main__":
    unittest.main()
