from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from .contracts import load_task
from .discovery import discover_tasks, get_task
from .errors import ContractError
from .graders import grade_answer
from .utils import dump_json, load_json, sha256_file


def oracle_path(oracle_root: Path, task_id: str) -> Path:
    return oracle_root / (task_id + ".oracle.json")


def grade_one(tasks_root: Path, oracle_root: Path, answer_path: Path) -> Dict[str, object]:
    answer = load_json(answer_path)
    task_id = answer.get("task_id")
    if not isinstance(task_id, str):
        raise ContractError("answer.task_id is required")
    task = get_task(tasks_root, task_id)
    oracle_file = oracle_path(oracle_root, task_id)
    if not oracle_file.is_file():
        raise ContractError("oracle not found for task: %s" % task_id)
    score = grade_answer(task, answer, load_json(oracle_file))
    score["provenance"] = {
        "answer_sha256": sha256_file(answer_path),
        "oracle_sha256": sha256_file(oracle_file),
        "task_manifest_sha256": sha256_file(task.manifest_path),
    }
    return score


def grade_directory(tasks_root: Path, oracle_root: Path, answers_root: Path, scores_root: Path) -> List[Dict[str, object]]:
    scores = []
    for answer_path in sorted(answers_root.rglob("answer.json")):
        score = grade_one(tasks_root, oracle_root, answer_path)
        output = scores_root / (str(score["task_id"]) + ".score.json")
        dump_json(output, score)
        scores.append(score)
    return scores
