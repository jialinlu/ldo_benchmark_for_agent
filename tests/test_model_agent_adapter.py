from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from evoldo_bench.errors import ContractError


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("model_agent_adapter", ROOT / "tools" / "model_agent_adapter.py")
assert SPEC and SPEC.loader
ADAPTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ADAPTER)
MERGE_SPEC = importlib.util.spec_from_file_location("merge_experiment_shards", ROOT / "tools" / "merge_experiment_shards.py")
assert MERGE_SPEC and MERGE_SPEC.loader
MERGER = importlib.util.module_from_spec(MERGE_SPEC)
MERGE_SPEC.loader.exec_module(MERGER)


class ModelAgentAdapterTests(unittest.TestCase):
    def test_prompt_accepts_v06_demo_bundle(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "task_contract.json").write_text(json.dumps({
                "prompt_file": "instruction.md", "answer_template_file": "answer_template.json",
                "input_files": ["case.json", "answer_template.json"]
            }))
            (root / "instruction.md").write_text("instruction")
            (root / "answer_template.json").write_text("{}")
            (root / "case.json").write_text("{\"case\": true}")
            prompt = ADAPTER._prompt(root)
            self.assertIn("instruction", prompt)
            self.assertIn('"case": true', prompt)
            self.assertEqual(prompt.count("===== answer_template.json ====="), 1)

    def test_extract_json_accepts_object_and_rejects_commentary(self):
        self.assertEqual({"x": 1}, ADAPTER._extract_json('{"x": 1}'))
        with self.assertRaises(ValueError):
            ADAPTER._extract_json('answer: {"x": 1} trailing')

    def test_prompt_contains_only_declared_runtime_files(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "inputs").mkdir()
            (root / "solution").mkdir()
            (root / "task.json").write_text(json.dumps({
                "prompt_file": "prompt.md", "answer_template_file": "answer_template.json",
                "input_files": ["inputs/case.json"],
            }))
            (root / "prompt.md").write_text("instruction")
            (root / "answer_template.json").write_text("{}")
            (root / "inputs" / "case.json").write_text('{"case": true}')
            (root / "solution" / "answer.json").write_text('{"secret": true}')
            prompt = ADAPTER._prompt(root)
            self.assertIn("instruction", prompt)
            self.assertNotIn("secret", prompt)

    def test_codex_usage_normalization_avoids_cache_and_reasoning_double_count(self):
        telemetry = ADAPTER._telemetry_base("m", 1.0)
        ADAPTER._normalize_codex("m", {
            "input_tokens": 100, "cached_input_tokens": 60, "output_tokens": 30,
            "reasoning_output_tokens": 20, "cache_write_input_tokens": 0,
        }, telemetry)
        self.assertEqual(40, telemetry["token_breakdown"]["input"])
        self.assertEqual(10, telemetry["token_breakdown"]["output"])
        self.assertEqual(20, telemetry["token_breakdown"]["reasoning"])
        self.assertEqual("requested_only", telemetry["model_identity_status"])

    def test_claude_usage_sums_auxiliary_model_entries(self):
        telemetry = ADAPTER._telemetry_base("deepseek-reasoner", 1.0)
        raw = {
            "total_cost_usd": 0.3,
            "modelUsage": {
                "deepseek-reasoner": {"inputTokens": 10, "outputTokens": 5},
                "deepseek-v4-flash": {"inputTokens": 2, "outputTokens": 1},
            },
        }
        ADAPTER._normalize_claude("deepseek-reasoner", raw, "deepseek-reasoner,deepseek-v4-flash", telemetry)
        self.assertEqual(12, telemetry["token_breakdown"]["input"])
        self.assertEqual(6, telemetry["token_breakdown"]["output"])
        self.assertEqual(0.3, telemetry["provider_total_cost_usd"])
        self.assertEqual("attested", telemetry["model_identity_status"])

    def test_openai_compatible_parses_identity_and_token_details(self):
        payload = json.dumps({
            "id": "response-1",
            "model": "provider/model",
            "choices": [{"message": {"content": '{"answer": true}'}}],
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 40,
                "prompt_tokens_details": {"cached_tokens": 25},
                "completion_tokens_details": {"reasoning_tokens": 30},
            },
        })
        final, raw, reported = ADAPTER._openai_compatible(payload)
        self.assertEqual('{"answer": true}', final)
        telemetry = ADAPTER._telemetry_base("provider/model", 1.0)
        ADAPTER._normalize_openai_compatible("provider/model", raw, reported, telemetry)
        self.assertEqual(75, telemetry["token_breakdown"]["input"])
        self.assertEqual(10, telemetry["token_breakdown"]["output"])
        self.assertEqual(30, telemetry["token_breakdown"]["reasoning"])
        self.assertEqual("attested", telemetry["model_identity_status"])
        self.assertEqual("partial", telemetry["token_measurement_status"])

    def test_container_boundary_mounts_only_the_task_read_only(self):
        command = ADAPTER._docker_base(Path("/isolated/task"))
        rendered = " ".join(command)
        self.assertIn("type=bind,src=/isolated/task,dst=/task,readonly", rendered)
        self.assertIn("--read-only", command)
        self.assertIn("--cap-drop ALL", rendered)
        self.assertNotIn("dst=/workspace", rendered)
        self.assertNotIn("dst=/repo", rendered)

    def test_shard_merge_rejects_duplicates_and_preserves_artifact_paths(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            shards = []
            for index, task_id in enumerate(("task-a", "task-b")):
                shard = root / ("shard-%02d" % index)
                run = shard / "runs" / task_id / "rollout-000"
                run.mkdir(parents=True)
                (run / "telemetry.json").write_text("{}")
                (run / "score.json").write_text("{}")
                manifest = {
                    "schema_version": "1.0", "model_id": "m", "mode": "direct_reasoning",
                    "rollouts_per_task": 1, "base_seed": 7, "seed_semantics": "test",
                    "pairing_modes": ["direct_reasoning"], "context_snapshot": {"included": False},
                    "task_count": 1, "run_count": 1,
                    "rows": [{
                        "task_id": task_id, "rollout": 0, "seed": 7,
                        "telemetry_file": "runs/%s/rollout-000/telemetry.json" % task_id,
                        "score_file": "runs/%s/rollout-000/score.json" % task_id,
                    }],
                }
                (shard / "experiment_manifest.json").write_text(json.dumps(manifest))
                shards.append(shard)
            merged = MERGER.merge_shards(root, shards)
            self.assertEqual(2, merged["task_count"])
            self.assertTrue(merged["rows"][0]["telemetry_file"].startswith("shard-00/"))
            with self.assertRaises(ContractError):
                MERGER.merge_shards(root, [shards[0], shards[0]])


if __name__ == "__main__":
    unittest.main()
