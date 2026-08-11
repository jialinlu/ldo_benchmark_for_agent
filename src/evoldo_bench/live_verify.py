from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Optional

from .contracts import Task
from .errors import ContractError
from .grading import grade_one
from .utils import load_json, sha256_file, utc_timestamp


def _run(command: list[str], cwd: Path, env: Dict[str, str], timeout: int) -> Dict[str, Any]:
    started = time.monotonic()
    try:
        cp = subprocess.run(command, cwd=str(cwd), env=env, capture_output=True, text=True,
                            timeout=timeout, check=False)
        return {"returncode": cp.returncode, "stdout": cp.stdout, "stderr": cp.stderr,
                "duration_seconds": round(time.monotonic() - started, 6), "timed_out": False}
    except subprocess.TimeoutExpired as exc:
        return {"returncode": 124, "stdout": exc.stdout or "", "stderr": exc.stderr or "",
                "duration_seconds": round(time.monotonic() - started, 6), "timed_out": True}


def verify_live_task(task: Task, answer_path: Path, tasks_root: Path, oracle_root: Path,
                     app_root: Optional[Path] = None, pdk_root: Optional[Path] = None,
                     eda_ssh_target: Optional[str] = None, ngspice: str = "ngspice") -> Dict[str, Any]:
    """Run the trusted live gate for a tool task; never convert INFRA into model failure."""
    semantic = grade_one(tasks_root, oracle_root, answer_path)
    role = task.data.get("evaluation_role")
    if role not in {"tool_sizing_treatment", "eda_live", "companion"} or task.suite != "eda_tool" and role != "tool_sizing_treatment":
        semantic.update({"score_valid": True, "live_verification": "not_required"})
        return semantic
    app_root = app_root or answer_path.parent
    env = os.environ.copy()
    with tempfile.TemporaryDirectory(prefix="evoldo-live-verify-") as temporary:
        work = Path(temporary)
        if role == "tool_sizing_treatment":
            if pdk_root is None:
                return {"task_id": task.task_id, "score_valid": False, "status": "INFRA_INVALID",
                        "reason": "SKY130 PDK root not provided", "semantic_score": semantic["score"]}
            model_entry = pdk_root / "libs.tech" / "ngspice" / "sky130.lib.spice"
            expected_model_sha = "5efa041a988893c1a3580d0ecd57870ea3146b27741c7d42b56baaa336b9549e"
            if not model_entry.is_file() or sha256_file(model_entry) != expected_model_sha:
                return {"task_id": task.task_id, "score_valid": False, "status": "INFRA_INVALID",
                        "reason": "SKY130 model entry missing or hash mismatch",
                        "expected_model_sha256": expected_model_sha, "semantic_score": semantic["score"]}
            for name in ("sizer_tool.py", "sizing_tb.sp", "sizing_spec.json"):
                shutil.copy2(task.source_path(name), work / name)
            case = load_json(task.source_path("case.json"))
            answer = load_json(answer_path)
            candidate = {field: answer["answers"]["q%d" % (index + 1)]
                         for index, field in enumerate(case["candidate_fields"])}
            (work / "candidate.json").write_text(json.dumps(candidate) + "\n", encoding="utf-8")
            env.update({"SKY130_PDK_ROOT": str(pdk_root), "NGSPICE": ngspice})
            execution = _run(["python3", "sizer_tool.py", "candidate.json"], work, env, 240)
            if execution["returncode"] != 0:
                infra = "INFRA:" in execution["stderr"] or "not found" in execution["stderr"]
                return {"task_id": task.task_id, "score_valid": not infra,
                        "status": "INFRA_INVALID" if infra else "MODEL_FAIL", "score": None if infra else 0.0,
                        "semantic_score": semantic["score"], "execution": execution}
            ledger = json.loads((work / "sizing_ledger.json").read_text(encoding="utf-8"))
            metrics = ledger[-1]["metrics"]
            live_pass = 1.44 <= metrics["vout"] <= 1.53 and abs(metrics["iq"]) <= 50e-6
            semantic.update({"score_valid": True, "score": semantic["score"] if live_pass else 0.0,
                             "live_verification": "PASS" if live_pass else "FAIL", "live_metrics": metrics,
                             "execution": execution})
            return semantic

        skill = app_root / "solution.il"
        if not skill.is_file():
            semantic.update({"score_valid": True, "score": 0.0, "live_verification": "FAIL",
                             "reason": "solution.il missing"})
            return semantic
        if not eda_ssh_target:
            return {"task_id": task.task_id, "score_valid": False, "status": "INFRA_INVALID",
                    "reason": "EDA SSH target not provided", "semantic_score": semantic["score"]}
        shutil.copy2(task.source_path("ic618_tool.py"), work / "ic618_tool.py")
        shutil.copy2(skill, work / "solution.il")
        env["EVOLDO_EDA_SSH_TARGET"] = eda_ssh_target
        preflight = _run(["python3", "ic618_tool.py", "preflight"], work, env, 60)
        if preflight["returncode"] != 0:
            return {"task_id": task.task_id, "score_valid": False, "status": "INFRA_INVALID",
                    "reason": "IC618 preflight failed", "preflight": preflight,
                    "semantic_score": semantic["score"]}
        execution = _run(["python3", "ic618_tool.py", "run", "--skill", "solution.il"], work, env, 300)
        if execution["returncode"] != 0 or not (work / "eda_result.json").is_file():
            semantic.update({"score_valid": True, "score": 0.0, "live_verification": "FAIL",
                             "execution": execution})
            return semantic
        result = load_json(work / "eda_result.json")
        case = load_json(task.source_path("case.json"))
        answer = load_json(answer_path)
        selected = answer["answers"]["q1"]
        option_text = next(item["text"] for item in case["questions"][0]["options"] if item["id"] == selected)
        field = case.get("result_field", "audit_result")
        live_pass = result.get("status") == "OK" and result.get(field) == option_text
        semantic.update({"score_valid": True, "score": semantic["score"] if live_pass else 0.0,
                         "live_verification": "PASS" if live_pass else "FAIL", "live_result": result,
                         "skill_sha256": sha256_file(skill), "execution": execution,
                         "verified_at": utc_timestamp()})
        return semantic
