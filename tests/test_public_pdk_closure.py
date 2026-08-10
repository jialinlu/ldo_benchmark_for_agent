from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import unittest

from evoldo_bench.public_pdk import (
    DEFAULT_TRACK_ROOT,
    load_closure_registry,
    parse_measurements,
    run_closure_task,
    scan_dut_policy,
)


class PublicPdkClosureTests(unittest.TestCase):
    def test_closure_tasks_have_separate_task_examples_layout(self):
        registry = load_closure_registry(DEFAULT_TRACK_ROOT)
        for item in registry["tasks"]:
            root = DEFAULT_TRACK_ROOT / "tasks" / item["task_id"]
            for relative in (
                "task.toml", "instruction.md", "environment/Dockerfile",
                "environment/starter/circuit.spi", "tests/Dockerfile", "tests/test.sh",
                "tests/verify.py", "solution/circuit.spi", "solution/solve.sh",
                "package_manifest.json",
            ):
                self.assertTrue((root / relative).is_file(), "%s: %s" % (item["task_id"], relative))
            self.assertIn('schema_version = "1.3"', (root / "task.toml").read_text())

    def test_registry_has_six_complete_real_tasks(self):
        registry = load_closure_registry()
        self.assertEqual(6, len(registry["tasks"]))
        for entry in registry["tasks"]:
            task = json.loads((DEFAULT_TRACK_ROOT / entry["task_file"]).read_text())
            self.assertTrue(task["scenarios"])
            self.assertTrue((DEFAULT_TRACK_ROOT / "tasks" / task["task_id"] / task["starter_candidate"]).is_file())
            for scenario in task["scenarios"]:
                bench = DEFAULT_TRACK_ROOT / "tasks" / task["task_id"] / scenario["bench_template"]
                self.assertTrue(bench.is_file())
                self.assertTrue(scenario["limits"])

    def test_policy_rejects_ideal_source_and_forced_state_inside_dut(self):
        with TemporaryDirectory() as temporary:
            candidate = Path(temporary) / "bad.sp"
            candidate.write_text(
                ".subckt bad a b\nVBIAS a b 1\n.nodeset v(a)=1\n.ends bad\n"
                "VTEST in 0 1.8\n",
                encoding="utf-8",
            )
            report = scan_dut_policy(candidate)
            self.assertEqual("FAIL", report["status"])
            self.assertEqual(
                {"FORBIDDEN_IDEAL_DEVICE", "FORCED_INITIAL_STATE", "TOP_LEVEL_CANDIDATE_CONTENT"},
                {item["code"] for item in report["violations"]},
            )

    def test_reference_candidate_passes_source_policy(self):
        candidate = DEFAULT_TRACK_ROOT / "dev_reference" / "sky130_reference" / "ldo.sp"
        self.assertEqual("PASS", scan_dut_policy(candidate)["status"])

    def test_missing_model_is_structured_infrastructure_failure(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = run_closure_task("sky130_ldo_operating_point", root, root / "run")
            self.assertEqual("INFRA_FAIL", result["status"])
            self.assertEqual("model_entry_unavailable", result["reason"])

    def test_measurement_parser_and_limit_runner(self):
        self.assertEqual({"vout": 1.48, "iq": 3.2e-5}, parse_measurements("vout = 1.48\niq = 3.2e-05\n"))
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            pdk = root / "sky130_pdk" / "libs.tech" / "ngspice"
            pdk.mkdir(parents=True)
            (pdk / "sky130.lib.spice").write_text("* fixture only\n")
            track = root / "track"
            shutil.copytree(DEFAULT_TRACK_ROOT, track)
            manifest = json.loads((track / "public_pdk_manifest.json").read_text())
            manifest["providers"]["sky130"]["entry_sha256"] = hashlib.sha256(b"* fixture only\n").hexdigest()
            (track / "public_pdk_manifest.json").write_text(json.dumps(manifest))
            fake = root / "fake-ngspice"
            fake.write_text(
                "#!/bin/sh\n"
                "while [ \"$1\" != \"-o\" ]; do shift; done\n"
                "shift\n"
                "cat > \"$1\" <<'EOF'\n"
                "vout_final = 1.48\n"
                "vfb_final = 0.986\n"
                "supply_current = 1.032e-3\n"
                "quiescent_current = 3.2e-5\n"
                "EOF\n",
                encoding="utf-8",
            )
            os.chmod(fake, 0o755)
            result = run_closure_task(
                "sky130_ldo_operating_point", root, root / "run",
                candidate=DEFAULT_TRACK_ROOT / "dev_reference" / "sky130_reference" / "ldo.sp",
                track_root=track,
                ngspice=str(fake),
            )
            self.assertTrue(result["passed"])
            self.assertEqual("PASS", result["status"])


if __name__ == "__main__":
    unittest.main()
