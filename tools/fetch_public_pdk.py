#!/usr/bin/env python3
"""Fetch pinned public model trees without vendoring them into this repository."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "benchmarks" / "ldo_design_closure" / "public_pdk_manifest.json"


def run(command: List[str], cwd: Optional[Path] = None) -> str:
    return subprocess.check_output(command, cwd=str(cwd) if cwd else None, text=True).strip()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=("sky130", "asap7", "all"), default="sky130")
    parser.add_argument("--output", type=Path, default=ROOT / ".runtime" / "public_pdks" / "opensource-analog-circuits")
    args = parser.parse_args()
    manifest: Dict[str, Any] = json.loads(MANIFEST.read_text(encoding="utf-8"))
    providers = manifest["providers"]
    selected = list(providers) if args.provider == "all" else [args.provider]
    required_paths = sorted({path for name in selected for path in providers[name]["required_paths"]})
    output = args.output.expanduser().resolve()
    if not output.exists():
        output.parent.mkdir(parents=True, exist_ok=True)
        run(["git", "clone", "--filter=blob:none", "--no-checkout", manifest["source_repository"], str(output)])
    if not (output / ".git").is_dir():
        parser.error("output exists but is not the expected Git checkout")
    remote = run(["git", "remote", "get-url", "origin"], output)
    expected_tail = "jialinlu/opensource-analog-circuits.git"
    if not remote.endswith(expected_tail):
        parser.error("existing checkout has an unexpected origin")
    run(["git", "fetch", "--depth=1", "origin", manifest["source_commit"]], output)
    # Manual sparse-checkout setup keeps the fetcher compatible with Git 2.23+ workers.
    run(["git", "config", "core.sparseCheckout", "true"], output)
    sparse_file = output / ".git" / "info" / "sparse-checkout"
    sparse_file.parent.mkdir(parents=True, exist_ok=True)
    sparse_file.write_text("".join("/%s/\n" % path for path in required_paths), encoding="utf-8")
    run(["git", "checkout", "--detach", manifest["source_commit"]], output)
    if run(["git", "rev-parse", "HEAD"], output) != manifest["source_commit"]:
        parser.error("checkout revision verification failed")
    checks = []
    for name in selected:
        provider = providers[name]
        entry = output / provider["entry_file"]
        actual = sha256(entry)
        checks.append({"provider": name, "entry_file": provider["entry_file"], "sha256": actual, "passed": actual == provider["entry_sha256"]})
        if name == "asap7":
            osdi = output / provider["osdi_file"]
            actual_osdi = sha256(osdi)
            checks.append({"provider": name, "entry_file": provider["osdi_file"], "sha256": actual_osdi, "passed": actual_osdi == provider["osdi_sha256"]})
    result = {"schema_version": "1.0", "checkout": str(output), "revision": manifest["source_commit"], "checks": checks, "passed": all(item["passed"] for item in checks)}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
