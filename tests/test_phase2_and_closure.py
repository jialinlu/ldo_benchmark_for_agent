from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from evoldo_bench.adapters import NgspiceBatchAdapter, ProcessSimulatorAdapter
from evoldo_bench.aggregate import aggregate_rollouts, failed_rollout_score
from evoldo_bench.calibration import calibrate_judges, combine_judges
from evoldo_bench.discovery import get_task
from evoldo_bench.exam import create_private_canary, freeze_exam, redact_exam_manifest, verify_exam
from evoldo_bench.experiment import compare_treatments
from evoldo_bench.leaderboard import write_leaderboard
from evoldo_bench.probes import evaluate_probe_contract
from evoldo_bench.qualification import build_candidate_manifest, qualify_candidate, REQUIRED_GATES
from evoldo_bench.telemetry import empty_telemetry, validate_telemetry, wilson_interval

ROOT = Path(__file__).resolve().parents[1]
TASKS = ROOT / "benchmarks" / "ldo_original" / "dev" / "tasks"
ORACLES = ROOT / "benchmarks" / "ldo_original" / "dev_reference" / "oracles"


class Phase2AndClosureTests(unittest.TestCase):
    def valid_probe(self):
        return {
            "schema_version": "1.0",
            "task_id": "trend_compensation_cap--canonical",
            "question": "Does Cc change phase margin?",
            "analysis_regime": "stb",
            "held_fixed": ["load", "bias"],
            "probe_family": "three_point_trend",
            "intervention": {"cc": [0.5, 1.0, 2.0]},
            "measurement": {"phase_margin_deg": "three values"},
            "expected_use": "disambiguate",
            "stop_condition": {"minimum_valid_points": 3},
            "claim_boundary": "Supplied operating point only.",
        }

    def test_probe_policy_detects_wrong_regime_confound_and_invented_artifact(self):
        task = get_task(TASKS, "trend_compensation_cap--canonical")
        probe = self.valid_probe()
        probe["analysis_regime"] = "startup"
        probe["intervention"]["load"] = [1, 10, 100]
        probe["source_artifacts"] = ["invented.scs"]
        report = evaluate_probe_contract(probe, task, available_artifacts=["inputs/case.json"])
        codes = {item["code"] for item in report["violations"]}
        self.assertIn("WRONG_REGIME", codes)
        self.assertIn("CONFOUNDED_INTERVENTION", codes)
        self.assertIn("INVENTED_ARTIFACT", codes)

    def test_process_simulator_json_protocol_and_infra_classification(self):
        adapter = ProcessSimulatorAdapter([sys.executable, str(ROOT / "examples" / "simulators" / "analytic_probe_simulator.py")])
        request = json.loads((ROOT / "examples" / "simulators" / "rc_probe_request.json").read_text())
        with TemporaryDirectory() as temporary:
            result = adapter.run(request, Path(temporary))
            self.assertEqual("OK", result["status"])
            self.assertEqual(3, len(result["points"]))
        missing = ProcessSimulatorAdapter(["definitely-not-a-real-simulator"])
        with TemporaryDirectory() as temporary:
            result = missing.run(request, Path(temporary))
            self.assertEqual("INFRA_FAIL", result["status"])

    @unittest.skipUnless(shutil.which("ngspice"), "ngspice is optional")
    def test_ngspice_adapter_parses_declared_measurements(self):
        request = json.loads((ROOT / "examples" / "simulators" / "rc_ngspice_request.json").read_text())
        with TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            shutil.copy2(ROOT / "examples" / "simulators" / "rc_tran.cir", workspace / "rc_tran.cir")
            result = NgspiceBatchAdapter().run(request, workspace)
            self.assertEqual("OK", result["status"])
            self.assertEqual({"vout_at_1us", "vout_at_5us"}, set(result["measurements"]))

    def test_effort_metrics_and_wilson_interval(self):
        telemetry = [empty_telemetry("a", "model", "direct_reasoning", index, index, 2.0) for index in range(3)]
        for row in telemetry:
            validate_telemetry(row)
        scores = [
            {"task_id": "a", "family_id": "fa", "suite": "trend", "level": "L2", "variant": "canonical", "score": value, "passed": value >= 70, "critical_failed": []}
            for value in (100, 80, 40)
        ]
        report = aggregate_rollouts(scores, telemetry, "model", "direct_reasoning")
        self.assertAlmostEqual(2 / 3, report["pass_at_1"], places=6)
        self.assertEqual(0, report["effort"]["avg_tool_calls"])
        low, high = wilson_interval(2, 3)
        self.assertLess(low, 2 / 3)
        self.assertGreater(high, 2 / 3)

    def test_missing_token_telemetry_is_unknown_not_zero(self):
        row = empty_telemetry("a", "model", "direct_reasoning", 0, 7, 2.0)
        self.assertEqual("unavailable", row["token_measurement_status"])
        self.assertIsNone(row["token_breakdown"]["input"])
        score = failed_rollout_score({
            "task_id": "a", "family_id": "fa", "suite": "trend", "level": "L2",
            "variant": "canonical", "status": "failed",
        })
        report = aggregate_rollouts([score], [row], "model", "direct_reasoning")
        self.assertFalse(report["token_efficiency"]["measurement_complete"])
        self.assertIsNone(report["token_efficiency"]["tokens_per_score_point"])

    def test_exam_manifest_detects_tamper(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            tasks = root / "tasks"
            oracles = root / "oracles"
            tasks.mkdir(); oracles.mkdir()
            (tasks / "task.json").write_text("{}")
            (oracles / "oracle.json").write_text("{}")
            canary = create_private_canary(tasks / "CANARY.txt", "test", token="fixed")
            self.assertEqual(64, len(canary["canary_sha256"]))
            manifest_path = root / "exam.json"
            manifest = freeze_exam(manifest_path, tasks, oracles, {"rollouts": 3}, release_id="test")
            self.assertTrue(verify_exam(manifest, tasks, oracles)["passed"])
            public = redact_exam_manifest(manifest)
            self.assertNotIn("files", public["trees"]["tasks"])
            self.assertNotIn("policy", public)
            (tasks / "task.json").write_text('{"changed": true}')
            self.assertFalse(verify_exam(manifest, tasks, oracles)["passed"])

    def test_qualification_requires_every_fresh_gate(self):
        with TemporaryDirectory() as temporary:
            candidate_root = Path(temporary) / "candidate"
            candidate_root.mkdir()
            (candidate_root / "design.json").write_text('{"device": "mos"}')
            candidate = build_candidate_manifest(candidate_root, "candidate-1")
            evidence = [
                {"gate": gate, "candidate_digest": candidate["candidate_digest"], "status": "PASS", "evidence_sha256": "a" * 64}
                for gate in REQUIRED_GATES
            ]
            self.assertTrue(qualify_candidate(candidate, evidence)["qualified"])
            evidence[0] = dict(evidence[0], candidate_digest="stale")
            result = qualify_candidate(candidate, evidence)
            self.assertFalse(result["qualified"])
            self.assertIn(REQUIRED_GATES[0], result["stale_evidence_gates"])

    def test_dual_judge_calibration_and_disagreement_routing(self):
        humans = [
            {"item_id": "a", "adjudicated_score": 80, "adjudicated_label": "sound", "critical_error": False},
            {"item_id": "b", "adjudicated_score": 20, "adjudicated_label": "unsafe", "critical_error": True},
        ]
        judges = []
        for judge_id in ("judge-a", "judge-b"):
            judges.extend([
                {"item_id": "a", "judge_id": judge_id, "score": 80, "label": "sound", "critical_error": False},
                {"item_id": "b", "judge_id": judge_id, "score": 20, "label": "unsafe", "critical_error": True},
            ])
        self.assertTrue(calibrate_judges(humans, judges)["passed"])
        combined = combine_judges([
            {"judge_id": "judge-a", "score": 80, "label": "sound", "critical_error": False},
            {"judge_id": "judge-b", "score": 40, "label": "unsafe", "critical_error": True},
        ])
        self.assertEqual("HUMAN_REVIEW", combined["status"])

    def test_static_leaderboard_exposes_score_and_effort(self):
        reports = [
            {"model_id": "a", "mode": "direct_reasoning", "pass_at_1": 0.5, "pass_at_1_ci95": [0.3, 0.7], "spec_score": 0.6, "family_macro_score": 60, "rollout_count": 6, "effort": {"avg_total_cost_usd": 2, "avg_output_tokens": 100, "avg_steps": 4, "avg_tool_calls": 0, "avg_wall_seconds": 30}},
            {"model_id": "b", "mode": "agentic_skill", "pass_at_1": 0.7, "pass_at_1_ci95": [0.5, 0.8], "spec_score": 0.8, "family_macro_score": 80, "rollout_count": 6, "effort": {"avg_total_cost_usd": 1, "avg_output_tokens": 200, "avg_steps": 6, "avg_tool_calls": 1, "avg_wall_seconds": 40}},
        ]
        with TemporaryDirectory() as temporary:
            board = write_leaderboard(Path(temporary), reports)
            self.assertEqual(2, board["entry_count"])
            self.assertTrue((Path(temporary) / "index.html").is_file())
            self.assertTrue(board["entries"][0]["pareto"])

    def test_paired_treatment_comparator_rejects_seed_drift(self):
        row = {"task_id": "a", "rollout": 0, "seed": 7, "task_manifest_sha256": "a", "answer_contract_sha256": "b", "budget": {"timeout_seconds": 1, "max_tool_calls": 0}}
        direct = {"model_id": "m", "mode": "direct_reasoning", "rows": [row]}
        skill = {"model_id": "m", "mode": "agentic_skill", "rows": [dict(row)]}
        self.assertTrue(compare_treatments([direct, skill])["passed"])
        skill["rows"][0]["seed"] = 8
        self.assertFalse(compare_treatments([direct, skill])["passed"])


if __name__ == "__main__":
    unittest.main()
