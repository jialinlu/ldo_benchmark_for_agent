from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

from evoldo_bench.adapters import CommandAgentAdapter
from evoldo_bench.contracts import Task, validate_task
from evoldo_bench.errors import ContractError, PolicyError
from evoldo_bench.external_kg import (
    freeze_external_retrievals,
    import_external_retrieval_freeze,
    load_kg_snapshot_manifest,
    load_mcp_kg_config,
    validate_external_retrieval,
)
from evoldo_bench.knowledge import task_query
from evoldo_bench.experiment import run_experiment
from evoldo_bench.utils import load_json, sha256_file, sha256_text


HEX_A = "a" * 64
HEX_B = "b" * 64
HEX_C = "c" * 64
HEX_D = "d" * 64


class FakeMcpClient:
    calls = []

    def __init__(self, config):
        self.config = config

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return None

    def call_tool(self, name, arguments):
        self.__class__.calls.append((name, arguments))
        payload = {
            "schema_version": "1.0",
            "source_snapshot_id": "kg-20260820",
            "source_snapshot_sha256": HEX_A,
            "retrieval_method": self.config["retrieval_method"],
            "query": arguments["query"],
            "query_sha256": sha256_text(arguments["query"]),
            "top_k": arguments["limit"],
            "entries": [{
                "rank": 1,
                "stable_id": "concept-ldo-feedback",
                "title": " LDO feedback polarity ",
                "text": "A PMOS pass element contributes an inversion in the loop.",
                "tags": ["ldo", "feedback"],
                "source_class": "textbook",
                "source_name": "Analog IC Design",
                "source_uri": None,
                "retrieval_score": 12.5,
                "updated_at": None,
                "confidence": 0.9,
                "provenance": {"validation_status": "reviewed"},
            }],
        }
        return {"content": [{"type": "text", "text": json.dumps(payload)}], "isError": False}


class FlakyMcpClient(FakeMcpClient):
    attempts = 0

    def call_tool(self, name, arguments):
        self.__class__.attempts += 1
        if self.__class__.attempts == 1:
            raise TimeoutError("simulated transient timeout")
        return super().call_tool(name, arguments)


class ExternalKGTests(unittest.TestCase):
    def _task(self, root: Path) -> Task:
        contract = {
            "schema_version": "3.0", "task_id": "v07-test", "family_id": "fam",
            "lineage_id": "line", "split": "dev", "variant": "canonical",
            "suite": "diagnosis", "level": "L2", "capabilities": ["psrr", "measurement"],
            "title": "Repair a misleading PSRR measurement", "language": "en",
            "prompt_file": "instruction.md", "input_files": ["case.json", "answer_template.json"],
            "answer_template_file": "answer_template.json",
            "eligible_modes": ["direct_reasoning", "knowledge_assisted"],
            "budget": {"timeout_seconds": 60, "max_tool_calls": 0},
            "network_policy": {"model_web_search": "forbidden", "external_network": "provider_control_plane_only"},
            "tool_policy": {"allowed_tools": [], "forbidden_tools": ["web_search", "browser", "remote_fetch"]},
            "benchmark_version": "0.7.0", "evaluation_role": "calibration",
            "deployment_tier": "T1_local_advice", "knowledge_effect_expectation": "benefit_expected",
        }
        (root / "instruction.md").write_text("Do not trust a changed measurement contract.")
        (root / "answer_template.json").write_text('{"artifact":{"answer":"CONTROLLED"}}')
        (root / "case.json").write_text(json.dumps({
            "scenario": "A PSRR result changed after a testbench edit.",
            "catalogs": {"answers": ["secret-looking-controlled-option"]},
            "answer_contract": {"fields": {"decision": {"type": "string"}}},
        }))
        return Task(root, validate_task(contract, root))

    def _config(self, root: Path, **updates):
        value = {
            "schema_version": "1.0",
            "transport": "sse",
            "endpoint": "http://127.0.0.1:8702/sse",
            "tool_name": "benchmark_retrieve",
            "retrieval_method": "lucene_fulltext",
            "query_profile": "title_capabilities_scenario_v1",
        }
        value.update(updates)
        path = root / "mcp.json"
        path.write_text(json.dumps(value))
        return path

    def _snapshot(self, root: Path, **updates):
        value = {
            "schema_version": "1.0",
            "snapshot_id": "kg-20260820",
            "snapshot_sha256": HEX_A,
            "created_at": "2026-08-20T00:00:00+00:00",
            "service_code": {"revision": "commit", "archive_sha256": HEX_B, "dirty": False},
            "corpus": {"node_count": 681373, "relationship_count": 500000},
            "supported_retrieval_methods": ["lucene_fulltext"],
            "artifacts": [
                {"role": "neo4j_dump", "name": "neo4j.dump", "sha256": HEX_A, "size_bytes": 100},
                {"role": "service_source", "name": "service.tar", "sha256": HEX_B, "size_bytes": 100},
            ],
            "qualification": {
                "dump_restored_and_count_verified": True,
                "read_only_enforced": True,
                "contamination_audit_passed": True,
                "determinism_verified": True,
            },
            "contamination_report_sha256": HEX_B,
        }
        value.update(updates)
        path = root / "snapshot.json"
        path.write_text(json.dumps(value))
        return path

    def test_compact_query_excludes_answer_contract_and_catalogs(self):
        with TemporaryDirectory() as temporary:
            task = self._task(Path(temporary))
            query = task_query(task, "title_capabilities_scenario_v1")
            self.assertIn("PSRR result changed", query)
            self.assertIn("psrr measurement", query)
            self.assertNotIn("secret-looking-controlled-option", query)
            self.assertNotIn("answer_contract", query)

    def test_config_rejects_credentials_and_unapproved_tool(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(PolicyError):
                load_mcp_kg_config(self._config(root, endpoint="http://user:pass@127.0.0.1/sse"))
            with self.assertRaises(PolicyError):
                load_mcp_kg_config(self._config(root, tool_name="search_concepts"))
            with self.assertRaises(PolicyError):
                load_mcp_kg_config(self._config(
                    root, **{"api" + "_key": "not-a-real-credential"},
                ))
            with self.assertRaises(ContractError):
                load_mcp_kg_config(self._config(root, query_profile="full_public_task_v1"))

    def test_snapshot_requires_clean_qualified_restorable_artifacts(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            good = load_kg_snapshot_manifest(self._snapshot(root), "lucene_fulltext")
            self.assertEqual(681373, good["corpus"]["node_count"])
            bad_code = {
                "revision": "commit", "archive_sha256": HEX_B, "dirty": True,
            }
            with self.assertRaises(PolicyError):
                load_kg_snapshot_manifest(self._snapshot(root, service_code=bad_code), "lucene_fulltext")
            artifacts = [
                {"role": "neo4j_dump", "name": "neo4j.dump", "sha256": HEX_A, "size_bytes": 100},
                {"role": "service_source", "name": "service.tar", "sha256": HEX_D, "size_bytes": 100},
            ]
            with self.assertRaises(PolicyError):
                load_kg_snapshot_manifest(self._snapshot(root, artifacts=artifacts), "lucene_fulltext")

    def test_response_is_bound_to_query_snapshot_and_strict_entry_schema(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = load_mcp_kg_config(self._config(root))
            snapshot = load_kg_snapshot_manifest(self._snapshot(root), "lucene_fulltext")
            query = "LDO feedback"
            payload = json.loads(FakeMcpClient(config).call_tool("benchmark_retrieve", {
                "query": query, "method": "lucene_fulltext", "limit": 4,
            })["content"][0]["text"])
            normalized = validate_external_retrieval(payload, query, 4, config, snapshot)
            self.assertEqual("concept-ldo-feedback", normalized["entries"][0]["id"])
            self.assertEqual("LDO feedback polarity", normalized["entries"][0]["title"])
            payload["source_snapshot_sha256"] = HEX_B
            with self.assertRaises(PolicyError):
                validate_external_retrieval(payload, query, 4, config, snapshot)

    def test_freeze_writes_raw_and_normalized_audit_artifacts(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            task_root = root / "task"
            task_root.mkdir()
            task = self._task(task_root)
            config_path = self._config(root)
            snapshot_path = self._snapshot(root)
            output = root / "frozen"
            FakeMcpClient.calls = []
            manifest = freeze_external_retrievals(
                [task], config_path, snapshot_path, output, top_k=4,
                client_class=FakeMcpClient,
            )
            self.assertEqual(1, manifest["task_count"])
            self.assertEqual(1, len(FakeMcpClient.calls))
            retrieval = load_json(output / "tasks" / "v07-test" / "kg_retrieval.json")
            self.assertEqual("external_mcp_sse", retrieval["retrieval_backend"])
            self.assertNotIn("retrieval_provenance", retrieval)
            self.assertNotIn("materialization_seconds", retrieval)
            self.assertTrue((output / "tasks" / "v07-test" / "kg_mcp_raw_response.json").is_file())
            self.assertFalse(manifest["rows"][0]["metrics"]["relevance_manifest_available"])

    def test_preflight_retries_only_transient_retrieval_failure(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            task_root = root / "task"
            task_root.mkdir()
            task = self._task(task_root)
            config = self._config(
                root, max_retrieval_attempts=2, retry_backoff_seconds=1,
            )
            FlakyMcpClient.attempts = 0
            with mock.patch("evoldo_bench.external_kg.time.sleep") as sleep:
                manifest = freeze_external_retrievals(
                    [task], config, self._snapshot(root), root / "frozen",
                    client_class=FlakyMcpClient,
                )
            self.assertEqual(2, manifest["rows"][0]["retrieval_attempts"])
            self.assertEqual(["TimeoutError"], manifest["rows"][0]["transient_failure_types"])
            sleep.assert_called_once_with(1)

    def test_experiment_prefreezes_once_and_exposes_only_normalized_context(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            tasks_root = root / "tasks"
            task_root = tasks_root / "v07-test"
            task_root.mkdir(parents=True)
            task = self._task(task_root)
            (task_root / "task.json").write_text(json.dumps(task.data))
            oracles = root / "oracles"
            oracles.mkdir()
            (oracles / "v07-test.oracle.json").write_text(json.dumps({
                "schema_version": "1.0", "task_id": "v07-test", "family_id": "fam",
                "checks": [{
                    "id": "decision", "path": "artifact.decision", "kind": "exact",
                    "expected": "repair", "weight": 100,
                }],
            }))
            config_path = self._config(root)
            snapshot_path = self._snapshot(root)
            real_freeze = freeze_external_retrievals
            seen_contexts = []

            def freeze_with_fake(*args, **kwargs):
                kwargs["client_class"] = FakeMcpClient
                return real_freeze(*args, **kwargs)

            def fake_run(task, run_dir, command, mode, context, timeout):
                self.assertEqual("knowledge_assisted", mode)
                self.assertEqual(["kg_retrieval.json"], sorted(path.name for path in context.iterdir()))
                seen_contexts.append((context / "kg_retrieval.json").read_bytes())
                app = run_dir / "app"
                app.mkdir(parents=True, exist_ok=True)
                (app / "answer.json").write_text(json.dumps({
                    "schema_version": "3.0", "task_id": "v07-test",
                    "artifact": {"decision": "repair"},
                    "claim_boundary": "Supplied evidence only.", "confidence": 0.8,
                }))
                return {"status": "ok", "answer_present": True, "duration_seconds": 0.1}

            FakeMcpClient.calls = []
            with mock.patch(
                "evoldo_bench.experiment.freeze_external_retrievals", side_effect=freeze_with_fake,
            ), mock.patch("evoldo_bench.experiment.run_agent_command", side_effect=fake_run):
                manifest = run_experiment(
                    tasks_root, oracles, root / "experiment",
                    CommandAgentAdapter(["unused"]), "model", "knowledge_assisted",
                    rollouts=2, knowledge_mcp_config=config_path,
                    knowledge_snapshot_manifest=snapshot_path,
                )
            self.assertEqual(1, len(FakeMcpClient.calls))
            self.assertEqual(2, len(seen_contexts))
            self.assertEqual(seen_contexts[0], seen_contexts[1])
            self.assertEqual("external_mcp_sse", manifest["knowledge_freeze"]["backend"])
            self.assertTrue(all(row["knowledge_context"]["backend"] == "external_mcp_sse" for row in manifest["rows"]))

    def test_reviewed_preflight_import_is_hash_and_task_bound(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            task_root = root / "task"
            task_root.mkdir()
            task = self._task(task_root)
            frozen = root / "preflight"
            freeze_external_retrievals(
                [task], self._config(root), self._snapshot(root), frozen,
                client_class=FakeMcpClient,
            )
            imported = import_external_retrieval_freeze([task], frozen, root / "imported")
            self.assertTrue(imported["imported_from_preflight"])
            retrieval_path = frozen / "tasks" / task.task_id / "kg_retrieval.json"
            retrieval_path.write_text(retrieval_path.read_text() + "\n")
            with self.assertRaisesRegex(PolicyError, "retrieval changed"):
                import_external_retrieval_freeze([task], frozen, root / "tampered")

    def test_formal_import_recomputes_bound_relevance_metrics(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            task_root = root / "task"
            task_root.mkdir()
            task = self._task(task_root)
            relevance = root / "relevance.json"
            relevance.write_text(json.dumps({
                "schema_version": "1.0",
                "source_snapshot_sha256": HEX_A,
                "tasks": {task.task_id: ["concept-ldo-feedback"]},
            }))
            frozen = root / "preflight"
            freeze_external_retrievals(
                [task], self._config(root), self._snapshot(root), frozen,
                relevance_manifest_path=relevance, client_class=FakeMcpClient,
            )
            imported = import_external_retrieval_freeze(
                [task], frozen, root / "imported", require_relevance=True,
            )
            self.assertEqual(1.0, imported["rows"][0]["metrics"]["recall_at_k"])

            manifest_path = frozen / "knowledge_freeze_manifest.json"
            manifest = load_json(manifest_path)
            manifest["rows"][0]["metrics"]["precision_at_k"] = 0.5
            manifest_path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(PolicyError, "metrics changed"):
                import_external_retrieval_freeze(
                    [task], frozen, root / "tampered", require_relevance=True,
                )

    def test_import_rederives_normalized_context_from_raw_mcp_response(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            task_root = root / "task"
            task_root.mkdir()
            task = self._task(task_root)
            frozen = root / "preflight"
            freeze_external_retrievals(
                [task], self._config(root), self._snapshot(root), frozen,
                client_class=FakeMcpClient,
            )
            retrieval_path = frozen / "tasks" / task.task_id / "kg_retrieval.json"
            retrieval = load_json(retrieval_path)
            retrieval["entries"][0]["text"] = "Content inserted after preflight."
            retrieval_path.write_text(json.dumps(retrieval))
            manifest_path = frozen / "knowledge_freeze_manifest.json"
            manifest = load_json(manifest_path)
            manifest["rows"][0]["retrieval_sha256"] = sha256_file(retrieval_path)
            manifest_path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(PolicyError, "does not match its raw response"):
                import_external_retrieval_freeze([task], frozen, root / "tampered")


if __name__ == "__main__":
    unittest.main()
