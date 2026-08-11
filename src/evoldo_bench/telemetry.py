from __future__ import annotations

import math
from statistics import mean
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .errors import ContractError

TOKEN_FIELDS = ("input", "cached_input", "output", "reasoning", "cache_write")
COST_FIELDS = TOKEN_FIELDS
MEASUREMENT_STATUSES = {"measured", "partial", "unavailable"}


def _nonnegative_number(value: Any, field: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
        raise ContractError("%s must be a non-negative number" % field)
    return float(value)


def _optional_nonnegative_number(value: Any, field: str) -> Optional[float]:
    if value is None:
        return None
    return _nonnegative_number(value, field)


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
    token_status = data.get("token_measurement_status", "measured")
    cost_status = data.get("cost_measurement_status", "measured")
    if token_status not in MEASUREMENT_STATUSES:
        raise ContractError("unsupported telemetry.token_measurement_status")
    if cost_status not in MEASUREMENT_STATUSES:
        raise ContractError("unsupported telemetry.cost_measurement_status")
    data["token_measurement_status"] = token_status
    data["cost_measurement_status"] = cost_status
    for group_name, fields, status in (
        ("token_breakdown", TOKEN_FIELDS, token_status),
        ("cost_breakdown_usd", COST_FIELDS, cost_status),
    ):
        group = data[group_name]
        if not isinstance(group, dict):
            raise ContractError("telemetry.%s must be an object" % group_name)
        unknown = sorted(set(group).difference(fields))
        if unknown:
            raise ContractError("telemetry.%s has unsupported fields: %s" % (group_name, ", ".join(unknown)))
        values = []
        for field in fields:
            value = group.get(field)
            values.append(_optional_nonnegative_number(value, "telemetry.%s.%s" % (group_name, field)))
        if status == "measured" and any(value is None for value in values):
            raise ContractError("telemetry.%s measured status requires every field" % group_name)
        if status == "unavailable" and any(value is not None for value in values):
            raise ContractError("telemetry.%s unavailable status requires null fields" % group_name)
    if "infra_status" in data and data["infra_status"] not in {"ok", "infra_fail", "not_used"}:
        raise ContractError("unsupported telemetry.infra_status")
    milestones = data.get("milestones", {})
    if not isinstance(milestones, dict):
        raise ContractError("telemetry.milestones must be an object")
    for field in ("first_feasible_seconds", "terminal_seconds", "first_feasible_tokens", "terminal_tokens"):
        if field in milestones:
            _optional_nonnegative_number(milestones[field], "telemetry.milestones.%s" % field)
    if "terminal_status" in milestones and milestones["terminal_status"] not in {
        "completed", "model_declined", "model_incomplete", "format_fail", "infra_fail", "timeout"
    }:
        raise ContractError("unsupported telemetry.milestones.terminal_status")
    if "terminal_tokens_status" in milestones and milestones["terminal_tokens_status"] not in MEASUREMENT_STATUSES:
        raise ContractError("unsupported telemetry.milestones.terminal_tokens_status")
    data["milestones"] = milestones
    identity_status = data.get("model_identity_status", "unavailable")
    if identity_status not in {"attested", "requested_only", "mismatch", "unavailable"}:
        raise ContractError("unsupported telemetry.model_identity_status")
    reported = data.get("provider_reported_model_id")
    if reported is not None and (not isinstance(reported, str) or not reported.strip()):
        raise ContractError("telemetry.provider_reported_model_id must be null or a non-empty string")
    if identity_status in {"attested", "requested_only", "mismatch"} and reported is None:
        raise ContractError("model identity status requires provider_reported_model_id")
    data["model_identity_status"] = identity_status
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
        "token_breakdown": {field: None for field in TOKEN_FIELDS},
        "cost_breakdown_usd": {field: None for field in COST_FIELDS},
        "token_measurement_status": "unavailable",
        "cost_measurement_status": "unavailable",
        "provider_reported_model_id": None,
        "model_identity_status": "unavailable",
        "infra_status": "not_used",
        "source": "runner_fallback",
        "milestones": {
            "first_feasible_seconds": None,
            "terminal_seconds": round(max(0.0, wall_seconds), 6),
            "first_feasible_tokens": None,
            "terminal_tokens": None,
            "terminal_status": "model_incomplete",
        },
    }


def wilson_interval(successes: int, total: int, z: float = 1.959963984540054) -> Tuple[float, float]:
    if total <= 0:
        return (0.0, 0.0)
    p = successes / total
    denominator = 1.0 + z * z / total
    centre = (p + z * z / (2.0 * total)) / denominator
    half = z * math.sqrt((p * (1.0 - p) + z * z / (4.0 * total)) / total) / denominator
    return (max(0.0, centre - half), min(1.0, centre + half))


def _avg(values: Sequence[float]) -> Optional[float]:
    return round(mean(values), 6) if values else None


def summarize_effort(rows: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    rows = list(rows)
    for row in rows:
        validate_telemetry(dict(row))
    token_totals: Dict[str, List[float]] = {field: [] for field in TOKEN_FIELDS}
    cost_totals: Dict[str, List[float]] = {field: [] for field in COST_FIELDS}
    for row in rows:
        for field in TOKEN_FIELDS:
            token_value = row["token_breakdown"].get(field)
            cost_value = row["cost_breakdown_usd"].get(field)
            if token_value is not None:
                token_totals[field].append(float(token_value))
            if cost_value is not None:
                cost_totals[field].append(float(cost_value))
    avg_token_breakdown = {field: _avg(values) for field, values in token_totals.items()}
    avg_cost_breakdown = {field: _avg(values) for field, values in cost_totals.items()}
    cached = sum(token_totals["cached_input"])
    input_like = cached + sum(token_totals["input"])
    total_observed_tokens = sum(
        sum(token_totals[field]) for field in ("input", "cached_input", "output", "reasoning")
    )
    measured_token_rollouts = sum(row["token_measurement_status"] == "measured" for row in rows)
    partial_token_rollouts = sum(row["token_measurement_status"] == "partial" for row in rows)
    measured_cost_rollouts = sum(row["cost_measurement_status"] == "measured" for row in rows)
    provider_costs = [
        float(row["provider_total_cost_usd"]) for row in rows
        if isinstance(row.get("provider_total_cost_usd"), (int, float))
        and not isinstance(row.get("provider_total_cost_usd"), bool)
    ]
    known_output = [value for field in ("output", "reasoning") for value in token_totals[field]]
    probe_calls = sum(int(row.get("probe_calls", 0)) for row in rows)
    ineffective = sum(int(row.get("ineffective_probe_calls", 0)) for row in rows)
    rejected = sum(int(row.get("policy_rejected_probe_calls", 0)) for row in rows)
    first_feasible_seconds = [float(row["milestones"]["first_feasible_seconds"]) for row in rows
                              if row.get("milestones", {}).get("first_feasible_seconds") is not None]
    terminal_seconds = [float(row["milestones"]["terminal_seconds"]) for row in rows
                        if row.get("milestones", {}).get("terminal_seconds") is not None]
    terminal_tokens = [float(row["milestones"]["terminal_tokens"]) for row in rows
                       if row.get("milestones", {}).get("terminal_tokens") is not None]
    return {
        "rollouts": len(rows),
        "avg_steps": _avg([float(row["steps"]) for row in rows]),
        "avg_tool_calls": _avg([float(row["tool_calls"]) for row in rows]),
        "avg_wall_seconds": _avg([float(row["wall_seconds"]) for row in rows]),
        "avg_output_tokens": (
            round((avg_token_breakdown["output"] or 0.0) + (avg_token_breakdown["reasoning"] or 0.0), 6)
            if known_output else None
        ),
        "total_observed_tokens": round(total_observed_tokens, 6),
        "avg_total_cost_usd": (
            round(mean(provider_costs), 6) if provider_costs and len(provider_costs) == len(rows)
            else round(sum(value or 0.0 for value in avg_cost_breakdown.values()), 6)
            if measured_cost_rollouts == len(rows) else None
        ),
        "total_observed_cost_usd": round(sum(provider_costs), 6) if provider_costs else None,
        "avg_token_breakdown": avg_token_breakdown,
        "avg_cost_breakdown_usd": avg_cost_breakdown,
        "token_measurement": {
            "measured_rollouts": measured_token_rollouts,
            "partial_rollouts": partial_token_rollouts,
            "unavailable_rollouts": len(rows) - measured_token_rollouts - partial_token_rollouts,
        },
        "cost_measurement": {
            "measured_rollouts": measured_cost_rollouts,
            "unavailable_or_partial_rollouts": len(rows) - measured_cost_rollouts,
        },
        "cached_input_share": round(cached / input_like, 6) if input_like else None,
        "ineffective_probe_rate": round(ineffective / probe_calls, 6) if probe_calls else 0.0,
        "probe_policy_rejection_rate": round(rejected / probe_calls, 6) if probe_calls else 0.0,
        "milestones": {
            "avg_first_feasible_seconds": _avg(first_feasible_seconds),
            "avg_terminal_seconds": _avg(terminal_seconds),
            "avg_terminal_tokens": _avg(terminal_tokens),
            "terminal_token_coverage": round(len(terminal_tokens) / len(rows), 6) if rows else 0.0,
        },
    }
