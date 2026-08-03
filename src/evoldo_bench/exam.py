from __future__ import annotations

from pathlib import Path
import json
import secrets
from typing import Any, Dict, Optional

from .errors import ContractError
from .utils import dump_json, git_commit, relative_hashes, sha256_text, utc_timestamp


def _tree(root: Optional[Path], required: bool = False) -> Dict[str, Any]:
    if root is None:
        if required:
            raise ContractError("required exam store was not supplied")
        return {"present": False, "files": {}, "digest": None}
    if not root.is_dir():
        raise ContractError("exam store is not a directory: %s" % root)
    files = relative_hashes(root)
    digest = sha256_text("\n".join("%s:%s" % item for item in sorted(files.items())))
    return {"present": True, "file_count": len(files), "files": files, "digest": digest}


def freeze_exam(
    output: Path,
    tasks_root: Path,
    oracle_root: Path,
    policy: Dict[str, Any],
    skill_root: Optional[Path] = None,
    tool_root: Optional[Path] = None,
    repository_root: Optional[Path] = None,
    release_id: str = "unreleased",
) -> Dict[str, Any]:
    if not isinstance(policy, dict) or not policy:
        raise ContractError("exam policy must be a non-empty JSON object")
    manifest = {
        "schema_version": "1.0",
        "release_id": release_id,
        "created_at": utc_timestamp(),
        "tasks": _tree(tasks_root, required=True),
        "oracles": _tree(oracle_root, required=True),
        "skill_snapshot": _tree(skill_root),
        "tool_snapshot": _tree(tool_root),
        "policy": policy,
        "repository_commit": git_commit(repository_root) if repository_root else None,
        "agent_mount_policy": "tasks_and_approved_snapshots_only; oracle_store_excluded",
    }
    dump_json(output, manifest)
    return manifest


def verify_exam(manifest: Dict[str, Any], tasks_root: Path, oracle_root: Path, skill_root: Optional[Path] = None, tool_root: Optional[Path] = None) -> Dict[str, Any]:
    checks = {}
    for name, root in (("tasks", tasks_root), ("oracles", oracle_root), ("skill_snapshot", skill_root), ("tool_snapshot", tool_root)):
        expected = manifest.get(name, {})
        current = _tree(root, required=name in {"tasks", "oracles"})
        checks[name] = {"passed": expected.get("digest") == current.get("digest"), "expected_digest": expected.get("digest"), "actual_digest": current.get("digest")}
    return {"schema_version": "1.0", "release_id": manifest.get("release_id"), "passed": all(item["passed"] for item in checks.values()), "checks": checks}


def redact_exam_manifest(manifest: Dict[str, Any]) -> Dict[str, Any]:
    """Create a publishable commitment without hidden filenames or policy contents."""
    trees = {}
    for name in ("tasks", "oracles", "skill_snapshot", "tool_snapshot"):
        tree = manifest.get(name, {})
        trees[name] = {
            "present": bool(tree.get("present")),
            "file_count": int(tree.get("file_count", len(tree.get("files", {})))),
            "digest": tree.get("digest"),
        }
    policy_text = json.dumps(manifest.get("policy", {}), sort_keys=True, separators=(",", ":"))
    return {
        "schema_version": "1.0-public",
        "release_id": manifest.get("release_id"),
        "created_at": manifest.get("created_at"),
        "trees": trees,
        "policy_sha256": sha256_text(policy_text),
        "repository_commit": manifest.get("repository_commit"),
        "agent_mount_policy": manifest.get("agent_mount_policy"),
        "redaction": "hidden relative paths and policy contents omitted",
    }


def create_private_canary(output: Path, release_id: str, token: Optional[str] = None) -> Dict[str, Any]:
    token = token or secrets.token_hex(24)
    text = (
        "EVOLDO_EXAM_PRIVATE_CANARY\n"
        "release_id=%s\n"
        "token=%s\n"
        "This sealed benchmark material must not enter model training, retrieval, or public corpora.\n"
        % (release_id, token)
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    return {"schema_version": "1.0", "release_id": release_id, "canary_sha256": sha256_text(text), "output": str(output)}
