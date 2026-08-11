from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from .bundle import audit_public_task_source
from .contracts import Task
from .discovery import discover_tasks
from .utils import iter_files, load_json, sha256_file, sha256_text

TOKEN_RE = re.compile(r"[A-Za-z0-9_.$+-]+")


def _tokens(text: str) -> Set[str]:
    return {token.lower() for token in TOKEN_RE.findall(text) if len(token) >= 4}


def _jaccard(left: Set[str], right: Set[str]) -> float:
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    return len(left.intersection(right)) / len(left.union(right))


def audit_task_collection(tasks_root: Path, oracle_root: Optional[Path] = None, similarity_threshold: float = 0.92) -> Dict[str, Any]:
    tasks = discover_tasks(tasks_root)
    violations: List[Dict[str, Any]] = []
    family_splits: Dict[str, Set[str]] = defaultdict(set)
    text_by_task: Dict[str, Set[str]] = {}
    for task in tasks:
        family_splits[task.family_id].add(task.split)
        prompt = task.prompt_path.read_text(encoding="utf-8")
        # Compare task semantics, not shared execution helpers or answer templates.
        semantic_inputs = [path for path in task.input_paths if path.name == "case.json"]
        input_text = "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in semantic_inputs)
        text_by_task[task.task_id] = _tokens(prompt + "\n" + input_text)
        runtime_audit = audit_public_task_source(task.root)
        if not runtime_audit["passed"]:
            violations.append({"type": "forbidden_public_task_file", "task_id": task.task_id, "files": runtime_audit["violations"]})
    for family_id, splits in sorted(family_splits.items()):
        if len(splits) > 1:
            violations.append({"type": "family_crosses_splits", "family_id": family_id, "splits": sorted(splits)})
    ids = sorted(text_by_task)
    near_duplicates = []
    task_lookup = {task.task_id: task for task in tasks}
    for index, left_id in enumerate(ids):
        for right_id in ids[index + 1 :]:
            if task_lookup[left_id].family_id == task_lookup[right_id].family_id:
                continue
            similarity = _jaccard(text_by_task[left_id], text_by_task[right_id])
            if similarity >= similarity_threshold:
                near_duplicates.append({"left": left_id, "right": right_id, "jaccard": round(similarity, 6)})
    if near_duplicates:
        violations.append({"type": "cross_family_near_duplicate", "pairs": near_duplicates})
    oracle_checks = {"oracle_root_provided": oracle_root is not None, "missing_oracles": [], "identity_mismatch": []}
    if oracle_root is not None:
        for task in tasks:
            path = oracle_root / (task.task_id + ".oracle.json")
            if not path.is_file():
                oracle_checks["missing_oracles"].append(task.task_id)
                continue
            oracle = load_json(path)
            if oracle.get("task_id") != task.task_id or oracle.get("family_id") != task.family_id:
                oracle_checks["identity_mismatch"].append(task.task_id)
        if oracle_checks["missing_oracles"]:
            violations.append({"type": "missing_oracles", "task_ids": oracle_checks["missing_oracles"]})
        if oracle_checks["identity_mismatch"]:
            violations.append({"type": "oracle_identity_mismatch", "task_ids": oracle_checks["identity_mismatch"]})
    return {
        "schema_version": "1.0",
        "passed": not violations,
        "task_count": len(tasks),
        "family_count": len(family_splits),
        "violations": violations,
        "oracle_checks": oracle_checks,
        "limitations": [
            "Lexical near-duplicate scan is a guardrail, not proof of no semantic contamination.",
            "Host-level filesystem isolation must be supplied by a container or site runner.",
        ],
    }
