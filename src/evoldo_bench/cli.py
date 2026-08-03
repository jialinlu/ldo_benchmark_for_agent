from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .aggregate import aggregate_scores, paired_lift
from .bundle import build_runtime_bundle
from .contamination import audit_task_collection
from .contracts import load_task, validate_answer, validate_oracle
from .discovery import discover_tasks, get_task, inventory, validate_registry
from .errors import BenchmarkError
from .grading import grade_directory, grade_one
from .report import write_markdown
from .runner import run_agent_command
from .utils import dump_json, load_json

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TASKS = ROOT / "benchmarks" / "ldo_original" / "dev" / "tasks"
DEFAULT_ORACLES = ROOT / "benchmarks" / "ldo_original" / "dev_reference" / "oracles"


def _path(value: str) -> Path:
    return Path(value).expanduser().resolve()


def _print_json(value: Any) -> None:
    json.dump(value, sys.stdout, indent=2, sort_keys=True, ensure_ascii=False)
    sys.stdout.write("\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="evoldo-bench", description="Original LDO benchmark runner and grader")
    sub = parser.add_subparsers(dest="command_name", required=True)

    listing = sub.add_parser("list", help="list and inventory tasks")
    listing.add_argument("--tasks-root", type=_path, default=DEFAULT_TASKS)
    listing.add_argument("--split")
    listing.add_argument("--json", action="store_true")

    validate = sub.add_parser("validate", help="validate task and public development oracle contracts")
    validate.add_argument("--tasks-root", type=_path, default=DEFAULT_TASKS)
    validate.add_argument("--oracle-root", type=_path, default=DEFAULT_ORACLES)
    validate.add_argument("--registry", type=_path)

    bundle = sub.add_parser("bundle", help="build a file-minimal runtime bundle without an oracle")
    bundle.add_argument("task_id")
    bundle.add_argument("--tasks-root", type=_path, default=DEFAULT_TASKS)
    bundle.add_argument("--output", type=_path, required=True)
    bundle.add_argument("--context-dir", type=_path)

    run = sub.add_parser("run", help="run an agent command in a prepared task bundle")
    run.add_argument("task_id")
    run.add_argument("--tasks-root", type=_path, default=DEFAULT_TASKS)
    run.add_argument("--output", type=_path, required=True)
    run.add_argument("--mode", default="direct_reasoning")
    run.add_argument("--context-dir", type=_path)
    run.add_argument("--timeout", type=int)
    run.add_argument(
        "agent_command",
        nargs="+",
        help="command after --, for example -- python agent.py",
    )

    grade = sub.add_parser("grade", help="grade one answer against an external oracle store")
    grade.add_argument("answer", type=_path)
    grade.add_argument("--tasks-root", type=_path, default=DEFAULT_TASKS)
    grade.add_argument("--oracle-root", type=_path, default=DEFAULT_ORACLES)
    grade.add_argument("--output", type=_path)

    grade_all = sub.add_parser("grade-dir", help="grade all answer.json files under a directory")
    grade_all.add_argument("answers_root", type=_path)
    grade_all.add_argument("--tasks-root", type=_path, default=DEFAULT_TASKS)
    grade_all.add_argument("--oracle-root", type=_path, default=DEFAULT_ORACLES)
    grade_all.add_argument("--scores-root", type=_path, required=True)

    aggregate = sub.add_parser("aggregate", help="aggregate task scores by family, suite, level, and variant")
    aggregate.add_argument("scores_root", type=_path)
    aggregate.add_argument("--mode", default="unspecified")
    aggregate.add_argument("--output", type=_path)
    aggregate.add_argument("--markdown", type=_path)

    audit = sub.add_parser("audit", help="audit split lineage, runtime leakage, oracle identity, and near duplicates")
    audit.add_argument("--tasks-root", type=_path, default=DEFAULT_TASKS)
    audit.add_argument("--oracle-root", type=_path, default=DEFAULT_ORACLES)
    audit.add_argument("--similarity-threshold", type=float, default=0.92)
    audit.add_argument("--output", type=_path)

    pair = sub.add_parser("paired-lift", help="compute direct-to-skill and skill-to-simulation score lift")
    pair.add_argument("--direct", type=_path)
    pair.add_argument("--skill", type=_path)
    pair.add_argument("--simulation", type=_path)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command_name == "list":
            tasks = discover_tasks(args.tasks_root, split=args.split)
            data = inventory(tasks)
            if args.json:
                _print_json(data)
            else:
                print("%d tasks / %d families" % (data["task_count"], data["family_count"]))
                for family, task_ids in data["families"].items():
                    print("- %s: %s" % (family, ", ".join(task_ids)))
            return 0
        if args.command_name == "validate":
            tasks = discover_tasks(args.tasks_root)
            missing = []
            for task in tasks:
                oracle = args.oracle_root / (task.task_id + ".oracle.json")
                if not oracle.is_file():
                    missing.append(task.task_id)
                else:
                    validate_oracle(load_json(oracle))
            registry_path = args.registry or args.tasks_root.parent.parent / "registry.jsonl"
            registry = validate_registry(tasks, registry_path)
            result = {
                "passed": not missing and registry["passed"],
                "task_count": len(tasks),
                "missing_oracles": missing,
                "registry": registry,
            }
            _print_json(result)
            return 0 if result["passed"] else 2
        if args.command_name == "bundle":
            _print_json(build_runtime_bundle(get_task(args.tasks_root, args.task_id), args.output, args.context_dir))
            return 0
        if args.command_name == "run":
            command = list(args.agent_command)
            if command and command[0] == "--":
                command = command[1:]
            _print_json(run_agent_command(get_task(args.tasks_root, args.task_id), args.output, command, args.mode, args.context_dir, args.timeout))
            return 0
        if args.command_name == "grade":
            score = grade_one(args.tasks_root, args.oracle_root, args.answer)
            if args.output:
                dump_json(args.output, score)
            _print_json(score)
            return 0
        if args.command_name == "grade-dir":
            scores = grade_directory(args.tasks_root, args.oracle_root, args.answers_root, args.scores_root)
            _print_json({"graded": len(scores), "scores_root": str(args.scores_root)})
            return 0
        if args.command_name == "aggregate":
            scores = [load_json(path) for path in sorted(args.scores_root.rglob("*.score.json"))]
            report = aggregate_scores(scores, mode=args.mode)
            if args.output:
                dump_json(args.output, report)
            if args.markdown:
                write_markdown(args.markdown, report)
            _print_json(report)
            return 0
        if args.command_name == "audit":
            report = audit_task_collection(args.tasks_root, args.oracle_root, args.similarity_threshold)
            if args.output:
                dump_json(args.output, report)
            _print_json(report)
            return 0 if report["passed"] else 3
        if args.command_name == "paired-lift":
            reports: Dict[str, Dict[str, Any]] = {}
            if args.direct:
                reports["direct_reasoning"] = load_json(args.direct)
            if args.skill:
                reports["agentic_skill"] = load_json(args.skill)
            if args.simulation:
                reports["simulation_assisted"] = load_json(args.simulation)
            _print_json(paired_lift(reports))
            return 0
    except (BenchmarkError, ValueError, OSError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
