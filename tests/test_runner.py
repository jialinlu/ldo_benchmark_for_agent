from pathlib import Path
from tempfile import TemporaryDirectory
import sys
import unittest

from evoldo_bench.discovery import discover_tasks
from evoldo_bench.runner import run_agent_command

ROOT = Path(__file__).resolve().parents[1]
TASKS = ROOT / "benchmarks" / "ldo_original" / "dev" / "tasks"


class RunnerTests(unittest.TestCase):
    def test_runner_records_answer_and_logs(self):
        task = discover_tasks(TASKS)[0]
        agent_source = '''
import json, os
from pathlib import Path
root = Path(os.environ["EVOLDO_TASK_DIR"])
answer = json.loads((root / "answer_template.json").read_text())
answer.update({
  "conclusion": "insufficient_evidence",
  "analysis_regime": "connectivity",
  "mechanism": "smoke test",
  "claim_boundary": "smoke test only",
  "confidence": 0.1
})
(root / "answer.json").write_text(json.dumps(answer))
print("agent smoke completed")
'''
        with TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            agent = temporary_path / "agent.py"
            agent.write_text(agent_source, encoding="utf-8")
            run_dir = temporary_path / "run"
            record = run_agent_command(task, run_dir, [sys.executable, str(agent)])
            self.assertEqual("ok", record["status"])
            self.assertTrue(record["answer_present"])
            self.assertTrue((run_dir / "app" / "answer.json").is_file())
            self.assertIn("agent smoke completed", (run_dir / "stdout.log").read_text())


if __name__ == "__main__":
    unittest.main()
