#!/usr/bin/env python3
"""Generate task_examples/Harbor-style wrappers for EvoLDO development tasks.

The agent environment, verifier, and public reference solution are deliberately separate.  The
runtime bundle builder copies only declared starter material and never copies ``tests`` or
``solution``.  Sealed exams must replace the public verifier assets with an external private store.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, Dict


ROOT = Path(__file__).resolve().parents[1]
TASKS_ROOT = ROOT / "benchmarks" / "ldo_original" / "dev" / "tasks"
ORACLE_ROOT = ROOT / "benchmarks" / "ldo_original" / "dev_reference" / "oracles"
REASONING_REGISTRY = ROOT / "benchmarks" / "ldo_original" / "registry.jsonl"
CLOSURE_ROOT = ROOT / "benchmarks" / "ldo_design_closure"


ENVIRONMENT_DOCKERFILE = """FROM python:3.12.3-slim-bookworm

WORKDIR /app
COPY starter/ /app/
RUN find /app -name '.DS_Store' -delete
CMD ["bash"]
"""


TESTS_DOCKERFILE = """FROM python:3.12.3-slim-bookworm

WORKDIR /app
COPY verify.py expected.json /app/evoldo_tests/
COPY test.sh /tests/test.sh
RUN chmod +x /tests/test.sh
"""


TEST_SH = """#!/usr/bin/env sh
set -eu
mkdir -p /logs/verifier
if [ ! -s /app/answer.json ]; then
  printf '%s\n' '{"reward":0,"tests_total":8,"tests_passed":0,"partial":0.0,"outcome":"missing_answer"}' > /logs/verifier/reward.json
  exit 0
fi
python3 /app/evoldo_tests/verify.py
"""


VERIFY_PY = r'''#!/usr/bin/env python3
"""Self-contained public-development verifier for one structured reasoning task."""
import json
import os
from pathlib import Path

ANSWER = Path(os.environ.get("EVOLDO_ANSWER_PATH", "/app/answer.json"))
EXPECTED = Path(os.environ.get("EVOLDO_EXPECTED_PATH", "/app/evoldo_tests/expected.json"))
OUTPUT = Path(os.environ.get("EVOLDO_VERIFIER_OUTPUT", "/logs/verifier"))
REQUIRED = {
    "schema_version", "task_id", "conclusion", "analysis_regime", "held_fixed",
    "evidence_facts", "mechanism_tags", "recommended_actions", "mechanism",
    "claim_boundary", "confidence",
}


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    try:
        answer = json.loads(ANSWER.read_text())
        oracle = json.loads(EXPECTED.read_text())
        if not isinstance(answer, dict) or not REQUIRED.issubset(answer):
            raise ValueError("answer contract is incomplete")
        if not isinstance(answer["mechanism"], str) or not answer["mechanism"].strip():
            raise ValueError("mechanism is empty")
        if not isinstance(answer["claim_boundary"], str) or not answer["claim_boundary"].strip():
            raise ValueError("claim_boundary is empty")
        if not isinstance(answer["confidence"], (int, float)) or isinstance(answer["confidence"], bool) or not 0 <= answer["confidence"] <= 1:
            raise ValueError("confidence is outside [0, 1]")
    except Exception as exc:
        write(0.0, [], "invalid_answer: %s" % exc)
        return

    raw = 0.0
    critical = []
    results = []
    for check in oracle["checks"]:
        actual = answer.get(check["path"])
        kind = check["kind"]
        expected = check.get("expected")
        if kind == "exact":
            passed = actual == expected
        elif kind == "set_equals":
            passed = isinstance(actual, list) and set(actual) == set(expected) and len(actual) == len(set(actual))
        elif kind == "set_excludes":
            passed = isinstance(actual, list) and not set(actual).intersection(expected)
        else:
            passed = False
        if passed:
            raw += float(check["weight"])
        elif check.get("critical", False):
            critical.append(check["id"])
        results.append({"name": check["id"], "status": "passed" if passed else "failed"})
    score = min(raw, float(oracle.get("critical_failure_cap", 49.0))) if critical else raw
    write(score / 100.0, results, "ok", score=score, critical=critical)


def write(reward: float, results: list, outcome: str, score: float = 0.0, critical: list | None = None) -> None:
    passed = sum(result.get("status") == "passed" for result in results)
    total = len(results) or 8
    payload = {
        "reward": reward, "tests_total": total, "tests_passed": passed,
        "partial": reward, "score": score, "outcome": outcome,
        "critical_failed": critical or [],
    }
    (OUTPUT / "reward.json").write_text(json.dumps(payload) + "\n")
    (OUTPUT / "new-ctrf.json").write_text(json.dumps({
        "results": {"summary": {"tests": total, "passed": passed, "failed": total - passed}, "tests": results}
    }, indent=2) + "\n")


if __name__ == "__main__":
    main()
'''


SOLVE_SH = """#!/usr/bin/env sh
set -eu
install -m 0644 "${SOLUTION_DIR:-/solution}/answer.json" "${APP_DIR:-/app}/answer.json"
"""


CLOSURE_ENVIRONMENT_DOCKERFILE = """FROM python:3.12.3-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends ngspice ca-certificates \\
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY starter/ /app/
CMD ["bash"]
"""


CLOSURE_TEST_SH = """#!/usr/bin/env sh
set -eu
mkdir -p /logs/verifier
if [ ! -s /app/circuit.spi ]; then
  printf '%s\n' '{"reward":0,"tests_total":1,"tests_passed":0,"partial":0.0,"outcome":"missing_candidate"}' > /logs/verifier/reward.json
  exit 0
fi
PYTHONPATH=/app/evoldo_tests python3 /app/evoldo_tests/verify.py
"""


CLOSURE_VERIFY_PY = '''#!/usr/bin/env python3
import json
import os
from pathlib import Path

from evoldo_bench.public_pdk import run_closure_task


def main() -> None:
    task_id = os.environ["EVOLDO_CLOSURE_TASK_ID"]
    output = Path("/logs/verifier/evidence")
    result = run_closure_task(
        task_id,
        Path(os.environ.get("EVOLDO_PDK_ROOT", "/opt/sky130")),
        output,
        candidate=Path("/app/circuit.spi"),
        track_root=Path("/app/evoldo_tests/track"),
    )
    checks = [check for scenario in result.get("scenarios", []) for check in scenario.get("checks", [])]
    total = len(checks) or 1
    passed = sum(check.get("status") == "PASS" for check in checks)
    reward = passed / total if checks else float(bool(result.get("passed")))
    payload = {
        "reward": reward,
        "partial": reward,
        "tests_total": total,
        "tests_passed": passed if checks else int(bool(result.get("passed"))),
        "outcome": result.get("status", "UNKNOWN"),
        "task_id": task_id,
    }
    target = Path("/logs/verifier")
    target.mkdir(parents=True, exist_ok=True)
    (target / "reward.json").write_text(json.dumps(payload) + "\\n")
    (target / "result.json").write_text(json.dumps(result, indent=2) + "\\n")


if __name__ == "__main__":
    main()
'''


def _json(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _reference_answer(task_id: str, oracle: Dict[str, Any]) -> Dict[str, Any]:
    answer: Dict[str, Any] = {
        "schema_version": "1.0",
        "task_id": task_id,
        "conclusion": "",
        "analysis_regime": "",
        "held_fixed": [],
        "evidence_facts": [],
        "mechanism_tags": [],
        "recommended_actions": [],
        "mechanism": "Reference development explanation based only on supplied evidence.",
        "claim_boundary": "Limited to the supplied operating regime and held-fixed conditions.",
        "confidence": 0.95,
        "numeric_results": {},
    }
    for check in oracle["checks"]:
        path = check["path"]
        if "." in path:
            continue
        if check["kind"] in {"exact", "boolean", "numeric_close"}:
            answer[path] = check["expected"]
        elif check["kind"] in {"set_equals", "set_contains"}:
            answer[path] = list(check["expected"])
    return answer


def _task_toml(task: Dict[str, Any]) -> str:
    keywords = ", ".join(_toml_string(value) for value in ["analog", "ldo", task["suite"], task["variant"]])
    return f'''schema_version = "1.3"
artifacts = ["/app/answer.json"]

[task]
name = {_toml_string("evoldo-bench/" + task["task_id"])}
description = {_toml_string(task["title"])}
authors = [{{ name = "EvoLDO-Bench contributors" }}]
keywords = [{keywords}]

[metadata]
task_id = {_toml_string(task["task_id"])}
family_id = {_toml_string(task["family_id"])}
suite = {_toml_string(task["suite"])}
variant = {_toml_string(task["variant"])}
level = {_toml_string(task["level"])}
revision = 2
maturity = "public-development"

[verifier]
environment_mode = "separate"

[verifier.environment]
network_mode = "no-network"
build_timeout_sec = 300.0
cpus = 1
memory_mb = 1024
storage_mb = 1024

[environment]
network_mode = "no-network"
build_timeout_sec = 300.0
cpus = 1
memory_mb = 1024
storage_mb = 1024
'''


def _package_digest(task_dir: Path) -> str:
    rows = []
    for path in sorted(task_dir.rglob("*")):
        if path.is_file() and path.name != "package_manifest.json":
            rows.append("%s:%s" % (path.relative_to(task_dir).as_posix(), hashlib.sha256(path.read_bytes()).hexdigest()))
    return hashlib.sha256("\n".join(rows).encode()).hexdigest()


def package_reasoning_task(task_dir: Path, oracle_path: Path) -> str:
    task = json.loads((task_dir / "task.json").read_text())
    oracle = json.loads(oracle_path.read_text())
    for name in ("environment", "tests", "solution"):
        target = task_dir / name
        if target.exists():
            shutil.rmtree(target)
    (task_dir / "instruction.md").write_text((task_dir / task["prompt_file"]).read_text(), encoding="utf-8")
    (task_dir / "task.toml").write_text(_task_toml(task), encoding="utf-8")

    starter = task_dir / "environment" / "starter"
    starter.mkdir(parents=True)
    shutil.copy2(task_dir / "task.json", starter / "task.json")
    shutil.copy2(task_dir / task["answer_template_file"], starter / "answer_template.json")
    for value in task["input_files"]:
        source = task_dir / value
        destination = starter / value
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    (task_dir / "environment" / "Dockerfile").write_text(ENVIRONMENT_DOCKERFILE, encoding="utf-8")

    tests = task_dir / "tests"
    tests.mkdir()
    (tests / "Dockerfile").write_text(TESTS_DOCKERFILE, encoding="utf-8")
    (tests / "test.sh").write_text(TEST_SH, encoding="utf-8")
    (tests / "test.sh").chmod(0o755)
    (tests / "verify.py").write_text(VERIFY_PY, encoding="utf-8")
    (tests / "expected.json").write_text(_json(oracle), encoding="utf-8")

    solution = task_dir / "solution"
    solution.mkdir()
    (solution / "answer.json").write_text(_json(_reference_answer(task["task_id"], oracle)), encoding="utf-8")
    (solution / "solve.sh").write_text(SOLVE_SH, encoding="utf-8")
    (solution / "solve.sh").chmod(0o755)

    digest = _package_digest(task_dir)
    (task_dir / "package_manifest.json").write_text(_json({
        "schema_version": "1.0",
        "task_id": task["task_id"],
        "package_sha256": digest,
        "runtime_excludes": ["tests", "solution"],
        "public_development_solution": True,
    }), encoding="utf-8")
    return digest


def package_all_reasoning_tasks() -> Dict[str, str]:
    result = {}
    for task_dir in sorted(path.parent for path in TASKS_ROOT.glob("*/task.json")):
        task = json.loads((task_dir / "task.json").read_text())
        result[task["task_id"]] = package_reasoning_task(
            task_dir, ORACLE_ROOT / (task["task_id"] + ".oracle.json")
        )
    return result


def update_reasoning_registry(packages: Dict[str, str]) -> None:
    rows = [json.loads(line) for line in REASONING_REGISTRY.read_text(encoding="utf-8").splitlines() if line.strip()]
    for row in rows:
        if row["task_id"] not in packages:
            raise ValueError("registry contains an unpackageable task: %s" % row["task_id"])
        row["package_sha256"] = packages[row["task_id"]]
    REASONING_REGISTRY.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in sorted(rows, key=lambda value: value["task_id"])),
        encoding="utf-8",
    )


def _closure_task_toml(task: Dict[str, Any]) -> str:
    return f'''schema_version = "1.3"
artifacts = ["/app/circuit.spi"]

[task]
name = {_toml_string("evoldo-bench/" + task["task_id"])}
description = {_toml_string(task["objective"])}
authors = [{{ name = "EvoLDO-Bench contributors" }}]
keywords = ["analog", "ldo", "sky130", "ngspice", "design-closure"]

[metadata]
task_id = {_toml_string(task["task_id"])}
revision = 2
maturity = "public-development"
pdk = "sky130"

[verifier]
environment_mode = "separate"

[verifier.environment]
network_mode = "no-network"
build_timeout_sec = 1800.0
cpus = 2
memory_mb = 4096
storage_mb = 4096

[environment]
network_mode = "no-network"
build_timeout_sec = 1800.0
cpus = 2
memory_mb = 4096
storage_mb = 4096
'''


def package_closure_task(task_dir: Path) -> str:
    task = json.loads((task_dir / "task.json").read_text())
    for name in ("environment", "tests", "solution"):
        target = task_dir / name
        if target.exists():
            shutil.rmtree(target)
    instruction = (task_dir / "prompt.md").read_text().rstrip() + f'''\n\n## Deliverable\n\n- Work in `/app` and edit only `/app/circuit.spi`.\n- Preserve `.subckt {task["candidate_subckt"]} {' '.join(task["candidate_pin_order"])}`.\n- Use only physical DUT devices permitted by the task policy.\n- The SKY130 model tree is an external, hash-pinned runtime dependency and is not a submitted artifact.\n- If time expires, the evaluator grades the current `circuit.spi`; a missing or empty file receives zero reward.\n'''
    (task_dir / "instruction.md").write_text(instruction, encoding="utf-8")
    (task_dir / "task.toml").write_text(_closure_task_toml(task), encoding="utf-8")

    starter = task_dir / "environment" / "starter"
    starter.mkdir(parents=True)
    shutil.copy2(task_dir / task["starter_candidate"], starter / "circuit.spi")
    shutil.copy2(task_dir / "task.json", starter / "task.json")
    (task_dir / "environment" / "Dockerfile").write_text(CLOSURE_ENVIRONMENT_DOCKERFILE, encoding="utf-8")

    tests = task_dir / "tests"
    package = tests / "evoldo_bench"
    track = tests / "track"
    package.mkdir(parents=True)
    (track / "tasks" / task["task_id"]).mkdir(parents=True)
    (track / "benches").mkdir(parents=True)
    for name in ("__init__.py", "errors.py", "utils.py", "public_pdk.py"):
        shutil.copy2(ROOT / "src" / "evoldo_bench" / name, package / name)
    shutil.copy2(task_dir / "task.json", track / "tasks" / task["task_id"] / "task.json")
    for scenario in task["scenarios"]:
        bench = (task_dir / scenario["bench_template"]).resolve()
        shutil.copy2(bench, track / "benches" / bench.name)
    shutil.copy2(CLOSURE_ROOT / "public_pdk_manifest.json", track / "public_pdk_manifest.json")
    registry_entry = next(
        item for item in json.loads((CLOSURE_ROOT / "registry.json").read_text())["tasks"]
        if item["task_id"] == task["task_id"]
    )
    (track / "registry.json").write_text(_json({
        "schema_version": "1.0", "track_id": "evoldo_sky130_closure", "tasks": [registry_entry]
    }), encoding="utf-8")
    dockerfile = '''FROM python:3.12.3-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends ngspice && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY evoldo_bench /app/evoldo_tests/evoldo_bench
COPY track /app/evoldo_tests/track
COPY verify.py /app/evoldo_tests/verify.py
COPY test.sh /tests/test.sh
RUN chmod +x /tests/test.sh
ENV EVOLDO_CLOSURE_TASK_ID={task_id}
'''.format(task_id=task["task_id"])
    (tests / "Dockerfile").write_text(dockerfile, encoding="utf-8")
    (tests / "test.sh").write_text(CLOSURE_TEST_SH, encoding="utf-8")
    (tests / "test.sh").chmod(0o755)
    (tests / "verify.py").write_text(CLOSURE_VERIFY_PY, encoding="utf-8")

    solution = task_dir / "solution"
    solution.mkdir()
    shutil.copy2(CLOSURE_ROOT / "dev_reference" / "sky130_reference" / "ldo.sp", solution / "circuit.spi")
    solve = '''#!/usr/bin/env sh
set -eu
install -m 0644 "${SOLUTION_DIR:-/solution}/circuit.spi" "${APP_DIR:-/app}/circuit.spi"
'''
    (solution / "solve.sh").write_text(solve, encoding="utf-8")
    (solution / "solve.sh").chmod(0o755)

    digest = _package_digest(task_dir)
    (task_dir / "package_manifest.json").write_text(_json({
        "schema_version": "1.0", "task_id": task["task_id"], "package_sha256": digest,
        "runtime_excludes": ["tests", "solution"], "public_development_solution": True,
    }), encoding="utf-8")
    return digest


def package_all_closure_tasks() -> Dict[str, str]:
    result = {}
    for task_file in sorted((CLOSURE_ROOT / "tasks").glob("*/task.json")):
        task = json.loads(task_file.read_text())
        result[task["task_id"]] = package_closure_task(task_file.parent)
    return result


def main() -> int:
    packages = package_all_reasoning_tasks()
    update_reasoning_registry(packages)
    closure = package_all_closure_tasks()
    print("generated %d reasoning and %d closure task_examples-style packages" % (len(packages), len(closure)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
