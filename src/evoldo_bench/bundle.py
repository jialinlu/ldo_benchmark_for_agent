from __future__ import annotations

import shutil
from pathlib import Path
from typing import Dict, Optional

from .contracts import Task
from .errors import PolicyError
from .utils import dump_json, ensure_under, relative_hashes, safe_relative_path, utc_timestamp

FORBIDDEN_RUNTIME_NAMES = {
    "oracle.json",
    "golden.json",
    "rubric.json",
    "judge_prompt.md",
    "reference_answer.json",
}
FORBIDDEN_RUNTIME_PARTS = {"oracle", "golden", "rubric", "judge_private", "reference_evidence", "solution", "tests"}


def _runtime_path_violation(path: Path, root: Path) -> bool:
    lower_name = path.name.lower()
    relative_parts = {part.lower() for part in path.relative_to(root).parts}
    return lower_name in FORBIDDEN_RUNTIME_NAMES or bool(relative_parts.intersection(FORBIDDEN_RUNTIME_PARTS))


def _copy_file(source: Path, destination: Path, allowed_root: Path) -> None:
    if source.is_symlink():
        raise PolicyError("symbolic links are not allowed in runtime source material: %s" % source)
    ensure_under(source, allowed_root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(source), str(destination))


def audit_runtime_bundle(bundle_dir: Path) -> Dict[str, object]:
    violations = []
    for path in sorted(bundle_dir.rglob("*")):
        if not path.is_file():
            continue
        if _runtime_path_violation(path, bundle_dir):
            violations.append(path.relative_to(bundle_dir).as_posix())
    return {"passed": not violations, "violations": violations}


def audit_public_task_source(task_dir: Path) -> Dict[str, object]:
    """Audit agent-visible source while allowing separate verifier and solution trees."""
    violations = []
    for path in sorted(task_dir.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(task_dir)
        if relative.parts and relative.parts[0].lower() in {"tests", "solution"}:
            continue
        if _runtime_path_violation(path, task_dir):
            violations.append(relative.as_posix())
    return {"passed": not violations, "violations": violations}


def build_runtime_bundle(task: Task, output_dir: Path, context_dir: Optional[Path] = None) -> Dict[str, object]:
    if output_dir.exists() and any(output_dir.iterdir()):
        raise PolicyError("output bundle directory is not empty: %s" % output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if task.package_style == "demo_task":
        _copy_file(task.manifest_path, output_dir / "task.toml", task.root)
        starter = task.root / "environment" / "starter"
        for source in sorted(starter.rglob("*")):
            if source.is_file():
                _copy_file(source, output_dir / source.relative_to(starter), task.root)
        _copy_file(task.prompt_path, output_dir / "instruction.md", task.root)
    else:
        manifest_rel = Path("task.json")
        _copy_file(task.root / manifest_rel, output_dir / manifest_rel, task.root)
        referenced = [task.data["prompt_file"], task.data["answer_template_file"]] + task.data["input_files"]
        for value in referenced:
            relative = safe_relative_path(value)
            _copy_file(task.root / relative, output_dir / relative, task.root)
    if context_dir is not None:
        if not context_dir.is_dir():
            raise PolicyError("context directory does not exist: %s" % context_dir)
        symlinks = [path for path in context_dir.rglob("*") if path.is_symlink()]
        if symlinks:
            raise PolicyError("context directory contains symbolic links: %s" % symlinks[0])
        shutil.copytree(str(context_dir), str(output_dir / "context"), dirs_exist_ok=True)
    audit = audit_runtime_bundle(output_dir)
    if not audit["passed"]:
        raise PolicyError("runtime bundle contains forbidden material: %s" % audit["violations"])
    bundle_manifest = {
        "schema_version": "1.0",
        "task_id": task.task_id,
        "family_id": task.family_id,
        "mode_context_included": context_dir is not None,
        "created_at": utc_timestamp(),
        "files": relative_hashes(output_dir),
        "oracle_included": False,
        "security_note": "File-minimal bundle; use a container/sandbox for a hostile agent.",
    }
    dump_json(output_dir / "bundle_manifest.json", bundle_manifest)
    return bundle_manifest
