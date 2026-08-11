from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from collections import Counter
from itertools import product
from pathlib import Path

from evoldo_bench.bundle import build_runtime_bundle
from evoldo_bench.discovery import discover_tasks, validate_registry
from evoldo_bench.grading import grade_one
from evoldo_bench.contracts import validate_answer
from evoldo_bench.errors import ContractError
from evoldo_bench.utils import load_json


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

    def test_reasoning_cases_expose_six_scoring_dimensions(self):
        reasoning = [task for task in self.tasks if task.data["eligible_modes"] == ["direct_reasoning"]]
        self.assertEqual(56, len(reasoning))
        for task in reasoning:
            case = load_json(task.root / "environment" / "starter" / "case.json")
            self.assertEqual(6, len(case["questions"]), task.task_id)
            self.assertEqual("ranked_choice", case["questions"][4]["kind"])
            self.assertEqual("multi_select", case["questions"][5]["kind"])
            self.assertEqual(2, case["questions"][5]["select_count"])
            oracle = load_json(ORACLES / (task.task_id + ".oracle.json"))
            self.assertEqual("ranking_pairwise", oracle["checks"][4]["kind"])
            self.assertEqual("set_f1", oracle["checks"][5]["kind"])

    def test_reasoning_score_lattice_is_not_coarse_binary(self):
        oracle = load_json(ORACLES / "v06-diagnosis-01-ringing.oracle.json")
        credit_spaces = [sorted(set(check["credits"].values())) for check in oracle["checks"][:4]]
        credit_spaces.append([index / 6.0 for index in range(7)])
        # With four evidence records and a two-record golden set, these are all
        # attainable set-F1 credits for a non-empty valid submission.
        credit_spaces.append([0.0, 0.4, 0.5, 2.0 / 3.0, 0.8, 1.0])
        final_scores = set()
        for credits in product(*credit_spaces):
            raw = sum(float(check["weight"]) * credit
                      for check, credit in zip(oracle["checks"], credits))
            critical = any(
                check.get("critical", False)
                and credit < float(check.get("critical_credit_threshold", 1.0))
                for check, credit in zip(oracle["checks"], credits)
            )
            final_scores.add(round(min(raw, oracle["critical_failure_cap"]) if critical else raw, 6))
        self.assertGreaterEqual(len(final_scores), 500)

    def test_embedded_verifier_matches_official_partial_credit(self):
        task = next(task for task in self.tasks if task.task_id == "v06-sizing-03-comp-cap")
        answer = load_json(task.root / "solution" / "answer.json")
        # Exercise partial ordered-choice credit and partial evidence F1 in one
        # valid answer, including a critical question that is not zero-credit.
        expected_rank = load_json(ORACLES / (task.task_id + ".oracle.json"))["checks"][4]["expected"]
        partial_rank = expected_rank[:]
        partial_rank[1], partial_rank[2] = partial_rank[2], partial_rank[1]
        answer["answers"] = {"q1": "B", "q2": "C", "q3": "C", "q4": "C",
                             "q5": partial_rank, "q6": ["E3"]}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            answer_path = root / "answer.json"
            answer_path.write_text(json.dumps(answer), encoding="utf-8")
            official = grade_one(TASKS, ORACLES, answer_path)
            reward = root / "reward.json"
            env = dict(os.environ, EVOLDO_APP=str(root), EVOLDO_REWARD=str(reward))
            subprocess.run(["python3", str(task.root / "tests" / "verify.py")], check=True, env=env)
            embedded = load_json(reward)
        self.assertAlmostEqual(official["score"] / 100.0, embedded["reward"])

    def test_multi_select_requires_nonempty_declared_evidence_ids(self):
        task = next(task for task in self.tasks if task.task_id == "v06-diagnosis-01-ringing")
        answer = load_json(task.root / "solution" / "answer.json")
        answer["answers"]["q6"] = ["E99"]
        with self.assertRaises(ContractError):
            validate_answer(answer, task)
        answer["answers"]["q6"] = []
        with self.assertRaises(ContractError):
            validate_answer(answer, task)

    def test_companion_hard_dimensions_preserve_physical_goldens(self):
        by_id = {task.task_id: task for task in self.tasks}
        companions = [task for task in self.tasks
                      if task.data["evaluation_role"] == "companion"
                      and task.data["eligible_modes"] == ["direct_reasoning"]]
        self.assertEqual(8, len(companions))
        for companion in companions:
            parent = by_id[companion.data["paired_with"]]
            parent_case = load_json(parent.root / "environment" / "starter" / "case.json")
            companion_case = load_json(companion.root / "environment" / "starter" / "case.json")
            parent_oracle = load_json(ORACLES / (parent.task_id + ".oracle.json"))
            companion_oracle = load_json(ORACLES / (companion.task_id + ".oracle.json"))
            parent_q5 = {option["id"]: option["text"] for option in parent_case["questions"][4]["options"]}
            companion_q5 = {option["id"]: option["text"] for option in companion_case["questions"][4]["options"]}
            parent_ranking = [parent_q5[key] for key in parent_oracle["checks"][4]["expected"]]
            companion_ranking = [companion_q5[key] for key in companion_oracle["checks"][4]["expected"]]
            self.assertEqual(parent_ranking, companion_ranking, companion.task_id)
            parent_evidence = {item["id"]: item["observation"] for item in parent_case["evidence"]}
            companion_evidence = {item["id"]: item["observation"] for item in companion_case["evidence"]}
            parent_gold = {parent_evidence[key] for key in parent_oracle["checks"][5]["expected"]}
            companion_gold = {companion_evidence[key] for key in companion_oracle["checks"][5]["expected"]}
            self.assertEqual(parent_gold, companion_gold, companion.task_id)


if __name__ == "__main__":
    unittest.main()
