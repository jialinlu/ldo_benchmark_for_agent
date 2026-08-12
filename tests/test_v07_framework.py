from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

from evoldo_bench.contracts import Task, validate_answer, validate_task
from evoldo_bench.errors import ContractError
from evoldo_bench.graders.deterministic import grade_answer
from evoldo_bench.experiment import compare_treatments, run_experiment
from evoldo_bench.adapters import CommandAgentAdapter
from evoldo_bench.knowledge import load_knowledge_corpus, materialize_retrieval, retrieve


class V07FrameworkTests(unittest.TestCase):
    def _task(self, root: Path) -> Task:
        contract = {
            "schema_version": "3.0", "task_id": "v07-test", "family_id": "fam",
            "lineage_id": "line", "split": "dev", "variant": "canonical",
            "suite": "sizing", "level": "L3", "capabilities": ["sizing"],
            "title": "Sizing recovery", "language": "en", "prompt_file": "instruction.md",
            "input_files": ["case.json"], "answer_template_file": "answer_template.json",
            "eligible_modes": ["direct_reasoning", "knowledge_assisted"],
            "budget": {"timeout_seconds": 60, "max_tool_calls": 0},
            "network_policy": {"model_web_search": "forbidden", "external_network": "provider_control_plane_only"},
            "tool_policy": {"allowed_tools": [], "forbidden_tools": ["web_search", "browser", "remote_fetch"]},
            "benchmark_version": "0.7.0", "evaluation_role": "calibration",
            "deployment_tier": "T2_bounded_workflow",
            "knowledge_effect_expectation": "benefit_expected",
        }
        (root / "instruction.md").write_text("Recover operating point before stability sizing.")
        (root / "answer_template.json").write_text("{}")
        (root / "case.json").write_text(json.dumps({"answer_contract": {"fields": {
            "decision": {"type": "string", "allowed": ["repair", "qualify"]},
            "sequence": {"type": "string_list", "allowed": ["op", "headroom", "stb", "full"]},
            "estimate": {"type": "number"},
            "class_map": {"type": "string_map", "required_keys": ["r1", "r2"],
                          "value_allowed": ["circuit", "infra"]},
        }}}))
        return Task(root, validate_task(contract, root))

    def test_v3_contract_requires_machine_enforced_no_web(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            task = self._task(root)
            bad = dict(task.data)
            bad["network_policy"] = {"model_web_search": "allowed", "external_network": "no_network"}
            with self.assertRaises(ContractError):
                validate_task(bad, root)

    def test_v3_contract_requires_knowledge_effect_expectation(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            task = self._task(root)
            bad = dict(task.data)
            bad.pop("knowledge_effect_expectation")
            with self.assertRaises(ContractError):
                validate_task(bad, root)

    def test_v3_structured_answer_and_partial_graders(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            task = self._task(root)
            answer = {
                "schema_version": "3.0", "task_id": "v07-test",
                "artifact": {
                    "decision": "repair", "sequence": ["op", "stb", "full"],
                    "estimate": 1.18, "class_map": {"r1": "circuit", "r2": "circuit"},
                },
                "claim_boundary": "Supplied evidence only.", "confidence": 0.7,
            }
            validate_answer(answer, task)
            oracle = {
                "schema_version": "1.0", "task_id": "v07-test", "family_id": "fam",
                "checks": [
                    {"id": "d", "path": "artifact.decision", "kind": "exact", "expected": "repair", "weight": 20},
                    {"id": "s", "path": "artifact.sequence", "kind": "sequence_alignment",
                     "expected": ["op", "headroom", "stb", "full"], "weight": 30},
                    {"id": "n", "path": "artifact.estimate", "kind": "numeric_score", "expected": 1.2,
                     "full_tolerance": 0.01, "zero_tolerance": 0.2, "weight": 20},
                    {"id": "m", "path": "artifact.class_map", "kind": "mapping_credit",
                     "expected": {"r1": "circuit", "r2": "infra"}, "weight": 30},
                ],
            }
            score = grade_answer(task, answer, oracle)
            self.assertGreater(score["score"], 50)
            self.assertLess(score["score"], 100)

    def test_multilabel_mapping_grades_each_record_and_tag_partially(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            task = self._task(root)
            case = json.loads((root / "case.json").read_text())
            case["answer_contract"]["fields"]["tags"] = {
                "type": "string_list_map", "required_keys": ["e1", "e2"],
                "allowed_keys": ["e1", "e2"],
                "value_allowed": ["measured", "budget", "objective", "retry", "exclude"],
            }
            (root / "case.json").write_text(json.dumps(case))
            task = Task(root, validate_task(task.data, root))
            answer = {
                "schema_version": "3.0", "task_id": "v07-test",
                "artifact": {
                    "decision": "repair", "sequence": ["op"], "estimate": 1.2,
                    "class_map": {"r1": "circuit", "r2": "infra"},
                    "tags": {"e1": ["measured", "budget"], "e2": ["retry"]},
                },
                "claim_boundary": "Supplied evidence only.", "confidence": 0.7,
            }
            oracle = {
                "schema_version": "1.0", "task_id": "v07-test", "family_id": "fam",
                "checks": [{
                    "id": "tags", "path": "artifact.tags", "kind": "multilabel_mapping_credit",
                    "expected": {"e1": ["measured", "budget", "objective"], "e2": ["retry", "exclude"]},
                    "weight": 100,
                }],
            }
            score = grade_answer(task, answer, oracle)
            self.assertGreater(score["score"], 50)
            self.assertLess(score["score"], 100)

    def test_multilabel_mapping_scores_scalar_values_as_zero_credit_not_format_failure(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            task = self._task(root)
            case = json.loads((root / "case.json").read_text())
            case["answer_contract"]["fields"]["tags"] = {
                "type": "string_list_map", "required_keys": ["e1", "e2"],
                "allowed_keys": ["e1", "e2"], "value_allowed": ["measured", "retry"],
            }
            (root / "case.json").write_text(json.dumps(case))
            task = Task(root, validate_task(task.data, root))
            answer = {
                "schema_version": "3.0", "task_id": "v07-test",
                "artifact": {
                    "decision": "repair", "sequence": ["op"], "estimate": 1.2,
                    "class_map": {"r1": "circuit", "r2": "infra"},
                    "tags": {"e1": "measured", "e2": "retry"},
                },
                "claim_boundary": "Supplied evidence only.", "confidence": 0.7,
            }
            with self.assertRaises(ContractError):
                validate_answer(answer, task)
            oracle = {
                "schema_version": "1.0", "task_id": "v07-test", "family_id": "fam",
                "checks": [{"id": "tags", "path": "artifact.tags",
                            "kind": "multilabel_mapping_credit",
                            "expected": {"e1": ["measured"], "e2": ["retry"]}, "weight": 100}],
            }
            self.assertEqual(0.0, grade_answer(task, answer, oracle)["score"])

    def test_malformed_field_does_not_erase_other_atomic_checks(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            task = self._task(root)
            case = json.loads((root / "case.json").read_text())
            case["answer_contract"]["fields"]["tags"] = {
                "type": "string_list_map", "required_keys": ["e1"],
                "allowed_keys": ["e1"], "value_allowed": ["measured"],
            }
            (root / "case.json").write_text(json.dumps(case))
            task = Task(root, validate_task(task.data, root))
            answer = {
                "schema_version": "3.0", "task_id": "v07-test",
                "artifact": {
                    "decision": "repair", "sequence": ["op"], "estimate": 1.2,
                    "class_map": {"r1": "circuit", "r2": "infra"},
                    "tags": {"e1": [{"not": "a controlled scalar"}]},
                },
                "claim_boundary": "Supplied evidence only.", "confidence": 0.7,
            }
            with self.assertRaises(ContractError):
                validate_answer(answer, task)
            oracle = {
                "schema_version": "1.0", "task_id": "v07-test", "family_id": "fam",
                "checks": [
                    {"id": "decision", "path": "artifact.decision", "kind": "exact",
                     "expected": "repair", "weight": 30},
                    {"id": "tags", "path": "artifact.tags", "kind": "multilabel_mapping_credit",
                     "expected": {"e1": ["measured"]}, "weight": 70},
                ],
            }
            score = grade_answer(task, answer, oracle)
            self.assertEqual(30.0, score["score"])
            self.assertEqual([1.0, 0.0], [row["credit_fraction"] for row in score["checks"]])

    def test_mapping_credit_denominator_is_the_required_record_set(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            task = self._task(root)
            answer = {
                "schema_version": "3.0", "task_id": "v07-test",
                "artifact": {
                    "decision": "repair", "sequence": ["op"], "estimate": 1.2,
                    "class_map": {"r1": "circuit", "r2": "circuit"},
                },
                "claim_boundary": "Supplied evidence only.", "confidence": 0.7,
            }
            oracle = {
                "schema_version": "1.0", "task_id": "v07-test", "family_id": "fam",
                "checks": [{
                    "id": "map", "path": "artifact.class_map", "kind": "mapping_credit",
                    "expected": {"r1": "circuit", "r2": "infra"}, "weight": 100,
                }],
            }
            self.assertEqual(50.0, grade_answer(task, answer, oracle)["score"])

    def test_frozen_knowledge_retrieval_is_deterministic_and_answer_free(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            task = self._task(root)
            corpus_path = root / "kg.json"
            corpus_path.write_text(json.dumps({"schema_version": "1.0", "entries": [
                {"id": "op", "title": "Operating point recovery", "text": "Recover headroom before STB.",
                 "tags": ["headroom", "stb"], "source_class": "clean_room"},
                {"id": "noise", "title": "Noise", "text": "Integrate input referred noise.",
                 "tags": ["noise"], "source_class": "clean_room"},
            ]}))
            corpus = load_knowledge_corpus(corpus_path)
            self.assertEqual(retrieve(corpus, "headroom stb", 1), retrieve(corpus, "headroom stb", 1))
            result = materialize_retrieval(task, corpus_path, root / "snapshot", 1)
            self.assertEqual("op", result["entries"][0]["id"])

    def test_kg_comparison_counts_model_format_failure_as_zero(self):
        base_row = {
            "task_id": "v07-test", "rollout": 0, "seed": 9,
            "task_manifest_sha256": "task", "answer_contract_sha256": "answer",
            "task_contract_sha256": "contract", "prompt_sha256": "prompt",
            "input_files_sha256": {"case.json": "case"}, "oracle_sha256": "oracle",
            "budget": {"timeout_seconds": 60, "max_tool_calls": 0},
            "web_search_policy": "forbidden",
            "requested_model_parameters": {"reasoning_mode": "disabled"},
            "knowledge_effect_expectation": "benefit_expected",
            "score": 80.0, "status": "ok", "terminal_tokens": 100,
            "wall_seconds": 4.0, "knowledge_context": None,
        }
        current_row = dict(base_row)
        current_row.update({
            "score": None, "status": "format_fail", "terminal_tokens": 120,
            "wall_seconds": 6.5,
            "knowledge_context": {
                "metrics": {"recall_at_k": 0.75, "precision_at_k": 0.5},
            },
        })
        result = compare_treatments([
            {"model_id": "m", "mode": "direct_reasoning",
             "requested_model_parameters": {"reasoning_mode": "disabled"}, "rows": [base_row]},
            {"model_id": "m", "mode": "knowledge_assisted",
             "requested_model_parameters": {"reasoning_mode": "disabled"}, "rows": [current_row]},
        ])
        paired = result["paired_deltas"]["knowledge_assisted"]
        self.assertEqual(1, paired["score_pair_count"])
        self.assertEqual(-80.0, paired["mean_score_delta"])
        self.assertEqual(1.0, paired["harm_rate"])
        self.assertEqual(20.0, paired["mean_terminal_token_delta"])
        self.assertEqual(2.5, paired["mean_wall_seconds_delta"])
        self.assertEqual(0.75, paired["mean_retrieval_recall_at_k"])
        self.assertEqual(0.5, paired["mean_retrieval_precision_at_k"])

    def test_policy_failure_is_zero_even_if_an_answer_was_graded(self):
        base_row = {
            "task_id": "v07-test", "rollout": 0, "seed": 9,
            "task_manifest_sha256": "task", "answer_contract_sha256": "answer",
            "task_contract_sha256": "contract", "prompt_sha256": "prompt",
            "input_files_sha256": {"case.json": "case"}, "oracle_sha256": "oracle",
            "budget": {"timeout_seconds": 60, "max_tool_calls": 0},
            "web_search_policy": "forbidden",
            "requested_model_parameters": {"reasoning_mode": "disabled"},
            "knowledge_effect_expectation": "override_resistant",
            "score": 80.0, "status": "ok", "terminal_tokens": 100,
        }
        violated = dict(base_row)
        violated.update({"status": "policy_fail", "score": 100.0})
        result = compare_treatments([
            {"model_id": "m", "mode": "direct_reasoning",
             "requested_model_parameters": base_row["requested_model_parameters"], "rows": [base_row]},
            {"model_id": "m", "mode": "knowledge_assisted",
             "requested_model_parameters": base_row["requested_model_parameters"], "rows": [violated]},
        ])
        self.assertEqual(
            -80.0, result["paired_deltas"]["knowledge_assisted"]["mean_score_delta"]
        )

    def test_kg_comparison_rejects_case_hash_mismatch(self):
        row = {
            "task_id": "v07-test", "rollout": 0, "seed": 9,
            "task_manifest_sha256": "task", "task_contract_sha256": "contract",
            "prompt_sha256": "prompt", "input_files_sha256": {"case.json": "case-a"},
            "answer_contract_sha256": "answer", "oracle_sha256": "oracle",
            "budget": {"timeout_seconds": 60, "max_tool_calls": 0},
            "web_search_policy": "forbidden",
            "requested_model_parameters": {"reasoning_mode": "disabled"},
            "knowledge_effect_expectation": "benefit_expected",
            "score": 80.0, "status": "ok", "terminal_tokens": 100,
        }
        changed = dict(row)
        changed["input_files_sha256"] = {"case.json": "case-b"}
        result = compare_treatments([
            {"model_id": "m", "mode": "direct_reasoning",
             "requested_model_parameters": row["requested_model_parameters"], "rows": [row]},
            {"model_id": "m", "mode": "knowledge_assisted",
             "requested_model_parameters": row["requested_model_parameters"], "rows": [changed]},
        ])
        self.assertFalse(result["passed"])
        self.assertIn("CONTROL_MISMATCH", {item["code"] for item in result["violations"]})

    def test_kg_comparison_rejects_unresolved_infrastructure(self):
        row = {
            "task_id": "v07-test", "rollout": 0, "seed": 9,
            "task_manifest_sha256": "task", "task_contract_sha256": "contract",
            "prompt_sha256": "prompt", "input_files_sha256": {"case.json": "case"},
            "answer_contract_sha256": "answer", "oracle_sha256": "oracle",
            "budget": {"timeout_seconds": 60, "max_tool_calls": 0},
            "web_search_policy": "forbidden",
            "requested_model_parameters": {"reasoning_mode": "disabled"},
            "knowledge_effect_expectation": "benefit_expected",
            "score": None, "status": "provider_timeout", "terminal_tokens": None,
        }
        result = compare_treatments([
            {"model_id": "m", "mode": "direct_reasoning", "capability_complete": False,
             "requested_model_parameters": row["requested_model_parameters"], "rows": [row]},
            {"model_id": "m", "mode": "knowledge_assisted", "capability_complete": False,
             "requested_model_parameters": row["requested_model_parameters"], "rows": [row]},
        ])
        self.assertFalse(result["passed"])
        self.assertIn("UNRESOLVED_INFRASTRUCTURE", {
            item["code"] for item in result["violations"]
        })

    def test_experiment_converts_wrong_answer_task_id_to_single_format_failure(self):
        with TemporaryDirectory() as temporary:
            base = Path(temporary)
            tasks = base / "tasks"
            task_root = tasks / "task-a"
            task_root.mkdir(parents=True)
            task = self._task(task_root)
            task.data["task_id"] = "task-a"
            task.data["family_id"] = "task-a"
            (task_root / "task.json").write_text(json.dumps(task.data))
            oracles = base / "oracles"
            oracles.mkdir()
            (oracles / "task-a.oracle.json").write_text(json.dumps({
                "schema_version": "1.0", "task_id": "task-a", "family_id": "task-a",
                "checks": [{"id": "d", "path": "artifact.decision", "kind": "exact",
                            "expected": "repair", "weight": 100}],
            }))

            def fake_run(task, run_dir, command, mode, context, timeout):
                app = run_dir / "app"
                app.mkdir(parents=True)
                (app / "answer.json").write_text(json.dumps({
                    "schema_version": "3.0", "task_id": "task-typo",
                    "artifact": {"decision": "repair"},
                    "claim_boundary": "Supplied evidence only.", "confidence": 0.5,
                }))
                return {"status": "ok", "answer_present": True, "duration_seconds": 1.0}

            with mock.patch("evoldo_bench.experiment.run_agent_command", side_effect=fake_run):
                manifest = run_experiment(
                    tasks, oracles, base / "output", CommandAgentAdapter(["unused"]),
                    "model", "direct_reasoning", rollouts=1,
                )
            self.assertEqual("format_fail", manifest["rows"][0]["status"])
            self.assertIsNone(manifest["rows"][0]["score"])
            self.assertEqual(1, len(manifest["rows"]))


if __name__ == "__main__":
    unittest.main()
