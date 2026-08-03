from __future__ import annotations

import math
from statistics import mean
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .errors import ContractError

TOKEN_FIELDS = ("input", "cached_input", "output", "reasoning", "cache_write")
COST_FIELDS = TOKEN_FIELDS


def _nonnegative_number(value: Any, field: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
        raise ContractError("%s must be a non-negative number" % field)
    return float(value)


def validate_telemetry(data: Dict[str, Any]) -> Dict[str, Any]:
    required = {
        "schema_version", "task_id", "model_id", "mode", "rollout", "seed",
        "steps", "tool_calls", "wall_seconds", "token_breakdown", "cost_breakdown_usd",
    }
    missing = sorted(required.difference(data))
    if missing:
        raise ContractError("telemetry missing required fields: %s" % ", ".join(missing))
    if data["schema_version"] != "1.0":
        raise ContractError("unsupported telemetry schema_version")
    for field in ("task_id", "model_id", "mode"):
        if not isinstance(data[field], str) or not data[field].strip():
            raise ContractError("telemetry.%s must be a non-empty string" % field)
    for field in ("rollout", "seed", "steps", "tool_calls"):
        if not isinstance(data[field], int) or isinstance(data[field], bool) or data[field] < 0:
            raise ContractError("telemetry.%s must be a non-negative integer" % field)
    _nonnegative_number(data["wall_seconds"], "telemetry.wall_seconds")
    for group_name, fields in (("token_breakdown", TOKEN_FIELDS), ("cost_breakdown_usd", COST_FIELDS)):
        group = data[group_name]
        if not isinstance(group, dict):
            raise ContractError("telemetry.%s must be an object" % group_name)
        unknown = sorted(set(group).difference(fields))
        if unknown:
            raise ContractError("telemetry.%s has unsupported fields: %s" % (group_name, ", ".join(unknown)))
        for field in fields:
            _nonnegative_number(group.get(field, 0), "telemetry.%s.%s" % (group_name, field))
    if "infra_status" in data and data["infra_status"] not in {"ok", "infra_fail", "not_used"}:
        raise ContractError("unsupported telemetry.infra_status")
    return data


def empty_telemetry(task_id: str, model_id: str, mode: str, rollout: int, seed: int, wall_seconds: float) -> Dict[str, Any]:
    return {
        "schema_version": "1.0",
        "task_id": task_id,
        "model_id": model_id,
        "mode": mode,
        "rollout": rollout,
        "seed": seed,
        "steps": 0,
        "tool_calls": 0,
        "wall_seconds": round(max(0.0, wall_seconds), 6),
        "token_breakdown": {field: 0 for field in TOKEN_FIELDS},
        "cost_breakdown_usd": {field: 0.0 for field in COST_FIELDS},
        "infra_status": "not_used",
        "source": "runner_fallback",
    }


def wilson_interval(successes: int, total: int, z: float = 1.959963984540054) -> Tuple[float, float]:
    if total <= 0:
        return (0.0, 0.0)
    p = successes / total
    denominator = 1.0 + z * z / total
    centre = (p + z * z / (2.0 * total)) / denominator
    half = z * math.sqrt((p * (1.0 - p) + z * z / (4.0 * total)) / total) / denominator
    return (max(0.0, centre - half), min(1.0, centre + half))


def _avg(values: Sequence[float]) -> float:
    return round(mean(values), 6) if values else 0.0


def summarize_effort(rows: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    rows = list(rows)
    for row in rows:
        validate_telemetry(dict(row))
    token_totals = {field: [] for field in TOKEN_FIELDS}
    cost_totals = {field: [] for field in COST_FIELDS}
    for row in rows:
        for field in TOKEN_FIELDS:
            token_totals[field].append(float(row["token_breakdown"].get(field, 0)))
            cost_totals[field].append(float(row["cost_breakdown_usd"].get(field, 0)))
    avg_token_breakdown = {field: _avg(values) for field, values in token_totals.items()}
    avg_cost_breakdown = {field: _avg(values) for field, values in cost_totals.items()}
    cached = sum(float(row["token_breakdown"].get("cached_input", 0)) for row in rows)
    input_like = cached + sum(float(row["token_breakdown"].get("input", 0)) for row in rows)
    probe_calls = sum(int(row.get("probe_calls", 0)) for row in rows)
    ineffective = sum(int(row.get("ineffective_probe_calls", 0)) for row in rows)
    rejected = sum(int(row.get("policy_rejected_probe_calls", 0)) for row in rows)
    return {
        "rollouts": len(rows),
        "avg_steps": _avg([float(row["steps"]) for row in rows]),
        "avg_tool_calls": _avg([float(row["tool_calls"]) for row in rows]),
        "avg_wall_seconds": _avg([float(row["wall_seconds"]) for row in rows]),
        "avg_output_tokens": avg_token_breakdown["output"] + avg_token_breakdown["reasoning"],
        "avg_total_cost_usd": round(sum(avg_cost_breakdown.values()), 6),
        "avg_token_breakdown": avg_token_breakdown,
        "avg_cost_breakdown_usd": avg_cost_breakdown,
        "cached_input_share": round(cached / input_like, 6) if input_like else 0.0,
        "ineffective_probe_rate": round(ineffective / probe_calls, 6) if probe_calls else 0.0,
        "probe_policy_rejection_rate": round(rejected / probe_calls, 6) if probe_calls else 0.0,
    }
