from __future__ import annotations

import os
import shlex
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .bundle import build_runtime_bundle
from .contracts import ALLOWED_MODES, Task
from .errors import ContractError, PolicyError
from .provenance import environment_fingerprint, repository_fingerprint, task_fingerprint
from .utils import dump_json, sha256_file, utc_timestamp


def run_agent_command(
    task: Task,
    output_dir: Path,
    command: Sequence[str],
    mode: str = "direct_reasoning",
    context_dir: Optional[Path] = None,
    timeout_seconds: Optional[int] = None,
) -> Dict[str, Any]:
    if mode not in ALLOWED_MODES:
        raise ContractError("unsupported mode: %s" % mode)
    if mode not in task.data["eligible_modes"]:
        raise PolicyError("task %s is not eligible for mode %s" % (task.task_id, mode))
    if not command:
        raise ContractError("agent command must not be empty")
    bundle_dir = output_dir / "app"
    output_dir.mkdir(parents=True, exist_ok=True)
    build_runtime_bundle(task, bundle_dir, context_dir=context_dir)
    timeout = timeout_seconds or int(task.data["budget"]["timeout_seconds"])
    env = os.environ.copy()
    for key in list(env):
        upper = key.upper()
        if any(token in upper for token in ("ORACLE", "GOLDEN", "JUDGE_PRIVATE", "BENCH_PRIVATE")):
            env.pop(key, None)
    env.update(
        {
            "EVOLDO_TASK_DIR": str(bundle_dir),
            "EVOLDO_ANSWER_PATH": str(bundle_dir / "answer.json"),
            "EVOLDO_MODE": mode,
            "EVOLDO_TASK_ID": task.task_id,
        }
    )
    started = utc_timestamp()
    start = time.monotonic()
    timed_out = False
    try:
        completed = subprocess.run(
            list(command),
            cwd=str(bundle_dir),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
        return_code = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        return_code = 124
        stdout = exc.stdout or b""
        stderr = exc.stderr or b""
    duration = time.monotonic() - start
    (output_dir / "stdout.log").write_bytes(stdout)
    (output_dir / "stderr.log").write_bytes(stderr)
    answer_path = bundle_dir / "answer.json"
    status = "ok" if return_code == 0 and answer_path.is_file() else "failed"
    if timed_out:
        status = "timeout"
    record = {
        "schema_version": "1.0",
        "task_id": task.task_id,
        "family_id": task.family_id,
        "mode": mode,
        "command": list(command),
        "command_display": " ".join(shlex.quote(item) for item in command),
        "started_at": started,
        "duration_seconds": round(duration, 6),
        "timeout_seconds": timeout,
        "timed_out": timed_out,
        "return_code": return_code,
        "status": status,
        "answer_present": answer_path.is_file(),
        "answer_sha256": sha256_file(answer_path) if answer_path.is_file() else None,
        "stdout_file": "stdout.log",
        "stderr_file": "stderr.log",
        "task_fingerprint": task_fingerprint(task.root),
        "repository": repository_fingerprint(Path(__file__).resolve().parents[2]),
        "environment": environment_fingerprint(),
        "security_boundary": "bundle_only; host sandbox not provided by reference runner",
    }
    dump_json(output_dir / "run_record.json", record)
    return record
