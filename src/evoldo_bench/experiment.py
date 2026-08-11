from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .adapters import AgentAdapter
from .contracts import ALLOWED_MODES, Task
from .discovery import discover_tasks
from .errors import ContractError, PolicyError
from .grading import grade_one
from .probes import evaluate_probe_contract
from .runner import run_agent_command
from .telemetry import empty_telemetry, validate_telemetry
from .utils import dump_json, load_json, relative_hashes, sha256_file, sha256_text, utc_timestamp


def snapshot_context(source: Optional[Path], snapshot_root: Path) -> Dict[str, Any]:
    snapshot_root.mkdir(parents=True, exist_ok=True)
    if source is None:
        return {"included": False, "files": {}, "snapshot_id": sha256_text("empty-context")}
    if not source.is_dir():
        raise PolicyError("context directory does not exist: %s" % source)
    symlinks = [path for path in source.rglob("*") if path.is_symlink()]
    if symlinks:
        raise PolicyError("context snapshot contains symbolic links: %s" % symlinks[0])
    destination = snapshot_root / "context"
    shutil.copytree(str(source), str(destination))
    files = relative_hashes(destination)
    snapshot_id = sha256_text("\n".join("%s:%s" % item for item in sorted(files.items())))
    manifest = {"included": True, "source_name": source.name, "files": files, "snapshot_id": snapshot_id}
    dump_json(snapshot_root / "context_snapshot.json", manifest)
    for path in destination.rglob("*"):
        if path.is_file():
            path.chmod(0o444)
    return manifest


def _load_agent_telemetry(path: Path, fallback: Dict[str, Any]) -> Dict[str, Any]:
    if not path.is_file():
        return fallback
    supplied = load_json(path)
    # Identity fields are controlled by the runner, never by an untrusted agent.
    for field in ("task_id", "model_id", "mode", "rollout", "seed"):
        supplied[field] = fallback[field]
    supplied.setdefault("schema_version", "1.0")
    supplied.setdefault("wall_seconds", fallback["wall_seconds"])
    supplied.setdefault("steps", 0)
    supplied.setdefault("tool_calls", 0)
    supplied.setdefault("token_breakdown", {})
    supplied.setdefault("cost_breakdown_usd", {})
    if "token_measurement_status" not in supplied:
        token_values = supplied["token_breakdown"].values()
        supplied["token_measurement_status"] = "partial" if any(value is not None for value in token_values) else "unavailable"
    if "cost_measurement_status" not in supplied:
        cost_values = supplied["cost_breakdown_usd"].values()
        supplied["cost_measurement_status"] = "partial" if any(value is not None for value in cost_values) else "unavailable"
    supplied.setdefault("provider_reported_model_id", None)
    supplied.setdefault("model_identity_status", "unavailable")
    supplied["source"] = "agent_adapter"
    return validate_telemetry(supplied)


def _normalize_tool_ledger(path: Path, task: Task) -> Dict[str, Any]:
    if not path.is_file():
        return {"schema_version": "1.0", "entries": [], "policy_rejections": 0, "ineffective_calls": 0}
    raw = load_json(path)
    entries = raw.get("entries", [])
    if not isinstance(entries, list):
        raise ContractError("tool_ledger.entries must be a list")
    normalized = []
    rejected = 0
    ineffective = 0
    available = list(task.data["input_files"])
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or not isinstance(entry.get("probe"), dict):
            gate = {"passed": False, "violations": [{"code": "MISSING_PROBE_CONTRACT", "detail": "entry requires probe"}]}
        else:
            gate = evaluate_probe_contract(entry["probe"], task, available)
        rejected += int(not gate["passed"])
        effective = bool(gate["passed"] and entry.get("status") == "OK" and entry.get("evidence_used"))
        ineffective += int(not effective)
        normalized.append({
            "index": index,
            "probe_gate": gate,
            "status": entry.get("status", "UNDECLARED"),
            "evidence_sha256": entry.get("evidence_sha256"),
            "evidence_used": bool(entry.get("evidence_used")),
            "effective": effective,
        })
    return {"schema_version": "1.0", "entries": normalized, "policy_rejections": rejected, "ineffective_calls": ineffective}


def run_experiment(
    tasks_root: Path,
    oracle_root: Path,
    output_root: Path,
    adapter: AgentAdapter,
    model_id: str,
    mode: str,
    rollouts: int = 3,
    base_seed: int = 2026,
    context_dir: Optional[Path] = None,
    task_ids: Optional[Iterable[str]] = None,
    timeout_seconds: Optional[int] = None,
    pairing_modes: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    if mode not in ALLOWED_MODES:
        raise ContractError("unsupported experiment mode: %s" % mode)
    if rollouts <= 0:
        raise ContractError("rollouts must be positive")
    if output_root.exists() and any(output_root.iterdir()):
        raise PolicyError("experiment output directory must be empty: %s" % output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    context_manifest = snapshot_context(context_dir, output_root / "frozen_context")
    frozen_context = output_root / "frozen_context" / "context" if context_manifest["included"] else None
    wanted = set(task_ids or [])
    required_modes = set(pairing_modes or [mode])
    unsupported = sorted(required_modes.difference(ALLOWED_MODES))
    if unsupported:
        raise ContractError("unsupported pairing modes: %s" % ", ".join(unsupported))
    tasks = [task for task in discover_tasks(tasks_root) if not wanted or task.task_id in wanted]
    if wanted.difference(task.task_id for task in tasks):
        raise ContractError("unknown task ids: %s" % ", ".join(sorted(wanted.difference(task.task_id for task in tasks))))
    tasks = [task for task in tasks if required_modes.issubset(set(task.data["eligible_modes"]))]
    rows: List[Dict[str, Any]] = []
    for task in tasks:
        if mode not in task.data["eligible_modes"]:
            continue
        for rollout in range(rollouts):
            seed = base_seed + rollout
            run_dir = output_root / "runs" / task.task_id / ("rollout-%03d" % rollout)
            command = adapter.command(task.task_id, rollout, seed)
            previous_seed = os.environ.get("EVOLDO_SEED")
            previous_rollout = os.environ.get("EVOLDO_ROLLOUT")
            os.environ["EVOLDO_SEED"] = str(seed)
            os.environ["EVOLDO_ROLLOUT"] = str(rollout)
            try:
                record = run_agent_command(task, run_dir, command, mode, frozen_context, timeout_seconds)
            finally:
                if previous_seed is None:
                    os.environ.pop("EVOLDO_SEED", None)
                else:
                    os.environ["EVOLDO_SEED"] = previous_seed
                if previous_rollout is None:
                    os.environ.pop("EVOLDO_ROLLOUT", None)
                else:
                    os.environ["EVOLDO_ROLLOUT"] = previous_rollout
            fallback = empty_telemetry(task.task_id, model_id, mode, rollout, seed, float(record["duration_seconds"]))
            telemetry = _load_agent_telemetry(run_dir / "app" / "telemetry.json", fallback)
            telemetry.setdefault("milestones", {})
            telemetry["milestones"].setdefault("terminal_seconds", float(record["duration_seconds"]))
            terminal_status = {
                "ok": "completed", "provider_timeout": "infra_fail", "provider_infra_fail": "infra_fail",
                "timeout": "timeout", "format_fail": "format_fail", "model_incomplete": "model_incomplete",
            }.get(str(record["status"]), "model_incomplete")
            if telemetry.get("source") == "runner_fallback":
                telemetry["milestones"]["terminal_status"] = terminal_status
            else:
                telemetry["milestones"].setdefault("terminal_status", terminal_status)
            ledger = _normalize_tool_ledger(run_dir / "app" / "tool_ledger.json", task)
            declared_calls = len(ledger["entries"])
            if telemetry["tool_calls"] and not declared_calls:
                record["status"] = "policy_fail"
                record["policy_failure"] = "tool_calls_without_ledger"
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
            dump_json(run_dir / "run_record.json", record)
            score = None
            if record["answer_present"]:
                try:
                    score = grade_one(tasks_root, oracle_root, run_dir / "app" / "answer.json")
                except (ContractError, ValueError, OSError) as exc:
                    record["status"] = "format_fail"
                    record["answer_error"] = str(exc)
                else:
                    score["rollout"] = rollout
                    score["seed"] = seed
                    score["run_status"] = record["status"]
                    dump_json(run_dir / "score.json", score)
            dump_json(run_dir / "run_record.json", record)
            dump_json(run_dir / "telemetry.normalized.json", telemetry)
            dump_json(run_dir / "tool_ledger.normalized.json", ledger)
            rows.append({
                "task_id": task.task_id,
                "family_id": task.family_id,
                "suite": task.suite,
                "level": task.data["level"],
                "variant": task.variant,
                "rollout": rollout,
                "seed": seed,
                "mode": mode,
                "task_manifest_sha256": sha256_file(task.manifest_path),
                "answer_contract_sha256": sha256_file(task.source_path(task.data["answer_template_file"])),
                "budget": task.data["budget"],
                "status": record["status"],
                "answer_present": record["answer_present"],
                "score": score["score"] if score else None,
                "passed": score["passed"] if score else False,
                "telemetry_file": str((run_dir / "telemetry.normalized.json").relative_to(output_root)),
                "score_file": str((run_dir / "score.json").relative_to(output_root)) if score else None,
            })
    manifest = {
        "schema_version": "1.0",
        "created_at": utc_timestamp(),
        "model_id": model_id,
        "mode": mode,
        "rollouts_per_task": rollouts,
        "base_seed": base_seed,
        "seed_semantics": "rollout scheduling identifier; provider sampling determinism is adapter-dependent",
        "pairing_modes": sorted(required_modes),
        "task_count": len({row["task_id"] for row in rows}),
        "run_count": len(rows),
        "context_snapshot": context_manifest,
        "rows": rows,
    }
    dump_json(output_root / "experiment_manifest.json", manifest)
    return manifest


def compare_treatments(manifests: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    if len(manifests) < 2:
        raise ContractError("at least two experiment manifests are required")
    model_ids = {manifest.get("model_id") for manifest in manifests}
    violations: List[Dict[str, str]] = []
    if len(model_ids) != 1:
        violations.append({"code": "MODEL_MISMATCH", "detail": "paired treatments must use the same model_id"})

    def index(manifest: Dict[str, Any]) -> Dict[Any, Dict[str, Any]]:
        return {(row["task_id"], row["rollout"], row["seed"]): row for row in manifest.get("rows", [])}

    baseline = index(manifests[0])
    for manifest in manifests[1:]:
        current = index(manifest)
        if set(current) != set(baseline):
            violations.append({"code": "ROLLOUT_MATRIX_MISMATCH", "detail": "task/rollout/seed keys differ"})
            continue
        for key in sorted(baseline):
            left, right = baseline[key], current[key]
            for field in ("task_manifest_sha256", "answer_contract_sha256", "budget"):
                if left.get(field) != right.get(field):
                    violations.append({"code": "CONTROL_MISMATCH", "detail": "%s differs for %s" % (field, key[0])})
    return {
        "schema_version": "1.0",
        "passed": not violations,
        "model_id": next(iter(model_ids)) if len(model_ids) == 1 else None,
        "modes": [manifest.get("mode") for manifest in manifests],
        "paired_rows": len(baseline),
        "violations": violations,
    }
