from __future__ import annotations

import platform
import sys
from pathlib import Path
from typing import Any, Dict

from .utils import git_commit, relative_hashes, sha256_file


def environment_fingerprint() -> Dict[str, Any]:
    return {
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "executable": sys.executable,
    }


def task_fingerprint(task_root: Path) -> Dict[str, Any]:
    files = relative_hashes(task_root)
    manifest = task_root / "task.json"
    if not manifest.is_file():
        manifest = task_root / "task.toml"
    return {
        "manifest_sha256": sha256_file(manifest),
        "task_files": files,
    }


def repository_fingerprint(repository_root: Path) -> Dict[str, str]:
    return {
        "repository_root": str(repository_root.resolve()),
        "git_commit": git_commit(repository_root),
    }
