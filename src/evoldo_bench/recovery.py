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
from .errors import ContractError, PolicyError
from .experiment import _load_agent_telemetry, _normalize_tool_ledger
from .grading import grade_one
from .provenance import repository_fingerprint
from .runner import run_agent_command
from .telemetry import empty_telemetry
from .utils import dump_json, load_json, safe_relative_path, sha256_file, utc_timestamp


INFRASTRUCTURE_STATUSES = frozenset({
    "failed",
    "provider_infra_fail",
    "provider_timeout",
    "timeout",
    "model_identity_mismatch",
})


def classify_attempt(record: Dict[str, Any], telemetry: Dict[str, Any]) -> str:
    """Separate provider/runner failures from model-attributable outcomes."""
    if telemetry.get("model_identity_status") == "mismatch":
        return "infrastructure"
    adapter_status = (record.get("adapter_outcome") or {}).get("status")
    if adapter_status in {"provider_infra_fail", "provider_timeout"}:
        return "infrastructure"
    if record.get("timed_out") is True:
        return "infrastructure"
    if record.get("status") in INFRASTRUCTURE_STATUSES:
        return "infrastructure"
    return "model"


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

    original_status = record.get("status")
    score = None
    framework_regraded = False
    if classify_attempt(record, telemetry) != "infrastructure":
        answer_path = run_dir / "app" / "answer.json"
        if answer_path.is_file() and original_status in {"ok", "format_fail"}:
            try:
                score = grade_one(tasks_root, oracle_root, answer_path)
            except (ContractError, ValueError, OSError) as exc:
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
        "run_record_file": str((run_dir / "run_record.json").relative_to(output_root)),
        "telemetry_file": str((run_dir / "telemetry.normalized.json").relative_to(output_root)),
        "score_file": str((run_dir / "score.json").relative_to(output_root)) if score else None,
    }


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


def _refresh_recovery_summary(manifest: Dict[str, Any]) -> None:
    attempts = [attempt for row in manifest["rows"] for attempt in row.get("attempts", [])]
    unresolved = [
        row for row in manifest["rows"]
        if row.get("resolution_status") in {"pending_infrastructure_retry", "infra_exhausted"}
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
                    Path(__file__).resolve().parents[2] / "schemas" / "answer.schema.json"
                ),
            },
        })
        for source_row in source_manifest.get("rows", []):
            task = get_task(tasks_root, source_row["task_id"])
            rollout = int(source_row["rollout"])
            seed = int(source_row["seed"])
            run_dir = output_root / "runs" / task.task_id / ("rollout-%03d" % rollout) / "attempt-000"
            shutil.copytree(str(_source_run_dir(source_root, source_row)), str(run_dir))
            record, telemetry, score, regraded = _normalize_attempt(
                run_dir, task, tasks_root, oracle_root, source_manifest["model_id"],
                source_manifest["mode"], rollout, seed, True,
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
    retry_context = None
    if manifest.get("context_snapshot", {}).get("included"):
        candidate = output_root / "frozen_context" / "context"
        if not candidate.is_dir():
            raise PolicyError("recovery is missing the frozen context snapshot")
        retry_context = candidate
    for row in manifest["rows"]:
        if row.get("resolution_status") not in {"pending_infrastructure_retry", "infra_exhausted"}:
            continue
        task = get_task(tasks_root, row["task_id"])
        retry_count = len(row.get("attempts", [])) - 1
        while retry_count < max_infrastructure_retries:
            attempt_index = len(row["attempts"])
            run_dir = (
                output_root / "runs" / task.task_id / ("rollout-%03d" % int(row["rollout"]))
                / ("attempt-%03d" % attempt_index)
            )
            if run_dir.exists():
                raise PolicyError("unrecorded retry attempt directory exists: %s" % run_dir)
            if retry_count and retry_backoff_seconds:
                time.sleep(retry_backoff_seconds)
            previous = _set_rollout_environment(int(row["seed"]), int(row["rollout"]))
            try:
                record = run_agent_command(
                    task, run_dir,
                    adapter.command(task.task_id, int(row["rollout"]), int(row["seed"])),
                    manifest["mode"], retry_context, timeout_seconds,
                )
            finally:
                _restore_rollout_environment(previous)
            record, telemetry, score, regraded = _normalize_attempt(
                run_dir, task, tasks_root, oracle_root, manifest["model_id"], manifest["mode"],
                int(row["rollout"]), int(row["seed"]), False,
            )
            attempt = _attempt_summary(
                output_root, run_dir, attempt_index, record, telemetry, score, regraded,
            )
            row["attempts"].append(attempt)
            retry_count += 1
            row["telemetry_file"] = attempt["telemetry_file"]
            row["status"] = attempt["status"]
            if attempt["classification"] == "model":
                _apply_accepted_attempt(row, attempt)
                _checkpoint(output_root, manifest)
                break
            row["resolution_status"] = "pending_infrastructure_retry"
            _checkpoint(output_root, manifest)
        if row.get("resolution_status") == "pending_infrastructure_retry":
            row["resolution_status"] = "infra_exhausted"
            _checkpoint(output_root, manifest)
    _checkpoint(output_root, manifest)
    return manifest
