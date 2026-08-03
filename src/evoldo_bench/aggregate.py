from __future__ import annotations

from collections import defaultdict
from statistics import mean, pstdev
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .telemetry import summarize_effort, wilson_interval


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
    critical_failures: Dict[str, int] = defaultdict(int)
    for score in scores:
        value = float(score["score"])
        by_family[str(score["family_id"])].append(value)
        by_suite[str(score["suite"])].append(value)
        by_level[str(score["level"])].append(value)
        by_variant[str(score["variant"])].append(value)
        for failure in score.get("critical_failed", []):
            critical_failures[str(failure)] += 1
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
    base = aggregate_scores(scores, mode=mode)
    passed = sum(1 for score in scores if bool(score.get("passed")))
    low, high = wilson_interval(passed, len(scores))
    per_task: Dict[str, List[float]] = defaultdict(list)
    for score in scores:
        per_task[str(score["task_id"])].append(float(score["score"]))
    base.update({
        "schema_version": "1.1",
        "model_id": model_id,
        "rollout_count": len(scores),
        "pass_at_1": round(passed / len(scores), 6) if scores else 0.0,
        "pass_at_1_ci95": [round(low, 6), round(high, 6)],
        "spec_score": round(mean(float(score["score"]) for score in scores) / 100.0, 6) if scores else 0.0,
        "task_results": {task_id: round(mean(values), 6) for task_id, values in sorted(per_task.items())},
        "effort": summarize_effort(telemetry),
    })
    return base
