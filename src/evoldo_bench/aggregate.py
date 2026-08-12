from __future__ import annotations

from collections import defaultdict
from statistics import mean, pstdev
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .telemetry import summarize_effort, wilson_interval


def failed_rollout_score(row: Mapping[str, Any]) -> Dict[str, Any]:
    """Represent every scheduled non-successful rollout as a scored zero."""
    return {
        "schema_version": "1.0",
        "task_id": str(row["task_id"]),
        "family_id": str(row["family_id"]),
        "suite": str(row["suite"]),
        "level": str(row.get("level", "unknown")),
        "variant": str(row.get("variant", "unknown")),
        "evaluation_role": str(row.get("evaluation_role", "legacy")),
        "deployment_tier": str(row.get("deployment_tier", "legacy")),
        "score": 0.0,
        "raw_score": 0.0,
        "max_score": 100.0,
        "passed": False,
        "critical_failed": ["rollout_%s" % row.get("status", "failed")],
        "checks": [],
        "rollout": row.get("rollout"),
        "seed": row.get("seed"),
        "run_status": row.get("status", "failed"),
        "synthetic_failure_score": True,
    }


def _summary(values: Sequence[float]) -> Dict[str, float]:
    if not values:
        return {"count": 0, "mean": 0.0, "stddev": 0.0, "min": 0.0, "max": 0.0}
    return {
        "count": len(values),
        "mean": round(mean(values), 6),
        "stddev": round(pstdev(values), 6) if len(values) > 1 else 0.0,
        "min": round(min(values), 6),
        "max": round(max(values), 6),
    }


def aggregate_scores(scores: Iterable[Mapping[str, Any]], mode: str = "unspecified") -> Dict[str, Any]:
    scores = list(scores)
    by_family: Dict[str, List[float]] = defaultdict(list)
    by_suite: Dict[str, List[float]] = defaultdict(list)
    by_level: Dict[str, List[float]] = defaultdict(list)
    by_variant: Dict[str, List[float]] = defaultdict(list)
    by_role: Dict[str, List[float]] = defaultdict(list)
    by_deployment_tier: Dict[str, List[float]] = defaultdict(list)
    by_dimension: Dict[str, List[float]] = defaultdict(list)
    critical_failures: Dict[str, int] = defaultdict(int)
    for score in scores:
        value = float(score["score"])
        by_family[str(score["family_id"])].append(value)
        by_suite[str(score["suite"])].append(value)
        by_level[str(score["level"])].append(value)
        by_variant[str(score["variant"])].append(value)
        by_role[str(score.get("evaluation_role", "legacy"))].append(value)
        by_deployment_tier[str(score.get("deployment_tier", "legacy"))].append(value)
        for failure in score.get("critical_failed", []):
            critical_failures[str(failure)] += 1
        for check in score.get("checks", []):
            weight = float(check.get("weight", 0.0))
            if weight <= 0:
                continue
            credit = check.get("credit_fraction")
            if credit is None:
                credit = float(check.get("earned", 0.0)) / weight
            by_dimension[str(check.get("dimension", check.get("id", "unknown")))].append(100.0 * float(credit))
    family_means = {family: mean(values) for family, values in by_family.items()}
    overall = mean(list(family_means.values())) if family_means else 0.0
    passed = sum(1 for score in scores if bool(score.get("passed")))
    return {
        "schema_version": "1.0",
        "mode": mode,
        "task_count": len(scores),
        "family_count": len(by_family),
        "family_macro_score": round(overall, 6),
        "task_pass_rate": round(passed / len(scores), 6) if scores else 0.0,
        "by_family": {key: _summary(values) for key, values in sorted(by_family.items())},
        "by_suite": {key: _summary(values) for key, values in sorted(by_suite.items())},
        "by_level": {key: _summary(values) for key, values in sorted(by_level.items())},
        "by_variant": {key: _summary(values) for key, values in sorted(by_variant.items())},
        "by_evaluation_role": {key: _summary(values) for key, values in sorted(by_role.items())},
        "by_deployment_tier": {key: _summary(values) for key, values in sorted(by_deployment_tier.items())},
        "by_scoring_dimension": {key: _summary(values) for key, values in sorted(by_dimension.items())},
        "critical_failure_counts": dict(sorted(critical_failures.items())),
    }


def paired_lift(reports: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
    direct = reports.get("direct_reasoning", {}).get("family_macro_score")
    skill = reports.get("agentic_skill", {}).get("family_macro_score")
    simulation = reports.get("simulation_assisted", {}).get("family_macro_score")
    result = {
        "skill_lift": None if direct is None or skill is None else round(float(skill) - float(direct), 6),
        "simulation_lift": None if skill is None or simulation is None else round(float(simulation) - float(skill), 6),
    }
    direct_tasks = reports.get("direct_reasoning", {}).get("task_results", {})
    skill_tasks = reports.get("agentic_skill", {}).get("task_results", {})
    simulation_tasks = reports.get("simulation_assisted", {}).get("task_results", {})
    shared = sorted(set(skill_tasks).intersection(simulation_tasks))
    if shared:
        harms = sum(1 for task_id in shared if float(simulation_tasks[task_id]) < float(skill_tasks[task_id]))
        result["simulation_harm_rate"] = round(harms / len(shared), 6)
    else:
        result["simulation_harm_rate"] = None
    return result


def aggregate_rollouts(
    scores: Iterable[Mapping[str, Any]],
    telemetry: Iterable[Mapping[str, Any]],
    model_id: str,
    mode: str,
) -> Dict[str, Any]:
    """Aggregate repeated rollouts without conflating partial spec score and Pass@1."""
    scores = list(scores)
    telemetry = list(telemetry)
    if len(scores) != len(telemetry):
        raise ValueError("every scheduled rollout requires exactly one score and one telemetry record")
    base = aggregate_scores(scores, mode=mode)
    passed = sum(1 for score in scores if bool(score.get("passed")))
    low, high = wilson_interval(passed, len(scores))
    per_task: Dict[str, List[float]] = defaultdict(list)
    tier_scores: Dict[str, List[float]] = defaultdict(list)
    tier_passes: Dict[str, int] = defaultdict(int)
    for score in scores:
        per_task[str(score["task_id"])].append(float(score["score"]))
        tier = str(score.get("deployment_tier", "legacy"))
        tier_scores[tier].append(float(score["score"]))
        tier_passes[tier] += int(bool(score.get("passed")))
    tier_readiness = {}
    for tier, values in sorted(tier_scores.items()):
        pass_rate = tier_passes[tier] / len(values)
        mean_score = mean(values)
        tier_readiness[tier] = {
            "rollout_count": len(values),
            "mean_score": round(mean_score, 6),
            "pass_at_1": round(pass_rate, 6),
            "score_gate": 70.0,
            "pass_at_1_gate": round(2.0 / 3.0, 6),
            "gate_passed": mean_score >= 70.0 and pass_rate >= 2.0 / 3.0,
        }
    effort = summarize_effort(telemetry)
    total_tokens = float(effort["total_observed_tokens"])
    token_counts = effort["token_measurement"]
    complete_tokens = token_counts["measured_rollouts"] == len(telemetry)
    score_points = sum(float(score["score"]) for score in scores)
    base.update({
        "schema_version": "1.1",
        "model_id": model_id,
        "rollout_count": len(scores),
        "pass_at_1": round(passed / len(scores), 6) if scores else 0.0,
        "pass_at_1_ci95": [round(low, 6), round(high, 6)],
        "spec_score": round(mean(float(score["score"]) for score in scores) / 100.0, 6) if scores else 0.0,
        "task_results": {task_id: round(mean(values), 6) for task_id, values in sorted(per_task.items())},
        "tier_readiness": tier_readiness,
        "scheduled_rollouts": len(telemetry),
        "failed_rollouts": sum(float(score["score"]) == 0.0 and bool(score.get("synthetic_failure_score")) for score in scores),
        "effort": effort,
        "token_efficiency": {
            "measurement_complete": complete_tokens,
            "tokens_per_score_point": round(total_tokens / score_points, 6) if complete_tokens and score_points else None,
            "tokens_per_pass": round(total_tokens / passed, 6) if complete_tokens and passed else None,
            "score_points_per_million_tokens": round(score_points * 1_000_000.0 / total_tokens, 6) if complete_tokens and total_tokens else None,
            "observed_tokens_per_score_point_lower_bound": round(total_tokens / score_points, 6) if total_tokens and score_points else None,
            "observed_tokens_per_pass_lower_bound": round(total_tokens / passed, 6) if total_tokens and passed else None,
        },
    })
    return base
