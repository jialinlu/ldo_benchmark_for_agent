from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from evoldo_bench.bundle import audit_runtime_bundle, build_runtime_bundle
from evoldo_bench.contamination import audit_task_collection
from evoldo_bench.discovery import discover_tasks
from evoldo_bench.errors import PolicyError

ROOT = Path(__file__).resolve().parents[1]
TASKS = ROOT / "benchmarks" / "ldo_original" / "dev" / "tasks"
ORACLES = ROOT / "benchmarks" / "ldo_original" / "dev_reference" / "oracles"


class BundleAndAuditTests(unittest.TestCase):
    def test_bundle_excludes_oracle_and_reference_material(self):
        task = discover_tasks(TASKS)[0]
        with TemporaryDirectory() as temporary:
            output = Path(temporary) / "app"
            manifest = build_runtime_bundle(task, output)
            self.assertFalse(manifest["oracle_included"])
            self.assertTrue(audit_runtime_bundle(output)["passed"])
            self.assertFalse(any("oracle" in path.name.lower() for path in output.rglob("*")))

    def test_collection_audit_passes(self):
        report = audit_task_collection(TASKS, ORACLES)
        self.assertTrue(report["passed"], report["violations"])
        self.assertEqual(36, report["task_count"])
        self.assertEqual(12, report["family_count"])

    def test_context_symlink_is_rejected(self):
        task = discover_tasks(TASKS)[0]
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            context = root / "context"
            context.mkdir()
            outside = root / "outside.txt"
            outside.write_text("private", encoding="utf-8")
            try:
                (context / "leak.txt").symlink_to(outside)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks are unavailable on this platform")
            with self.assertRaises(PolicyError):
                build_runtime_bundle(task, root / "app", context)


if __name__ == "__main__":
    unittest.main()
