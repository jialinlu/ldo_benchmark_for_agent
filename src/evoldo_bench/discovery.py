from __future__ import annotations

import json
import hashlib
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from .contracts import Task, load_task
from .errors import ContractError, TaskNotFoundError
from .utils import sha256_file


def task_package_sha256(task_root: Path) -> str:
    rows = []
    for path in sorted(task_root.rglob("*")):
        if path.is_file() and path.name != "package_manifest.json":
            rows.append("%s:%s" % (path.relative_to(task_root).as_posix(), sha256_file(path)))
    return hashlib.sha256("\n".join(rows).encode()).hexdigest()


def discover_tasks(tasks_root: Path, split: Optional[str] = None) -> List[Task]:
    if not tasks_root.is_dir():
        raise ContractError("tasks root does not exist: %s" % tasks_root)
    tasks = []
    seen = {}
    manifests = list(tasks_root.rglob("task.toml")) + list(tasks_root.rglob("task.json"))
    for manifest in sorted(manifests):
        relative_parts = {part.lower() for part in manifest.relative_to(tasks_root).parts[:-1]}
        if relative_parts.intersection({"environment", "tests", "solution"}):
            continue
        if manifest.name == "task.json" and (manifest.parent / "task.toml").is_file():
            continue
        task = load_task(manifest.parent)
        if task.task_id in seen:
            raise ContractError(
                "duplicate task id %s in %s and %s" % (task.task_id, seen[task.task_id], task.root)
            )
        seen[task.task_id] = task.root
        if split is None or task.split == split:
            tasks.append(task)
    return tasks


def get_task(tasks_root: Path, task_id: str) -> Task:
    matches = [task for task in discover_tasks(tasks_root) if task.task_id == task_id]
    if not matches:
        raise TaskNotFoundError("task not found: %s" % task_id)
    return matches[0]


def inventory(tasks: Iterable[Task]) -> Dict[str, object]:
    tasks = list(tasks)
    by_family = defaultdict(list)
    for task in tasks:
        by_family[task.family_id].append(task)
    return {
        "task_count": len(tasks),
        "family_count": len(by_family),
        "suite_counts": dict(sorted(Counter(task.suite for task in tasks).items())),
        "level_counts": dict(sorted(Counter(task.data["level"] for task in tasks).items())),
        "variant_counts": dict(sorted(Counter(task.variant for task in tasks).items())),
        "split_counts": dict(sorted(Counter(task.split for task in tasks).items())),
        "families": {
            family: sorted(task.task_id for task in family_tasks)
            for family, family_tasks in sorted(by_family.items())
        },
    }


def validate_registry(tasks: Iterable[Task], registry_path: Path) -> Dict[str, object]:
    tasks = list(tasks)
    if not registry_path.is_file():
        raise ContractError("registry does not exist: %s" % registry_path)
    rows = []
    with registry_path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ContractError("invalid registry JSON at line %d: %s" % (line_number, exc))
            if not isinstance(row, dict) or "task_id" not in row:
                raise ContractError("registry line %d is not a task object" % line_number)
            rows.append(row)
    by_id = {}
    for row in rows:
        task_id = row["task_id"]
        if task_id in by_id:
            raise ContractError("duplicate task in registry: %s" % task_id)
        by_id[task_id] = row
    task_by_id = {task.task_id: task for task in tasks}
    missing = sorted(set(task_by_id) - set(by_id))
    unexpected = sorted(set(by_id) - set(task_by_id))
    hash_mismatch = []
    package_hash_mismatch = []
    identity_mismatch = []
    for task_id in sorted(set(task_by_id).intersection(by_id)):
        task = task_by_id[task_id]
        row = by_id[task_id]
        if row.get("manifest_sha256") != sha256_file(task.manifest_path):
            hash_mismatch.append(task_id)
        if row.get("package_sha256") != task_package_sha256(task.root):
            package_hash_mismatch.append(task_id)
        for field, actual in [
            ("family_id", task.family_id),
            ("suite", task.suite),
            ("level", task.data["level"]),
            ("variant", task.variant),
            ("split", task.split),
        ]:
            if row.get(field) != actual:
                identity_mismatch.append({"task_id": task_id, "field": field})
    return {
        "passed": not (missing or unexpected or hash_mismatch or package_hash_mismatch or identity_mismatch),
        "row_count": len(rows),
        "missing": missing,
        "unexpected": unexpected,
        "hash_mismatch": hash_mismatch,
        "package_hash_mismatch": package_hash_mismatch,
        "identity_mismatch": identity_mismatch,
    }
