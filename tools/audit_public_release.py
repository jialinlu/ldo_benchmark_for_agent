#!/usr/bin/env python3
"""Fail when a public release contains common secrets or private-site artifacts.

This is a guardrail, not a substitute for an organizational security review. It scans the tracked
tree, reachable Git blobs, and reachable commit metadata without printing matched secret values.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple


ROOT = Path(__file__).resolve().parents[1]

CONTENT_RULES: Sequence[Tuple[str, re.Pattern[bytes]]] = [
    ("private_key", re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("github_token", re.compile(rb"\bgh[opusr]_[A-Za-z0-9_]{20,}\b")),
    ("openai_key", re.compile(rb"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{16,}\b")),
    ("aws_access_key", re.compile(rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("google_api_key", re.compile(rb"\bAIza[0-9A-Za-z_-]{30,}\b")),
    ("slack_token", re.compile(rb"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    (
        "generic_secret_assignment",
        re.compile(
            rb"(?i)\b(?:api[_-]?key|secret|password|passwd|access[_-]?token|auth[_-]?token)"
            rb"\b\s*[:=]\s*[\"']?[^\s\"']{8,}"
        ),
    ),
    (
        "absolute_private_path",
        re.compile(
            (rb"/" + b"Users" + rb"/[^/\s\"']+|/" + b"home" + rb"/[^/\s\"']+|/" + b"data" + rb"/[^\s\"']+")
        ),
    ),
    (
        "private_ipv4",
        re.compile(
            rb"(?<![\d.])(?:10\.|127\.|169\.254\.|172\.(?:1[6-9]|2\d|3[01])\."
            rb"|192\.168\.)\d{1,3}\.\d{1,3}(?![\d.])"
        ),
    ),
    (
        "vendor_build_or_license_detail",
        re.compile(
            rb"(?i)(?:\b(?:spectre|virtuoso)\b.{0,24}\b(?:version|ver\.?|build)\s*[0-9]"
            rb"|\brequires\s+the\s+[A-Z0-9_]{6,}\s+license\b|\bFLEXlm\s+error\b)"
        ),
    ),
]

EMAIL_RE = re.compile(rb"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
ALLOWED_EMAIL_SUFFIXES = (b"@users.noreply.github.com", b"@example.invalid")
ALLOWED_EMAILS = {b"noreply@github.com"}

SUSPICIOUS_BASENAMES = {
    ".env",
    ".netrc",
    ".npmrc",
    ".pypirc",
    "credentials",
    "credentials.json",
    "id_rsa",
    "id_ed25519",
    "secrets.json",
    "token.json",
}

DISALLOWED_SUFFIXES = {
    ".gds",
    ".gdsii",
    ".oas",
    ".oa",
    ".psf",
    ".raw",
    ".scs",
    ".tr0",
}


def run(*args: str) -> bytes:
    return subprocess.check_output(args, cwd=str(ROOT))


def tracked_files() -> List[Path]:
    return [ROOT / item for item in run("git", "ls-files", "-z").decode().split("\0") if item]


def scan_bytes(label: str, data: bytes, violations: List[Dict[str, object]]) -> None:
    if b"\x00" in data:
        violations.append({"rule": "binary_tracked_content", "location": label})
        return
    for rule, pattern in CONTENT_RULES:
        if pattern.search(data):
            violations.append({"rule": rule, "location": label})
    for match in EMAIL_RE.finditer(data):
        email = match.group(0).lower()
        if email not in ALLOWED_EMAILS and not email.endswith(ALLOWED_EMAIL_SUFFIXES):
            violations.append({"rule": "public_email", "location": label})
            break


def scan_tree(violations: List[Dict[str, object]]) -> None:
    for path in tracked_files():
        # A tracked path may be intentionally deleted in the release worktree before
        # the deletion is staged.  It contributes no bytes to the candidate tree.
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT).as_posix()
        if path.name.lower() in SUSPICIOUS_BASENAMES:
            violations.append({"rule": "suspicious_file_name", "location": relative})
        if path.suffix.lower() in DISALLOWED_SUFFIXES:
            violations.append({"rule": "private_eda_artifact_type", "location": relative})
        if path.stat().st_size > 2 * 1024 * 1024:
            violations.append({"rule": "large_tracked_file_requires_review", "location": relative})
        scan_bytes(relative, path.read_bytes(), violations)


def scan_history(violations: List[Dict[str, object]]) -> None:
    seen_blobs = set()
    for line in run("git", "rev-list", "--objects", "--all").decode().splitlines():
        object_id, *path_parts = line.split(" ", 1)
        if run("git", "cat-file", "-t", object_id).strip() != b"blob" or object_id in seen_blobs:
            continue
        seen_blobs.add(object_id)
        path = path_parts[0] if path_parts else "<unnamed>"
        scan_bytes("git-blob:%s:%s" % (object_id[:12], path), run("git", "cat-file", "blob", object_id), violations)

    metadata = run(
        "git",
        "log",
        "--all",
        "--format=%H%x00%an%x00%ae%x00%cn%x00%ce%x00%s",
    ).splitlines()
    for line in metadata:
        fields = line.split(b"\x00")
        if len(fields) != 6:
            violations.append({"rule": "invalid_commit_metadata", "location": "git-history"})
            continue
        commit, _author, author_email, _committer, committer_email, subject = fields
        for role, email in (("author", author_email), ("committer", committer_email)):
            normalized_email = email.lower()
            if (
                normalized_email not in ALLOWED_EMAILS
                and not normalized_email.endswith(ALLOWED_EMAIL_SUFFIXES)
            ):
                violations.append(
                    {
                        "rule": "non_noreply_commit_email",
                        "location": "git-commit:%s:%s" % (commit[:12].decode(), role),
                    }
                )
        scan_bytes("git-commit:%s:subject" % commit[:12].decode(), subject, violations)


def main() -> int:
    violations: List[Dict[str, object]] = []
    scan_tree(violations)
    scan_history(violations)
    unique = []
    seen = set()
    for item in violations:
        key = (item["rule"], item["location"])
        if key not in seen:
            seen.add(key)
            unique.append(item)
    report = {
        "schema_version": "1.0",
        "passed": not unique,
        "tracked_file_count": len(tracked_files()),
        "violations": unique,
        "note": "Matched values are intentionally omitted from this report.",
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
