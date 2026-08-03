from pathlib import Path
import unittest

from evoldo_bench.contracts import (
    ContractError,
    load_task,
    validate_answer,
    validate_oracle,
    validate_probe_contract,
)
from evoldo_bench.discovery import discover_tasks, inventory, validate_registry
from evoldo_bench.utils import load_json

ROOT = Path(__file__).resolve().parents[1]
TASKS = ROOT / "benchmarks" / "ldo_original" / "dev" / "tasks"
ORACLES = ROOT / "benchmarks" / "ldo_original" / "dev_reference" / "oracles"


class ContractAndDiscoveryTests(unittest.TestCase):
    def test_public_dev_inventory(self):
        tasks = discover_tasks(TASKS)
        data = inventory(tasks)
        self.assertEqual(36, data["task_count"])
        self.assertEqual(12, data["family_count"])
        self.assertEqual({"canonical": 12, "counterexample": 12, "metamorphic": 12}, data["variant_counts"])
        self.assertEqual(36, sum(data["suite_counts"].values()))

    def test_every_oracle_is_valid_and_matches(self):
        for task in discover_tasks(TASKS):
            oracle = load_json(ORACLES / (task.task_id + ".oracle.json"))
            validate_oracle(oracle)
            self.assertEqual(task.task_id, oracle["task_id"])
            self.assertEqual(task.family_id, oracle["family_id"])

    def test_registry_matches_generated_tasks(self):
        report = validate_registry(
            discover_tasks(TASKS),
            ROOT / "benchmarks" / "ldo_original" / "registry.jsonl",
        )
        self.assertTrue(report["passed"], report)
        self.assertEqual(36, report["row_count"])

    def test_answer_rejects_duplicate_controlled_tokens(self):
        task = discover_tasks(TASKS)[0]
        answer = load_json(task.root / "answer_template.json")
        answer.update({
            "conclusion": "x",
            "analysis_regime": "connectivity",
            "held_fixed": ["same", "same"],
            "mechanism": "x",
            "claim_boundary": "x",
            "confidence": 0.5,
        })
        with self.assertRaises(ContractError):
            validate_answer(answer)

    def test_probe_contract_requires_measurement_and_stop_condition(self):
        valid = {
            "schema_version": "1.0",
            "task_id": "trend_compensation_cap--canonical",
            "question": "Does phase margin improve as Cc increases?",
            "analysis_regime": "stb",
            "held_fixed": ["load", "bias"],
            "probe_family": "three_point_trend",
            "intervention": {"cc_pf": [0.5, 1.0, 2.0]},
            "measurement": {"phase_margin_deg": "three values"},
            "expected_use": "disambiguate",
            "stop_condition": {"minimum_valid_points": 3},
            "claim_boundary": "Only for the supplied operating point.",
        }
        self.assertEqual(valid, validate_probe_contract(valid))
        invalid = dict(valid)
        invalid["measurement"] = {}
        with self.assertRaises(ContractError):
            validate_probe_contract(invalid)


if __name__ == "__main__":
    unittest.main()
