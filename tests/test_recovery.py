import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

from evoldo_bench.adapters import CommandAgentAdapter
from evoldo_bench.discovery import discover_tasks
from evoldo_bench.errors import ContractError
from evoldo_bench.experiment import run_experiment
from evoldo_bench.recovery import (
    _enforce_retry_controls, _explicit_output_budget_exhaustion, _verify_row_bindings,
    classify_attempt, recover_experiment,
)
from evoldo_bench.utils import dump_json, load_json, sha256_file
from tests.helpers import reference_answer


ROOT = Path(__file__).resolve().parents[1]
TASKS = ROOT / "benchmarks" / "ldo_original" / "dev" / "tasks"
ORACLES = ROOT / "benchmarks" / "ldo_original" / "dev_reference" / "oracles"


class RecoveryTests(unittest.TestCase):
    def test_classification_separates_infrastructure_and_model_failures(self):
        self.assertEqual(
            "infrastructure",
            classify_attempt({"status": "provider_timeout"}, {"model_identity_status": "attested"}),
        )
        self.assertEqual(
            "infrastructure",
            classify_attempt(
                {"status": "output_budget_exhausted"}, {"model_identity_status": "attested"}
            ),
        )
        self.assertEqual(
            "infrastructure",
            classify_attempt(
                {"status": "controller_interrupted"},
                {"model_identity_status": "unavailable"},
            ),
        )
        self.assertEqual(
            "infrastructure",
            classify_attempt({"status": "ok"}, {"model_identity_status": "mismatch"}),
        )
        self.assertEqual(
            "model",
            classify_attempt({"status": "format_fail"}, {"model_identity_status": "attested"}),
        )

    def test_recovery_regrades_preserved_answer_without_new_inference(self):
        task = discover_tasks(TASKS)[0]
        answer = reference_answer(task.root, ORACLES / (task.task_id + ".oracle.json"))
        answer["numeric_results"] = {"corners": ["ss", "ff"], "converged": True}
        agent_source = """
import json, os
from pathlib import Path
Path(os.environ["EVOLDO_ANSWER_PATH"]).write_text(json.dumps(%s))
""" % repr(answer)
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            agent = root / "agent.py"
            agent.write_text(agent_source, encoding="utf-8")
            source = root / "source"
            run_experiment(
                TASKS, ORACLES, source,
                CommandAgentAdapter([sys.executable, str(agent)]),
                "test-model", "direct_reasoning", rollouts=1, base_seed=17,
                task_ids=[task.task_id],
            )
            manifest = load_json(source / "experiment_manifest.json")
            row = manifest["rows"][0]
            run_dir = source / Path(row["telemetry_file"]).parent
            original_hash = sha256_file(run_dir / "app" / "answer.json")
            record = load_json(run_dir / "run_record.json")
            record["status"] = "format_fail"
            record["answer_error"] = "numeric_results must map strings to numbers"
            dump_json(run_dir / "run_record.json", record)
            row.update({"status": "format_fail", "score": None, "passed": False, "score_file": None})
            dump_json(source / "experiment_manifest.json", manifest)

            recovered = root / "recovered"
            result = recover_experiment(
                source, recovered, TASKS, ORACLES,
                CommandAgentAdapter([sys.executable, str(agent)]),
                max_infrastructure_retries=0,
            )
            recovered_row = result["rows"][0]
            self.assertTrue(result["capability_complete"])
            self.assertEqual("framework_regraded", recovered_row["resolution_status"])
            self.assertEqual("ok", recovered_row["status"])
            self.assertEqual(100.0, recovered_row["score"])
            self.assertEqual(1, result["recovery"]["attempt_count"])
            answer_path = recovered / Path(recovered_row["telemetry_file"]).parent / "app" / "answer.json"
            self.assertEqual(original_hash, sha256_file(answer_path))

    def test_recovery_rejects_benchmark_content_drift(self):
        task = discover_tasks(TASKS)[0]
        row = {
            "task_manifest_sha256": sha256_file(task.manifest_path),
            "task_contract_sha256": "changed-contract",
            "prompt_sha256": sha256_file(task.prompt_path),
            "input_files_sha256": {
                value: sha256_file(task.source_path(value))
                for value in task.data["input_files"]
            },
            "answer_contract_sha256": sha256_file(
                task.source_path(task.data["answer_template_file"])
            ),
            "oracle_sha256": sha256_file(ORACLES / (task.task_id + ".oracle.json")),
        }
        with self.assertRaisesRegex(ContractError, "content binding changed"):
            _verify_row_bindings(task, row, ORACLES)

    def test_recovery_detects_legacy_provider_length_finish(self):
        with TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            dump_json(run_dir / "stdout.log", {
                "choices": [{"finish_reason": "length", "message": {"content": ""}}],
                "usage": {"completion_tokens": 4096},
            })
            self.assertEqual("length", _explicit_output_budget_exhaustion(run_dir))
            dump_json(run_dir / "stdout.log", {"choices": [{"finish_reason": "stop"}]})
            self.assertIsNone(_explicit_output_budget_exhaustion(run_dir))

    def test_retry_with_changed_model_parameters_is_infrastructure_invalid(self):
        with TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            dump_json(run_dir / "run_record.json", {"status": "ok"})
            row = {
                "requested_model_parameters": {"reasoning_mode": "disabled"},
                "provider_seed": 17,
                "knowledge_context": None,
            }
            attempt = {
                "requested_model_parameters": {"reasoning_mode": "fixed_budget"},
                "provider_seed": 17,
                "knowledge_context": None,
                "classification": "model", "status": "ok", "score": 100.0,
                "passed": True, "score_file": "score.json",
            }
            _enforce_retry_controls(row, attempt, run_dir)
            self.assertEqual("infrastructure", attempt["classification"])
            self.assertEqual("control_mismatch", attempt["status"])
            self.assertIsNone(attempt["score"])
            self.assertEqual("control_mismatch", load_json(run_dir / "run_record.json")["status"])

    def test_legacy_retry_accepts_only_new_timeout_telemetry_field(self):
        with TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            (run_dir / "run_record.json").write_text(json.dumps({"status": "ok"}))
            row = {
                "requested_model_parameters": {"reasoning_mode": "disabled"},
                "provider_seed": 9,
                "knowledge_context": None,
            }
            attempt = {
                "requested_model_parameters": {
                    "reasoning_mode": "disabled", "output_timeout_seconds": 270,
                },
                "provider_seed": 9,
                "knowledge_context": None,
                "classification": "model", "status": "ok", "score": 100,
                "passed": True, "score_file": "score.json",
            }
            _enforce_retry_controls(row, attempt, run_dir)
            self.assertEqual("ok", attempt["status"])
            self.assertEqual(100, attempt["score"])
            self.assertEqual("ok", load_json(run_dir / "run_record.json")["status"])


if __name__ == "__main__":
    unittest.main()
