from pathlib import Path
import unittest

from evoldo_bench.aggregate import aggregate_scores, failed_rollout_score, paired_lift
from evoldo_bench.contracts import Task, validate_answer, validate_oracle
from evoldo_bench.errors import ContractError
from evoldo_bench.discovery import discover_tasks
from evoldo_bench.graders import grade_answer
from evoldo_bench.utils import load_json
from tests.helpers import reference_answer

ROOT = Path(__file__).resolve().parents[1]
TASKS = ROOT / "benchmarks" / "ldo_original" / "dev" / "tasks"
ORACLES = ROOT / "benchmarks" / "ldo_original" / "dev_reference" / "oracles"


class GradingAndAggregateTests(unittest.TestCase):
    def test_choice_credit_produces_auditable_partial_score(self):
        task = Task(Path("/tmp/task"), {
            "task_id": "credit-task", "family_id": "credit-task", "lineage_id": "credit-task",
            "suite": "sizing", "level": "L4", "variant": "canonical", "split": "dev",
            "evaluation_role": "coupled",
        })
        answer = {"schema_version": "2.0", "task_id": "credit-task", "answers": {"q1": "B"},
                  "claim_boundary": "bounded", "confidence": 0.5}
        oracle = {"schema_version": "1.0", "task_id": "credit-task", "family_id": "credit-task",
                  "checks": [{"id": "q1", "path": "answers.q1", "kind": "choice_credit",
                              "expected": "A", "credits": {"A": 1.0, "B": 0.6, "C": 0.2, "D": 0.0},
                              "weight": 100}], "pass_threshold": 70}
        validate_oracle(oracle)
        # Avoid task-bound case validation; this isolates deterministic oracle behavior.
        from unittest.mock import patch
        with patch("evoldo_bench.graders.deterministic.validate_answer", return_value=answer):
            score = grade_answer(task, answer, oracle)
        self.assertEqual(60.0, score["score"])
        self.assertEqual(0.6, score["checks"][0]["credit_fraction"])

    def test_set_f1_rewards_overlap_and_penalizes_extra_evidence(self):
        task = Task(Path("/tmp/task"), {
            "task_id": "evidence-task", "family_id": "evidence-task", "lineage_id": "evidence-task",
            "suite": "diagnosis", "level": "L4", "variant": "canonical", "split": "dev",
            "evaluation_role": "coupled",
        })
        answer = {"schema_version": "2.0", "task_id": "evidence-task",
                  "answers": {"q1": ["E1", "E3", "E4"]}, "claim_boundary": "bounded", "confidence": 0.5}
        oracle = {"schema_version": "1.0", "task_id": "evidence-task", "family_id": "evidence-task",
                  "checks": [{"id": "q1", "path": "answers.q1", "kind": "set_f1",
                              "expected": ["E1", "E3"], "weight": 100}], "pass_threshold": 70}
        from unittest.mock import patch
        with patch("evoldo_bench.graders.deterministic.validate_answer", return_value=answer):
            score = grade_answer(task, answer, oracle)
        self.assertEqual(80.0, score["score"])
        self.assertEqual(0.8, score["checks"][0]["credit_fraction"])

    def test_unscored_numeric_results_accept_nested_supporting_data(self):
        task = discover_tasks(TASKS)[0]
        answer = reference_answer(task.root, ORACLES / (task.task_id + ".oracle.json"))
        answer["numeric_results"] = {
            "phase_margin_deg": [42.0, 58.0],
            "corner": "ss",
            "converged": True,
            "sweep": {"load_ma": [1, 10, 100]},
        }
        validate_answer(answer, task)

    def test_reference_answers_score_100(self):
        scores = []
        for task in discover_tasks(TASKS):
            oracle_path = ORACLES / (task.task_id + ".oracle.json")
            oracle = load_json(oracle_path)
            answer = reference_answer(task.root, oracle_path)
            score = grade_answer(task, answer, oracle)
            self.assertEqual(100.0, score["score"], task.task_id)
            scores.append(score)
        report = aggregate_scores(scores, mode="reference_dev_check")
        self.assertEqual(100.0, report["family_macro_score"])
        self.assertEqual(40, report["family_count"])

    def test_critical_conclusion_failure_caps_score(self):
        task = discover_tasks(TASKS)[0]
        oracle_path = ORACLES / (task.task_id + ".oracle.json")
        oracle = load_json(oracle_path)
        answer = reference_answer(task.root, oracle_path)
        case = load_json(task.root / "inputs" / "case.json")
        answer["conclusion"] = next(
            value for value in case["controlled_vocabulary"]["conclusion"]
            if value != answer["conclusion"]
        )
        score = grade_answer(task, answer, oracle)
        self.assertEqual(49.0, score["score"])
        self.assertIn("conclusion", score["critical_failed"])

    def test_controlled_vocabulary_rejects_unknown_tokens(self):
        task = discover_tasks(TASKS)[0]
        oracle_path = ORACLES / (task.task_id + ".oracle.json")
        answer = reference_answer(task.root, oracle_path)
        answer["evidence_facts"].append("invented_oracle_shaped_token")
        with self.assertRaises(ContractError):
            grade_answer(task, answer, load_json(oracle_path))

    def test_exact_sets_reject_selecting_every_allowed_option(self):
        task = discover_tasks(TASKS)[0]
        oracle_path = ORACLES / (task.task_id + ".oracle.json")
        oracle = load_json(oracle_path)
        answer = reference_answer(task.root, oracle_path)
        case = load_json(task.root / "inputs" / "case.json")
        answer["evidence_facts"] = case["controlled_vocabulary"]["evidence_facts"]
        score = grade_answer(task, answer, oracle)
        self.assertLess(score["score"], 100.0)

    def test_failed_rollout_score_is_zero(self):
        score = failed_rollout_score({
            "task_id": "a", "family_id": "fa", "suite": "trend", "level": "L2",
            "variant": "canonical", "rollout": 2, "seed": 9, "status": "timeout",
        })
        self.assertEqual(0.0, score["score"])
        self.assertFalse(score["passed"])
        self.assertTrue(score["synthetic_failure_score"])

    def test_paired_lift(self):
        result = paired_lift({
            "direct_reasoning": {"family_macro_score": 40},
            "agentic_skill": {"family_macro_score": 58.5},
            "simulation_assisted": {"family_macro_score": 61},
        })
        self.assertEqual(18.5, result["skill_lift"])
        self.assertEqual(2.5, result["simulation_lift"])

    def test_aggregate_reports_partial_credit_by_dimension(self):
        report = aggregate_scores([{ "task_id": "t", "family_id": "f", "suite": "sizing", "level": "L4",
            "variant": "canonical", "evaluation_role": "coupled", "score": 82, "passed": True,
            "critical_failed": [], "checks": [
                {"id": "q1", "dimension": "mechanism", "weight": 20, "earned": 11,
                 "credit_fraction": 0.55}
            ]}], mode="test")
        self.assertEqual(55.0, report["by_scoring_dimension"]["mechanism"]["mean"])


if __name__ == "__main__":
    unittest.main()
