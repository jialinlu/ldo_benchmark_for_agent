from __future__ import annotations

from statistics import mean
from typing import Any, Dict, Iterable, List, Mapping

from .errors import ContractError


def calibrate_judges(
    human_records: Iterable[Mapping[str, Any]],
    judge_records: Iterable[Mapping[str, Any]],
    max_mae: float = 10.0,
    minimum_critical_recall: float = 0.9,
    minimum_label_agreement: float = 0.8,
) -> Dict[str, Any]:
    """Evaluate frozen judge outputs against adjudicated human records.

    This function never calls a model. Judge prompts/model snapshots must be frozen externally and
    their outputs supplied as records, which keeps calibration replayable and air-gap compatible.
    """
    humans = {str(row.get("item_id")): row for row in human_records}
    judges: Dict[str, Dict[str, Mapping[str, Any]]] = {}
    for row in judge_records:
        item_id = str(row.get("item_id"))
        judge_id = str(row.get("judge_id"))
        if not item_id or not judge_id:
            raise ContractError("judge records require item_id and judge_id")
        judges.setdefault(judge_id, {})[item_id] = row
    if not humans or len(judges) < 2:
        raise ContractError("calibration requires human records and at least two judges")
    per_judge: Dict[str, Any] = {}
    for judge_id, rows in sorted(judges.items()):
        shared = sorted(set(humans).intersection(rows))
        if not shared:
            raise ContractError("judge %s has no shared calibration items" % judge_id)
        errors = []
        label_matches = 0
        critical_total = 0
        critical_found = 0
        for item_id in shared:
            human = humans[item_id]
            judge = rows[item_id]
            errors.append(abs(float(judge["score"]) - float(human["adjudicated_score"])))
            label_matches += int(judge.get("label") == human.get("adjudicated_label"))
            if bool(human.get("critical_error")):
                critical_total += 1
                critical_found += int(bool(judge.get("critical_error")))
        mae = mean(errors)
        agreement = label_matches / len(shared)
        recall = critical_found / critical_total if critical_total else 1.0
        passed = mae <= max_mae and agreement >= minimum_label_agreement and recall >= minimum_critical_recall
        per_judge[judge_id] = {
            "items": len(shared),
            "mae": round(mae, 6),
            "label_agreement": round(agreement, 6),
            "critical_error_recall": round(recall, 6),
            "passed": passed,
        }
    all_passed = all(row["passed"] for row in per_judge.values())
    return {
        "schema_version": "1.0",
        "passed": all_passed,
        "thresholds": {
            "max_mae": max_mae,
            "minimum_critical_recall": minimum_critical_recall,
            "minimum_label_agreement": minimum_label_agreement,
        },
        "judges": per_judge,
        "automation_allowed": all_passed,
        "rule": "failed calibration or inter-judge disagreement routes explanation scoring to human review",
    }


def combine_judges(records: Iterable[Mapping[str, Any]], score_tolerance: float = 10.0) -> Dict[str, Any]:
    rows = list(records)
    if len(rows) != 2 or len({row.get("judge_id") for row in rows}) != 2:
        raise ContractError("exactly two heterogeneous judge records are required")
    labels = {row.get("label") for row in rows}
    critical = {bool(row.get("critical_error")) for row in rows}
    scores = [float(row["score"]) for row in rows]
    disagreement = len(labels) != 1 or len(critical) != 1 or abs(scores[0] - scores[1]) > score_tolerance
    return {
        "schema_version": "1.0",
        "status": "HUMAN_REVIEW" if disagreement else "AGREED",
        "score": None if disagreement else round(mean(scores), 6),
        "label": None if disagreement else next(iter(labels)),
        "critical_error": None if disagreement else next(iter(critical)),
        "judge_ids": sorted(str(row["judge_id"]) for row in rows),
    }
