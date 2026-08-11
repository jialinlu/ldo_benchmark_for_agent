import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

from evoldo_bench.adapters import CommandAgentAdapter
from evoldo_bench.discovery import discover_tasks
from evoldo_bench.experiment import run_experiment
from evoldo_bench.recovery import classify_attempt, recover_experiment
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


if __name__ == "__main__":
    unittest.main()
