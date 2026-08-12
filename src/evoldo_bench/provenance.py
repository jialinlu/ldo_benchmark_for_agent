from __future__ import annotations

import hashlib
import platform
import subprocess
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


def _worktree_fingerprint(repository_root: Path) -> Dict[str, Any]:
    """Hash release-relevant worktree changes without serializing their contents."""
    try:
        diff = subprocess.check_output(
            ["git", "diff", "--binary", "HEAD", "--"], cwd=str(repository_root)
        )
        untracked_raw = subprocess.check_output(
            ["git", "ls-files", "--others", "--exclude-standard", "-z"],
            cwd=str(repository_root),
        )
    except (OSError, subprocess.CalledProcessError):
        return {"worktree_state": "unavailable", "worktree_sha256": None}
    digest = hashlib.sha256()
    digest.update(b"tracked-diff\0")
    digest.update(diff)
    untracked = sorted(item for item in untracked_raw.decode().split("\0") if item)
    for relative in untracked:
        path = repository_root / relative
        if not path.is_file() or path.is_symlink():
            continue
        digest.update(b"untracked\0" + relative.encode() + b"\0")
        digest.update(bytes.fromhex(sha256_file(path)))
    dirty = bool(diff or untracked)
    return {
        "worktree_state": "dirty" if dirty else "clean",
        "worktree_sha256": digest.hexdigest(),
    }


def repository_fingerprint(repository_root: Path) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "repository_root": str(repository_root.resolve()),
        "git_commit": git_commit(repository_root),
    }
    result.update(_worktree_fingerprint(repository_root))
    return result
