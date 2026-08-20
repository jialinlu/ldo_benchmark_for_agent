from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .adapters import CommandAgentAdapter, NgspiceBatchAdapter, ProcessSimulatorAdapter
from .aggregate import aggregate_rollouts, aggregate_scores, failed_rollout_score, paired_lift
from .bundle import build_runtime_bundle
from .calibration import calibrate_judges, combine_judges
from .contamination import audit_task_collection
from .contracts import ALLOWED_MODES, load_task, validate_answer, validate_oracle
from .discovery import discover_tasks, get_task, inventory, validate_registry
from .errors import BenchmarkError, PolicyError
from .exam import create_private_canary, freeze_exam, redact_exam_manifest, verify_exam
from .external_kg import freeze_external_retrievals
from .experiment import compare_treatments, run_experiment
from .grading import grade_directory, grade_one
from .leaderboard import write_leaderboard
from .live_verify import verify_live_task
from .outcomes import is_infrastructure_status
from .report import write_markdown
from .recovery import recover_experiment
from .probes import evaluate_probe_contract
from .public_pdk import DEFAULT_TRACK_ROOT, load_closure_registry, run_closure_suite
from .qualification import build_candidate_manifest, qualify_candidate, summarize_qualification_attempts
from .runner import run_agent_command
from .telemetry import summarize_effort
from .utils import dump_json, load_json

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TASKS = ROOT / "benchmarks" / "ldo_v07" / "tasks"
DEFAULT_ORACLES = ROOT / "benchmarks" / "ldo_v07" / "dev_reference" / "oracles"


def _path(value: str) -> Path:
    return Path(value).expanduser().resolve()


def _print_json(value: Any) -> None:
    json.dump(value, sys.stdout, indent=2, sort_keys=True, ensure_ascii=False)
    sys.stdout.write("\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="evoldo-bench", description="EvoLDO v0.7 LDO model, knowledge, sizing, and EDA benchmark")
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

    live = sub.add_parser("verify-live", help="run the authoritative SKY130 or IC618 gate for a tool task")
    live.add_argument("answer", type=_path)
    live.add_argument("--app-root", type=_path)
    live.add_argument("--tasks-root", type=_path, default=DEFAULT_TASKS)
    live.add_argument("--oracle-root", type=_path, default=DEFAULT_ORACLES)
    live.add_argument("--pdk-root", type=_path)
    live.add_argument("--eda-ssh-target")
    live.add_argument("--ngspice", default="ngspice")
    live.add_argument("--output", type=_path)

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

    experiment = sub.add_parser("experiment", help="run a frozen repeated-rollout treatment")
    experiment.add_argument("--tasks-root", type=_path, default=DEFAULT_TASKS)
    experiment.add_argument("--oracle-root", type=_path, default=DEFAULT_ORACLES)
    experiment.add_argument("--output", type=_path, required=True)
    experiment.add_argument("--model-id", required=True)
    experiment.add_argument("--mode", choices=sorted(ALLOWED_MODES), required=True)
    experiment.add_argument("--rollouts", type=int, default=3)
    experiment.add_argument("--base-seed", type=int, default=2026)
    experiment.add_argument("--context-dir", type=_path)
    experiment.add_argument("--knowledge-corpus", type=_path)
    experiment.add_argument("--knowledge-top-k", type=int, default=4)
    experiment.add_argument("--knowledge-mcp-config", type=_path)
    experiment.add_argument("--knowledge-snapshot-manifest", type=_path)
    experiment.add_argument("--knowledge-relevance-manifest", type=_path)
    experiment.add_argument(
        "--knowledge-freeze-dir", type=_path,
        help="reviewed kg-preflight output; avoids contacting KG during the model experiment",
    )
    experiment.add_argument("--task-id", action="append", dest="task_ids")
    experiment.add_argument("--timeout", type=int)
    experiment.add_argument("--paired-modes", help="comma-separated modes; restrict every treatment to tasks eligible in all modes")
    experiment.add_argument("agent_command", nargs="+", help="command template after --; supports {task_id}, {rollout}, {seed}")

    kg_preflight = sub.add_parser(
        "kg-preflight",
        help="freeze and validate external MCP KG retrievals without invoking a model",
    )
    kg_preflight.add_argument("--tasks-root", type=_path, default=DEFAULT_TASKS)
    kg_preflight.add_argument("--output", type=_path, required=True)
    kg_preflight.add_argument("--knowledge-mcp-config", type=_path, required=True)
    kg_preflight.add_argument("--knowledge-snapshot-manifest", type=_path, required=True)
    kg_preflight.add_argument("--knowledge-relevance-manifest", type=_path)
    kg_preflight.add_argument("--knowledge-top-k", type=int, default=4)
    kg_preflight.add_argument("--task-id", action="append", dest="task_ids")

    experiment_report = sub.add_parser("experiment-report", help="aggregate scores and effort from an experiment directory")
    experiment_report.add_argument("experiment_root", type=_path)
    experiment_report.add_argument("--output", type=_path)
    experiment_report.add_argument("--markdown", type=_path)

    recover = sub.add_parser(
        "recover-experiment",
        help="regrade an experiment and retry only provider/runner infrastructure failures",
    )
    recover.add_argument("--source", type=_path, required=True)
    recover.add_argument("--output", type=_path, required=True)
    recover.add_argument("--tasks-root", type=_path, default=DEFAULT_TASKS)
    recover.add_argument("--oracle-root", type=_path, default=DEFAULT_ORACLES)
    recover.add_argument("--max-infrastructure-retries", type=int, default=5)
    recover.add_argument("--retry-backoff-seconds", type=float, default=2.0)
    recover.add_argument("--timeout", type=int)
    recover.add_argument("--resume", action="store_true")
    recover.add_argument(
        "agent_command", nargs="+",
        help="command template after --; supports {task_id}, {rollout}, and {seed}",
    )

    probe = sub.add_parser("validate-probe", help="enforce AnalogProbeContract and task-specific tool policy")
    probe.add_argument("probe", type=_path)
    probe.add_argument("--tasks-root", type=_path, default=DEFAULT_TASKS)
    probe.add_argument("--task-id")
    probe.add_argument("--available-artifact", action="append", default=[])

    simulate = sub.add_parser("simulate-probe", help="execute a validated probe through a uniform simulator adapter")
    simulate.add_argument("request", type=_path)
    simulate.add_argument("--workspace", type=_path, required=True)
    simulate.add_argument("--timeout", type=int, default=120)
    simulate.add_argument("--ngspice", action="store_true")
    simulate.add_argument("--simulator-command", nargs="+", default=[])

    freeze = sub.add_parser("freeze-exam", help="create a cryptographic release manifest for a sealed exam store")
    freeze.add_argument("--tasks-root", type=_path, required=True)
    freeze.add_argument("--oracle-root", type=_path, required=True)
    freeze.add_argument("--policy", type=_path, required=True)
    freeze.add_argument("--skill-root", type=_path)
    freeze.add_argument("--tool-root", type=_path)
    freeze.add_argument("--release-id", required=True)
    freeze.add_argument("--output", type=_path, required=True)

    verify = sub.add_parser("verify-exam", help="verify stores against a frozen exam manifest")
    verify.add_argument("manifest", type=_path)
    verify.add_argument("--tasks-root", type=_path, required=True)
    verify.add_argument("--oracle-root", type=_path, required=True)
    verify.add_argument("--skill-root", type=_path)
    verify.add_argument("--tool-root", type=_path)

    redact = sub.add_parser("redact-exam-manifest", help="create a public commitment without hidden filenames or policy contents")
    redact.add_argument("manifest", type=_path)
    redact.add_argument("--output", type=_path, required=True)

    canary = sub.add_parser("create-exam-canary", help="create a private release canary before freezing a sealed store")
    canary.add_argument("--release-id", required=True)
    canary.add_argument("--output", type=_path, required=True)

    candidate = sub.add_parser("candidate-manifest", help="hash an immutable design candidate")
    candidate.add_argument("candidate_root", type=_path)
    candidate.add_argument("--candidate-id", required=True)
    candidate.add_argument("--parent-id", default="none")
    candidate.add_argument("--output", type=_path)

    qualify = sub.add_parser("qualify", help="apply fresh-evidence design-closure gates")
    qualify.add_argument("candidate", type=_path)
    qualify.add_argument("evidence", type=_path, help="JSON object with an evidence array")
    qualify.add_argument("--output", type=_path)

    calibration = sub.add_parser("calibrate-judges", help="compare two or more frozen judges with adjudicated human labels")
    calibration.add_argument("human_records", type=_path, help="JSON object with a records array")
    calibration.add_argument("judge_records", type=_path, help="JSON object with a records array")
    calibration.add_argument("--max-mae", type=float, default=10.0)
    calibration.add_argument("--minimum-critical-recall", type=float, default=0.9)
    calibration.add_argument("--minimum-label-agreement", type=float, default=0.8)
    calibration.add_argument("--output", type=_path)

    combine = sub.add_parser("combine-judges", help="combine two judge records or route disagreement to human review")
    combine.add_argument("judge_records", type=_path, help="JSON object with exactly two records")
    combine.add_argument("--score-tolerance", type=float, default=10.0)

    leaderboard = sub.add_parser("leaderboard", help="build static JSON/CSV/HTML score-versus-effort artifacts")
    leaderboard.add_argument("reports", nargs="+", type=_path)
    leaderboard.add_argument("--output-dir", type=_path, required=True)

    compare = sub.add_parser("compare-treatments", help="verify paired treatments and report score/token lift, harm, and KG retrieval recall")
    compare.add_argument("manifests", nargs="+", type=_path)

    closure = sub.add_parser("closure-metrics", help="summarize evaluations and wall time to first qualified candidate")
    closure.add_argument("attempts", type=_path, help="JSON object with an attempts array")

    closure_list = sub.add_parser("closure-list", help="list real public-PDK LDO design-closure tasks")
    closure_list.add_argument("--track-root", type=_path, default=DEFAULT_TRACK_ROOT)

    closure_run = sub.add_parser("closure-run", help="run real SKY130/ngspice design-closure gates")
    closure_run.add_argument("--pdk-root", type=_path, required=True, help="model checkout root or sky130_pdk directory")
    closure_run.add_argument("--track-root", type=_path, default=DEFAULT_TRACK_ROOT)
    closure_run.add_argument("--output", type=_path, required=True)
    closure_run.add_argument("--task-id", action="append", dest="task_ids")
    closure_run.add_argument("--candidate", type=_path, help="one candidate netlist to qualify against every selected task")
    closure_run.add_argument("--ngspice", default="ngspice")
    closure_run.add_argument("--timeout", type=int, default=180)

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
            adjacent_registry = args.tasks_root.parent / "registry.jsonl"
            registry_path = args.registry or (adjacent_registry if adjacent_registry.is_file()
                                               else args.tasks_root.parent.parent / "registry.jsonl")
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
        if args.command_name == "verify-live":
            answer = load_json(args.answer)
            task = get_task(args.tasks_root, answer.get("task_id", ""))
            result = verify_live_task(task, args.answer, args.tasks_root, args.oracle_root,
                                      args.app_root, args.pdk_root, args.eda_ssh_target, args.ngspice)
            if args.output:
                dump_json(args.output, result)
            _print_json(result)
            if not result.get("score_valid", False):
                return 12
            return 0 if result.get("score", 0) > 0 else 13
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
        if args.command_name == "experiment":
            command = list(args.agent_command)
            if command and command[0] == "--":
                command = command[1:]
            result = run_experiment(
                args.tasks_root, args.oracle_root, args.output, CommandAgentAdapter(command),
                args.model_id, args.mode, args.rollouts, args.base_seed, args.context_dir,
                args.task_ids, args.timeout,
                [value.strip() for value in args.paired_modes.split(",") if value.strip()] if args.paired_modes else None,
                args.knowledge_corpus, args.knowledge_top_k,
                args.knowledge_mcp_config, args.knowledge_snapshot_manifest,
                args.knowledge_relevance_manifest,
                args.knowledge_freeze_dir,
            )
            _print_json({"output": str(args.output), "run_count": result["run_count"], "context_snapshot": result["context_snapshot"]["snapshot_id"]})
            return 0
        if args.command_name == "kg-preflight":
            wanted = set(args.task_ids or [])
            tasks = [
                task for task in discover_tasks(args.tasks_root)
                if (not wanted or task.task_id in wanted)
                and "knowledge_assisted" in task.data["eligible_modes"]
            ]
            missing = sorted(wanted.difference(task.task_id for task in tasks))
            if missing:
                raise PolicyError("unknown or KG-ineligible task ids: %s" % ", ".join(missing))
            result = freeze_external_retrievals(
                tasks,
                args.knowledge_mcp_config,
                args.knowledge_snapshot_manifest,
                args.output,
                args.knowledge_top_k,
                args.knowledge_relevance_manifest,
            )
            _print_json({
                "output": str(args.output),
                "task_count": result["task_count"],
                "source_snapshot_id": result["source_snapshot_id"],
                "source_snapshot_sha256": result["source_snapshot_sha256"],
            })
            return 0
        if args.command_name == "recover-experiment":
            command = list(args.agent_command)
            if command and command[0] == "--":
                command = command[1:]
            result = recover_experiment(
                args.source, args.output, args.tasks_root, args.oracle_root,
                CommandAgentAdapter(command), args.max_infrastructure_retries,
                args.timeout, args.retry_backoff_seconds, args.resume,
            )
            _print_json({
                "output": str(args.output),
                "capability_complete": result["capability_complete"],
                "recovery": result["recovery"],
            })
            return 0 if result["capability_complete"] else 12
        if args.command_name == "experiment-report":
            manifest = load_json(args.experiment_root / "experiment_manifest.json")
            unresolved_infrastructure = [
                row for row in manifest.get("rows", [])
                if is_infrastructure_status(row.get("status"))
            ]
            if manifest.get("capability_complete") is False or unresolved_infrastructure:
                raise PolicyError(
                    "capability report is blocked while infrastructure retries remain unresolved"
                )
            scores = []
            telemetry = []
            for row in manifest["rows"]:
                if row.get("status") == "ok" and row.get("score_file"):
                    scores.append(load_json(args.experiment_root / row["score_file"]))
                else:
                    scores.append(failed_rollout_score(row))
                telemetry.append(load_json(args.experiment_root / row["telemetry_file"]))
            report = aggregate_rollouts(scores, telemetry, manifest["model_id"], manifest["mode"])
            attempt_telemetry = []
            infrastructure_attempts = 0
            for row in manifest["rows"]:
                for attempt in row.get("attempts", []):
                    attempt_telemetry.append(
                        load_json(args.experiment_root / attempt["telemetry_file"])
                    )
                    infrastructure_attempts += attempt.get("classification") == "infrastructure"
            if attempt_telemetry:
                operational = summarize_effort(attempt_telemetry)
                score_points = sum(float(score["score"]) for score in scores)
                passed = sum(bool(score.get("passed")) for score in scores)
                total_tokens = float(operational["total_observed_tokens"])
                token_counts = operational["token_measurement"]
                measurement_complete = (
                    token_counts["measured_rollouts"] == len(attempt_telemetry)
                )
                report["operational_effort_all_attempts"] = operational
                report["operational_attempt_count"] = len(attempt_telemetry)
                report["infrastructure_attempt_count"] = infrastructure_attempts
                report["operational_token_efficiency"] = {
                    "measurement_complete": measurement_complete,
                    "tokens_per_score_point": (
                        round(total_tokens / score_points, 6)
                        if measurement_complete and score_points else None
                    ),
                    "tokens_per_pass": (
                        round(total_tokens / passed, 6)
                        if measurement_complete and passed else None
                    ),
                    "observed_tokens_per_score_point_lower_bound": (
                        round(total_tokens / score_points, 6)
                        if total_tokens and score_points else None
                    ),
                }
            if args.output:
                dump_json(args.output, report)
            if args.markdown:
                write_markdown(args.markdown, report)
            _print_json(report)
            return 0
        if args.command_name == "validate-probe":
            probe_data = load_json(args.probe)
            task_id = args.task_id or probe_data.get("task_id")
            task = get_task(args.tasks_root, task_id) if task_id else None
            report = evaluate_probe_contract(probe_data, task, args.available_artifact)
            _print_json(report)
            return 0 if report["passed"] else 4
        if args.command_name == "simulate-probe":
            request = load_json(args.request)
            if args.ngspice:
                adapter = NgspiceBatchAdapter()
            else:
                adapter = ProcessSimulatorAdapter(list(args.simulator_command))
            result = adapter.run(request, args.workspace, args.timeout)
            _print_json(result)
            return 0 if result.get("status") == "OK" else 5
        if args.command_name == "freeze-exam":
            result = freeze_exam(args.output, args.tasks_root, args.oracle_root, load_json(args.policy), args.skill_root, args.tool_root, ROOT, args.release_id)
            _print_json(result)
            return 0
        if args.command_name == "verify-exam":
            result = verify_exam(load_json(args.manifest), args.tasks_root, args.oracle_root, args.skill_root, args.tool_root)
            _print_json(result)
            return 0 if result["passed"] else 6
        if args.command_name == "redact-exam-manifest":
            result = redact_exam_manifest(load_json(args.manifest))
            dump_json(args.output, result)
            _print_json(result)
            return 0
        if args.command_name == "create-exam-canary":
            _print_json(create_private_canary(args.output, args.release_id))
            return 0
        if args.command_name == "candidate-manifest":
            result = build_candidate_manifest(args.candidate_root, args.candidate_id, args.parent_id)
            if args.output:
                dump_json(args.output, result)
            _print_json(result)
            return 0
        if args.command_name == "qualify":
            evidence = load_json(args.evidence).get("evidence", [])
            result = qualify_candidate(load_json(args.candidate), evidence)
            if args.output:
                dump_json(args.output, result)
            _print_json(result)
            return 0 if result["qualified"] else 7
        if args.command_name == "calibrate-judges":
            result = calibrate_judges(
                load_json(args.human_records).get("records", []),
                load_json(args.judge_records).get("records", []),
                args.max_mae,
                args.minimum_critical_recall,
                args.minimum_label_agreement,
            )
            if args.output:
                dump_json(args.output, result)
            _print_json(result)
            return 0 if result["passed"] else 8
        if args.command_name == "combine-judges":
            result = combine_judges(load_json(args.judge_records).get("records", []), args.score_tolerance)
            _print_json(result)
            return 0 if result["status"] == "AGREED" else 9
        if args.command_name == "leaderboard":
            result = write_leaderboard(args.output_dir, [load_json(path) for path in args.reports])
            _print_json({"entry_count": result["entry_count"], "output_dir": str(args.output_dir)})
            return 0
        if args.command_name == "compare-treatments":
            result = compare_treatments([load_json(path) for path in args.manifests])
            _print_json(result)
            return 0 if result["passed"] else 10
        if args.command_name == "closure-metrics":
            _print_json(summarize_qualification_attempts(load_json(args.attempts).get("attempts", [])))
            return 0
        if args.command_name == "closure-list":
            registry = load_closure_registry(args.track_root)
            _print_json({"task_count": len(registry["tasks"]), "tasks": registry["tasks"]})
            return 0
        if args.command_name == "closure-run":
            registry = load_closure_registry(args.track_root)
            task_ids = args.task_ids or [item["task_id"] for item in registry["tasks"]]
            result = run_closure_suite(
                task_ids, args.pdk_root, args.output, args.candidate, args.track_root,
                args.ngspice, args.timeout,
            )
            dump_json(args.output / "suite_result.json", result)
            _print_json(result)
            return 0 if result["passed"] else 11
    except (BenchmarkError, ValueError, OSError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
