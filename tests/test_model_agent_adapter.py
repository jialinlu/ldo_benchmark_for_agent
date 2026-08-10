from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("model_agent_adapter", ROOT / "tools" / "model_agent_adapter.py")
assert SPEC and SPEC.loader
ADAPTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ADAPTER)


class ModelAgentAdapterTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
