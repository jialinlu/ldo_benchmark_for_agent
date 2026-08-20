from __future__ import annotations

import os
import shutil
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .adapters import AgentAdapter
from .contracts import Task
from .discovery import get_task
from .errors import BenchmarkError, ContractError, PolicyError
from .experiment import _load_agent_telemetry, _normalize_tool_ledger, _task_contract_hash
from .grading import grade_one
from .outcomes import classify_attempt
from .provenance import repository_fingerprint
from .runner import run_agent_command
from .telemetry import empty_telemetry
from .utils import dump_json, load_json, safe_relative_path, sha256_file, utc_timestamp


def _source_run_dir(source_root: Path, row: Dict[str, Any]) -> Path:
    relative = safe_relative_path(str(row["telemetry_file"]))
    run_dir = (source_root / relative).parent.resolve()
    source = source_root.resolve()
    if source != run_dir and source not in run_dir.parents:
        raise PolicyError("source telemetry path escapes experiment root")
    if not run_dir.is_dir():
        raise PolicyError("source run directory does not exist: %s" % run_dir)
    return run_dir


def _load_normalized_telemetry(
    run_dir: Path,
    task: Task,
    model_id: str,
    mode: str,
    rollout: int,
    seed: int,
    record: Dict[str, Any],
) -> Tuple[Dict[str, Any], Optional[str]]:
    fallback = empty_telemetry(
        task.task_id, model_id, mode, rollout, seed,
        float(record.get("duration_seconds", 0.0)),
    )
    candidates = [run_dir / "telemetry.normalized.json", run_dir / "app" / "telemetry.json"]
    for candidate in candidates:
        if not candidate.is_file():
            continue
        try:
            return _load_agent_telemetry(candidate, fallback), None
        except (ContractError, ValueError, OSError) as exc:
            return fallback, str(exc)
    return fallback, None


def _explicit_output_budget_exhaustion(run_dir: Path) -> Optional[str]:
    """Recover provider finish metadata emitted before the structured outcome existed."""
    stdout_path = run_dir / "stdout.log"
    if not stdout_path.is_file():
        return None
    try:
        raw = load_json(stdout_path)
    except (OSError, ValueError):
        return None
    choices = raw.get("choices", []) if isinstance(raw, dict) else []
    if not choices or not isinstance(choices[0], dict):
        return None
    reason = choices[0].get("finish_reason")
    return str(reason) if reason in {"length", "max_tokens"} else None


def _verify_row_bindings(task: Task, row: Dict[str, Any], oracle_root: Path) -> None:
    """Refuse to regrade or retry a row against changed benchmark content."""
    oracle_path = oracle_root / (task.task_id + ".oracle.json")
    actual = {
        "task_manifest_sha256": sha256_file(task.manifest_path),
        "task_contract_sha256": _task_contract_hash(task),
        "prompt_sha256": sha256_file(task.prompt_path),
        "input_files_sha256": {
            value: sha256_file(task.source_path(value)) for value in task.data["input_files"]
        },
        "answer_contract_sha256": sha256_file(
            task.source_path(task.data["answer_template_file"])
        ),
        "oracle_sha256": sha256_file(oracle_path) if oracle_path.is_file() else None,
    }
    for field, value in actual.items():
        if field not in row:
            raise PolicyError("source experiment row lacks required content binding: %s" % field)
        if row[field] != value:
            raise ContractError(
                "source experiment content binding changed for %s: %s"
                % (task.task_id, field)
            )


def _knowledge_retry_context(output_root: Path, row: Dict[str, Any]) -> Path:
    attempt_zero = (
        output_root / "runs" / str(row["task_id"])
        / ("rollout-%03d" % int(row["rollout"])) / "attempt-000" / "app" / "context"
    )
    retrieval_path = attempt_zero / "kg_retrieval.json"
    if not retrieval_path.is_file():
        raise PolicyError("knowledge retry is missing the frozen per-task retrieval snapshot")
    retrieval = load_json(retrieval_path)
    expected = row.get("knowledge_context")
    if not isinstance(expected, dict):
        raise PolicyError("knowledge retry row is missing retrieval provenance")
    if retrieval.get("corpus_sha256") != expected.get("corpus_sha256"):
        raise PolicyError("knowledge retry corpus binding changed")
    if retrieval.get("query_sha256") != expected.get("query_sha256"):
        raise PolicyError("knowledge retry query binding changed")
    returned = [entry.get("id") for entry in retrieval.get("entries", [])]
    if returned != expected.get("returned_ids"):
        raise PolicyError("knowledge retry returned-id binding changed")
    snapshot_sha = expected.get("snapshot_sha256")
    if snapshot_sha is not None and sha256_file(retrieval_path) != snapshot_sha:
        raise PolicyError("knowledge retry snapshot hash changed")
    return attempt_zero


def _normalize_attempt(
    run_dir: Path,
    task: Task,
    tasks_root: Path,
    oracle_root: Path,
    model_id: str,
    mode: str,
    rollout: int,
    seed: int,
    preserve_source: bool,
    knowledge_context: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Optional[Dict[str, Any]], bool]:
    record_path = run_dir / "run_record.json"
    if not record_path.is_file():
        raise PolicyError("attempt is missing run_record.json: %s" % run_dir)
    if preserve_source:
        shutil.copy2(str(record_path), str(run_dir / "run_record.source.json"))
        for name, target in (
            ("score.json", "score.source.json"),
            ("telemetry.normalized.json", "telemetry.source.normalized.json"),
            ("tool_ledger.normalized.json", "tool_ledger.source.normalized.json"),
        ):
            path = run_dir / name
            if path.is_file():
                shutil.copy2(str(path), str(run_dir / target))
    record = load_json(record_path)
    telemetry, telemetry_error = _load_normalized_telemetry(
        run_dir, task, model_id, mode, rollout, seed, record,
    )
    if knowledge_context is not None:
        telemetry["knowledge_retrieval"] = knowledge_context
    if telemetry_error:
        record["telemetry_error"] = telemetry_error
    try:
        ledger = _normalize_tool_ledger(run_dir / "app" / "tool_ledger.json", task)
    except (ContractError, ValueError, OSError) as exc:
        ledger = {
            "schema_version": "1.0", "entries": [], "policy_rejections": 1,
            "ineffective_calls": 0, "normalization_error": str(exc),
        }
        record["status"] = "policy_fail"
        record["policy_failure"] = "invalid_tool_ledger"
    declared_calls = len(ledger["entries"])
    telemetry["tool_calls"] = declared_calls
    telemetry["probe_calls"] = declared_calls
    telemetry["ineffective_probe_calls"] = ledger["ineffective_calls"]
    telemetry["policy_rejected_probe_calls"] = ledger["policy_rejections"]
    if declared_calls > int(task.data["budget"]["max_tool_calls"]):
        record["status"] = "policy_fail"
        record["policy_failure"] = "tool_budget_exceeded"
    elif ledger["policy_rejections"]:
        record["status"] = "policy_fail"
        record["policy_failure"] = "probe_contract_rejected"
    if telemetry.get("model_identity_status") == "mismatch":
        record["status"] = "model_identity_mismatch"
        record["identity_failure"] = {
            "requested_model_id": model_id,
            "provider_reported_model_id": telemetry.get("provider_reported_model_id"),
        }
    finish_reason = _explicit_output_budget_exhaustion(run_dir)
    if finish_reason is not None:
        record["status"] = "output_budget_exhausted"
        record["budget_failure"] = {
            "provider_finish_reason": finish_reason,
            "classification": "configuration_invalid",
        }

    original_status = record.get("status")
    score = None
    framework_regraded = False
    if classify_attempt(record, telemetry) != "infrastructure":
        answer_path = run_dir / "app" / "answer.json"
        if answer_path.is_file() and original_status in {"ok", "format_fail"}:
            try:
                candidate_answer = load_json(answer_path)
                if candidate_answer.get("task_id") != task.task_id:
                    raise ContractError(
                        "answer.task_id must match scheduled task %s" % task.task_id
                    )
                score = grade_one(tasks_root, oracle_root, answer_path)
            except (BenchmarkError, ValueError, OSError) as exc:
                record["status"] = "format_fail"
                record["answer_error"] = str(exc)
            else:
                framework_regraded = original_status == "format_fail"
                record["status"] = "ok"
                record.pop("answer_error", None)
                score["rollout"] = rollout
                score["seed"] = seed
                score["run_status"] = "ok"
                dump_json(run_dir / "score.json", score)
        elif original_status == "ok":
            record["status"] = "format_fail"
            record["answer_error"] = "successful adapter outcome did not produce answer.json"

    record["framework_regraded"] = framework_regraded
    dump_json(record_path, record)
    dump_json(run_dir / "telemetry.normalized.json", telemetry)
    dump_json(run_dir / "tool_ledger.normalized.json", ledger)
    return record, telemetry, score, framework_regraded


def _attempt_summary(
    output_root: Path,
    run_dir: Path,
    attempt_index: int,
    record: Dict[str, Any],
    telemetry: Dict[str, Any],
    score: Optional[Dict[str, Any]],
    framework_regraded: bool,
) -> Dict[str, Any]:
    token_values = [
        telemetry.get("token_breakdown", {}).get(field)
        for field in ("input", "cached_input", "output", "reasoning")
    ]
    token_values = [
        value for value in token_values
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    ]
    return {
        "attempt": attempt_index,
        "classification": classify_attempt(record, telemetry),
        "status": record.get("status", "failed"),
        "framework_regraded": framework_regraded,
        "answer_present": bool(record.get("answer_present")),
        "score": score.get("score") if score else None,
        "passed": bool(score.get("passed")) if score else False,
        "duration_seconds": record.get("duration_seconds"),
        "observed_tokens": sum(float(value) for value in token_values) if token_values else None,
        "token_measurement_status": telemetry.get("token_measurement_status", "unavailable"),
        "provider_total_cost_usd": telemetry.get("provider_total_cost_usd"),
        "cost_measurement_status": telemetry.get("cost_measurement_status", "unavailable"),
        "model_identity_status": telemetry.get("model_identity_status", "unavailable"),
        "provider_reported_model_id": telemetry.get("provider_reported_model_id"),
        "wall_seconds": telemetry.get("wall_seconds"),
        "terminal_tokens": telemetry.get("milestones", {}).get("terminal_tokens"),
        "terminal_tokens_status": telemetry.get("milestones", {}).get(
            "terminal_tokens_status", telemetry.get("token_measurement_status")
        ),
        "token_breakdown": telemetry.get("token_breakdown"),
        "requested_model_parameters": telemetry.get("requested_model_parameters"),
        "provider_seed": telemetry.get("provider_seed"),
        "knowledge_context": telemetry.get("knowledge_retrieval"),
        "run_record_file": str((run_dir / "run_record.json").relative_to(output_root)),
        "telemetry_file": str((run_dir / "telemetry.normalized.json").relative_to(output_root)),
        "score_file": str((run_dir / "score.json").relative_to(output_root)) if score else None,
    }


def _enforce_retry_controls(
    row: Dict[str, Any], attempt: Dict[str, Any], run_dir: Path,
) -> None:
    """Turn a retry with changed model controls into an infrastructure-invalid attempt."""
    violations = []
    expected_parameters = row.get("requested_model_parameters")
    actual_parameters = attempt.get("requested_model_parameters")
    # Pre-v0.7.0-final manifests did not normalize the adapter's inner provider timeout.
    # Preserve replay compatibility for those manifests while requiring exact equality for
    # every newly generated manifest that contains the field.
    comparable_actual = actual_parameters
    if isinstance(expected_parameters, dict) and "output_timeout_seconds" not in expected_parameters:
        comparable_actual = dict(actual_parameters) if isinstance(actual_parameters, dict) else actual_parameters
        if isinstance(comparable_actual, dict):
            comparable_actual.pop("output_timeout_seconds", None)
    if comparable_actual != expected_parameters:
        violations.append("requested_model_parameters")
    expected_seed = row.get("provider_seed")
    if expected_seed is not None and attempt.get("provider_seed") != expected_seed:
        violations.append("provider_seed")
    expected_knowledge = row.get("knowledge_context")
    if expected_knowledge is not None and attempt.get("knowledge_context") != expected_knowledge:
        violations.append("knowledge_context")
    if not violations:
        return
    attempt["classification"] = "infrastructure"
    attempt["status"] = "control_mismatch"
    attempt["score"] = None
    attempt["passed"] = False
    attempt["score_file"] = None
    attempt["control_violations"] = violations
    record_path = run_dir / "run_record.json"
    record = load_json(record_path)
    record["status"] = "control_mismatch"
    record["control_violations"] = violations
    dump_json(record_path, record)


def _set_rollout_environment(seed: int, rollout: int) -> Dict[str, Optional[str]]:
    previous = {key: os.environ.get(key) for key in ("EVOLDO_SEED", "EVOLDO_ROLLOUT")}
    os.environ["EVOLDO_SEED"] = str(seed)
    os.environ["EVOLDO_ROLLOUT"] = str(rollout)
    return previous


def _restore_rollout_environment(previous: Dict[str, Optional[str]]) -> None:
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def _apply_accepted_attempt(row: Dict[str, Any], attempt: Dict[str, Any]) -> None:
    row["accepted_attempt"] = attempt["attempt"]
    row["resolution_status"] = "framework_regraded" if attempt["framework_regraded"] else "accepted"
    row["status"] = attempt["status"]
    row["answer_present"] = attempt["answer_present"]
    row["score"] = attempt["score"]
    row["passed"] = attempt["passed"]
    row["telemetry_file"] = attempt["telemetry_file"]
    row["score_file"] = attempt["score_file"]
    for field in (
        "wall_seconds", "terminal_tokens", "terminal_tokens_status", "token_breakdown",
        "requested_model_parameters", "provider_seed", "knowledge_context",
    ):
        row[field] = attempt.get(field)


def _refresh_recovery_summary(manifest: Dict[str, Any]) -> None:
    attempts = [attempt for row in manifest["rows"] for attempt in row.get("attempts", [])]
    unresolved = [
        row for row in manifest["rows"]
        if row.get("resolution_status") in {
            "pending_infrastructure_retry", "infra_exhausted", "output_budget_exhausted",
        }
    ]
    classifications = Counter(attempt["classification"] for attempt in attempts)
    statuses = Counter(attempt["status"] for attempt in attempts)
    manifest["capability_complete"] = not unresolved
    manifest["recovery"].update({
        "attempt_count": len(attempts),
        "retry_attempt_count": max(0, len(attempts) - len(manifest["rows"])),
        "infrastructure_attempt_count": classifications.get("infrastructure", 0),
        "framework_regraded_rollouts": sum(
            row.get("resolution_status") == "framework_regraded" for row in manifest["rows"]
        ),
        "unresolved_infrastructure_rollouts": len(unresolved),
        "attempt_status_counts": dict(sorted(statuses.items())),
    })


def _checkpoint(output_root: Path, manifest: Dict[str, Any]) -> None:
    _refresh_recovery_summary(manifest)
    dump_json(output_root / "experiment_manifest.json", manifest)


def _write_interrupted_attempt_record(
    run_dir: Path,
    task: Task,
    mode: str,
    timeout_seconds: Optional[int],
) -> None:
    """Make an interrupted, already-created attempt auditable and resumable."""
    answer_path = run_dir / "app" / "answer.json"
    duration = max(0.0, time.time() - run_dir.stat().st_mtime)
    dump_json(run_dir / "run_record.json", {
        "schema_version": "1.0",
        "task_id": task.task_id,
        "family_id": task.family_id,
        "mode": mode,
        "command": [],
        "command_display": "unavailable: recovery controller interrupted",
        "started_at": None,
        "duration_seconds": round(duration, 6),
        "duration_measurement": "estimated_from_attempt_directory_mtime",
        "timeout_seconds": timeout_seconds or int(task.data["budget"]["timeout_seconds"]),
        "timed_out": False,
        "return_code": None,
        "status": "controller_interrupted",
        "answer_present": answer_path.is_file(),
        "answer_sha256": sha256_file(answer_path) if answer_path.is_file() else None,
        "adapter_outcome": None,
        "interruption_reason": "recovery_controller_interrupted",
        "stdout_file": None,
        "stderr_file": None,
        "security_boundary": "unknown_after_controller_interruption",
    })


def recover_experiment(
    source_root: Path,
    output_root: Path,
    tasks_root: Path,
    oracle_root: Path,
    adapter: AgentAdapter,
    max_infrastructure_retries: int = 5,
    timeout_seconds: Optional[int] = None,
    retry_backoff_seconds: float = 2.0,
    resume: bool = False,
) -> Dict[str, Any]:
    """Regrade under the current contract and retry only non-model failures.

    Every source and retry attempt remains immutable in an attempt-numbered directory. The
    capability row points to the first non-infrastructure result; operational reporting reads all
    attempt telemetry, so successful retries never erase token, cost, or wall-time evidence.
    """
    if max_infrastructure_retries < 0:
        raise ContractError("max_infrastructure_retries must be non-negative")
    if retry_backoff_seconds < 0:
        raise ContractError("retry_backoff_seconds must be non-negative")
    source_manifest_path = source_root / "experiment_manifest.json"
    if not source_manifest_path.is_file():
        raise PolicyError("source experiment manifest does not exist: %s" % source_manifest_path)
    source_manifest = load_json(source_manifest_path)

    manifest_path = output_root / "experiment_manifest.json"
    if resume:
        if not manifest_path.is_file():
            raise PolicyError("cannot resume without experiment_manifest.json: %s" % output_root)
        manifest = load_json(manifest_path)
        expected_hash = manifest.get("recovery", {}).get("source_manifest_sha256")
        if expected_hash != sha256_file(source_manifest_path):
            raise PolicyError("source manifest changed since recovery began")
    else:
        if output_root.exists() and any(output_root.iterdir()):
            raise PolicyError("recovery output directory must be empty: %s" % output_root)
        output_root.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(source_manifest_path), str(output_root / "source_experiment_manifest.json"))
        source_context = source_root / "frozen_context"
        if source_context.is_dir():
            shutil.copytree(str(source_context), str(output_root / "frozen_context"))
        source_knowledge = source_root / "frozen_knowledge"
        if source_knowledge.is_dir():
            shutil.copytree(str(source_knowledge), str(output_root / "frozen_knowledge"))
        rows: List[Dict[str, Any]] = []
        manifest = {
            key: value for key, value in source_manifest.items()
            if key not in {"created_at", "rows"}
        }
        manifest.update({
            "schema_version": "1.1-recovery",
            "created_at": utc_timestamp(),
            "capability_complete": False,
            "rows": rows,
            "recovery": {
                "policy_version": "1.0",
                "source_experiment": str(source_root.resolve()),
                "source_manifest_sha256": sha256_file(source_manifest_path),
                "framework_regrade_current_contract": True,
                "infrastructure_retry_same_task_rollout_seed": True,
                "all_attempts_count_toward_operational_effort": True,
                "model_failures_score_zero": True,
                "maximum_infrastructure_retries_per_rollout": max_infrastructure_retries,
                "framework_repository": repository_fingerprint(Path(__file__).resolve().parents[2]),
                "answer_schema_sha256": sha256_file(
                    Path(__file__).resolve().parents[2] / "schemas" / (
                        "answer-v3.schema.json"
                        if source_manifest.get("rows")
                        and get_task(
                            tasks_root, source_manifest["rows"][0]["task_id"]
                        ).data.get("schema_version") == "3.0"
                        else "answer.schema.json"
                    )
                ),
            },
        })
        for source_row in source_manifest.get("rows", []):
            task = get_task(tasks_root, source_row["task_id"])
            _verify_row_bindings(task, source_row, oracle_root)
            rollout = int(source_row["rollout"])
            seed = int(source_row["seed"])
            run_dir = output_root / "runs" / task.task_id / ("rollout-%03d" % rollout) / "attempt-000"
            shutil.copytree(str(_source_run_dir(source_root, source_row)), str(run_dir))
            record, telemetry, score, regraded = _normalize_attempt(
                run_dir, task, tasks_root, oracle_root, source_manifest["model_id"],
                source_manifest["mode"], rollout, seed, True,
                source_row.get("knowledge_context"),
            )
            attempt = _attempt_summary(output_root, run_dir, 0, record, telemetry, score, regraded)
            row = dict(source_row)
            row["attempts"] = [attempt]
            row["accepted_attempt"] = None
            if attempt["classification"] == "infrastructure":
                row["resolution_status"] = "pending_infrastructure_retry"
                row["score"] = None
                row["passed"] = False
                row["score_file"] = None
                row["telemetry_file"] = attempt["telemetry_file"]
                row["status"] = attempt["status"]
            else:
                _apply_accepted_attempt(row, attempt)
            rows.append(row)
            _checkpoint(output_root, manifest)

    manifest["recovery"]["maximum_infrastructure_retries_per_rollout"] = max_infrastructure_retries
    if any(
        attempt.get("status") == "output_budget_exhausted"
        for row in manifest["rows"] for attempt in row.get("attempts", [])
    ):
        raise PolicyError(
            "output budget exhaustion requires a new uniformly frozen budget treatment; "
            "automatic same-configuration retries are invalid"
        )
    scheduler_repository = repository_fingerprint(Path(__file__).resolve().parents[2])
    scheduler_history = manifest["recovery"].setdefault("scheduler_repository_history", [])
    if scheduler_repository not in scheduler_history:
        scheduler_history.append(scheduler_repository)
    manifest["recovery"]["retry_scheduling"] = "round_robin_one_attempt_per_unresolved_row"
    shared_retry_context = None
    if manifest.get("context_snapshot", {}).get("included"):
        candidate = output_root / "frozen_context" / "context"
        if not candidate.is_dir():
            raise PolicyError("recovery is missing the frozen context snapshot")
        shared_retry_context = candidate
    while True:
        attempted_this_round = False
        for row in manifest["rows"]:
            if row.get("resolution_status") not in {"pending_infrastructure_retry", "infra_exhausted"}:
                continue
            retry_count = len(row.get("attempts", [])) - 1
            if retry_count >= max_infrastructure_retries:
                continue
            attempted_this_round = True
            task = get_task(tasks_root, row["task_id"])
            _verify_row_bindings(task, row, oracle_root)
            retry_context = (
                _knowledge_retry_context(output_root, row)
                if manifest["mode"] == "knowledge_assisted"
                else shared_retry_context
            )
            attempt_index = len(row["attempts"])
            run_dir = (
                output_root / "runs" / task.task_id / ("rollout-%03d" % int(row["rollout"]))
                / ("attempt-%03d" % attempt_index)
            )
            if retry_count and retry_backoff_seconds and not run_dir.exists():
                time.sleep(retry_backoff_seconds)
            if run_dir.exists():
                if not (run_dir / "run_record.json").is_file():
                    _write_interrupted_attempt_record(
                        run_dir, task, manifest["mode"], timeout_seconds,
                    )
            else:
                previous = _set_rollout_environment(int(row["seed"]), int(row["rollout"]))
                try:
                    run_agent_command(
                        task, run_dir,
                        adapter.command(task.task_id, int(row["rollout"]), int(row["seed"])),
                        manifest["mode"], retry_context, timeout_seconds,
                    )
                finally:
                    _restore_rollout_environment(previous)
            record, telemetry, score, regraded = _normalize_attempt(
                run_dir, task, tasks_root, oracle_root, manifest["model_id"], manifest["mode"],
                int(row["rollout"]), int(row["seed"]), False,
                row.get("knowledge_context"),
            )
            attempt = _attempt_summary(
                output_root, run_dir, attempt_index, record, telemetry, score, regraded,
            )
            _enforce_retry_controls(row, attempt, run_dir)
            row["attempts"].append(attempt)
            row["telemetry_file"] = attempt["telemetry_file"]
            row["status"] = attempt["status"]
            if attempt["status"] == "output_budget_exhausted":
                row["resolution_status"] = "output_budget_exhausted"
                _checkpoint(output_root, manifest)
                raise PolicyError(
                    "output budget exhaustion occurred during recovery for %s; "
                    "stop same-configuration retries and start a new uniformly frozen "
                    "budget treatment"
                    % row["task_id"]
                )
            if attempt["classification"] == "model":
                _apply_accepted_attempt(row, attempt)
            else:
                row["resolution_status"] = "pending_infrastructure_retry"
            _checkpoint(output_root, manifest)
        if not attempted_this_round:
            break
        if not any(
            row.get("resolution_status") in {"pending_infrastructure_retry", "infra_exhausted"}
            and len(row.get("attempts", [])) - 1 < max_infrastructure_retries
            for row in manifest["rows"]
        ):
            break
    for row in manifest["rows"]:
        if row.get("resolution_status") == "pending_infrastructure_retry":
            row["resolution_status"] = "infra_exhausted"
    _checkpoint(output_root, manifest)
    return manifest
