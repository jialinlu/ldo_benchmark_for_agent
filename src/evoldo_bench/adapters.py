from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from .errors import ContractError
from .probes import evaluate_probe_contract
from .utils import ensure_under, sha256_file, utc_timestamp


class AgentAdapter(ABC):
    @abstractmethod
    def command(self, task_id: str, rollout: int, seed: int) -> Sequence[str]:
        raise NotImplementedError


class CommandAgentAdapter(AgentAdapter):
    """Command template adapter. Tokens may contain {task_id}, {rollout}, and {seed}."""

    def __init__(self, command_template: Sequence[str]):
        if not command_template:
            raise ContractError("agent command template must not be empty")
        self.command_template = list(command_template)

    def command(self, task_id: str, rollout: int, seed: int) -> Sequence[str]:
        values = {"task_id": task_id, "rollout": rollout, "seed": seed}
        return [part.format(**values) for part in self.command_template]


class SimulatorAdapter(ABC):
    @abstractmethod
    def run(self, request: Dict[str, Any], workspace: Path, timeout_seconds: int) -> Dict[str, Any]:
        raise NotImplementedError


class ProcessSimulatorAdapter(SimulatorAdapter):
    """Uniform JSON-in/JSON-out simulator process adapter.

    The child receives the probe request on stdin and must emit one JSON object on stdout. An
    unavailable executable, timeout, or malformed response is classified as INFRA_FAIL rather than
    converted into a circuit conclusion.
    """

    def __init__(self, command: Sequence[str]):
        if not command:
            raise ContractError("simulator command must not be empty")
        self.command = list(command)

    def run(self, request: Dict[str, Any], workspace: Path, timeout_seconds: int = 120) -> Dict[str, Any]:
        workspace.mkdir(parents=True, exist_ok=True)
        probe = request.get("probe")
        if not isinstance(probe, dict):
            raise ContractError("simulator request requires probe")
        probe_gate = evaluate_probe_contract(probe)
        if not probe_gate["passed"]:
            return {"schema_version": "1.0", "status": "POLICY_FAIL", "probe_gate": probe_gate}
        started = utc_timestamp()
        start = time.monotonic()
        executable = shutil.which(self.command[0])
        if executable is None:
            return {"schema_version": "1.0", "status": "INFRA_FAIL", "reason": "simulator_unavailable", "started_at": started, "duration_seconds": 0.0}
        try:
            completed = subprocess.run(
                self.command,
                cwd=str(workspace),
                input=json.dumps(request).encode("utf-8"),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return {"schema_version": "1.0", "status": "INFRA_FAIL", "reason": "simulator_timeout", "started_at": started, "duration_seconds": round(time.monotonic() - start, 6)}
        (workspace / "simulator.stdout.log").write_bytes(completed.stdout)
        (workspace / "simulator.stderr.log").write_bytes(completed.stderr)
        if completed.returncode != 0:
            return {"schema_version": "1.0", "status": "INFRA_FAIL", "reason": "simulator_nonzero_exit", "return_code": completed.returncode, "started_at": started, "duration_seconds": round(time.monotonic() - start, 6)}
        try:
            result = json.loads(completed.stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {"schema_version": "1.0", "status": "INFRA_FAIL", "reason": "invalid_simulator_response", "started_at": started, "duration_seconds": round(time.monotonic() - start, 6)}
        if not isinstance(result, dict):
            return {"schema_version": "1.0", "status": "INFRA_FAIL", "reason": "invalid_simulator_response", "started_at": started, "duration_seconds": round(time.monotonic() - start, 6)}
        result.setdefault("schema_version", "1.0")
        result.setdefault("status", "OK")
        result["probe_gate"] = probe_gate
        result["started_at"] = started
        result["duration_seconds"] = round(time.monotonic() - start, 6)
        return result


class NgspiceBatchAdapter(SimulatorAdapter):
    """Optional open simulator adapter for independently supplied, redistributable SPICE decks."""

    def __init__(self, executable: str = "ngspice"):
        self.executable = executable

    def run(self, request: Dict[str, Any], workspace: Path, timeout_seconds: int = 120) -> Dict[str, Any]:
        probe = request.get("probe")
        if not isinstance(probe, dict):
            raise ContractError("ngspice request requires probe")
        gate = evaluate_probe_contract(probe)
        if not gate["passed"]:
            return {"schema_version": "1.0", "status": "POLICY_FAIL", "probe_gate": gate}
        deck_value = request.get("deck")
        if not isinstance(deck_value, str):
            raise ContractError("ngspice request.deck must be a path string")
        deck_path = Path(deck_value).expanduser()
        deck = (workspace / deck_path).resolve() if not deck_path.is_absolute() else deck_path.resolve()
        if not deck.is_file():
            return {"schema_version": "1.0", "status": "INFRA_FAIL", "reason": "deck_unavailable"}
        try:
            ensure_under(deck, workspace)
        except ValueError:
            return {"schema_version": "1.0", "status": "POLICY_FAIL", "reason": "deck_outside_tool_workspace"}
        executable = shutil.which(self.executable)
        if executable is None:
            return {"schema_version": "1.0", "status": "INFRA_FAIL", "reason": "ngspice_unavailable"}
        workspace.mkdir(parents=True, exist_ok=True)
        log = workspace / "ngspice.log"
        started = utc_timestamp()
        start = time.monotonic()
        try:
            completed = subprocess.run([executable, "-b", "-o", str(log), str(deck)], cwd=str(workspace), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout_seconds, check=False)
        except subprocess.TimeoutExpired:
            return {"schema_version": "1.0", "status": "INFRA_FAIL", "reason": "ngspice_timeout", "started_at": started, "duration_seconds": round(time.monotonic() - start, 6)}
        measurements: Dict[str, float] = {}
        if log.is_file():
            log_text = log.read_text(encoding="utf-8", errors="replace")
            for name in request.get("measurement_names", []):
                if not isinstance(name, str) or not name:
                    continue
                match = re.search(r"(?im)^\s*%s\s*=\s*([-+0-9.eE]+)" % re.escape(name), log_text)
                if match:
                    measurements[name] = float(match.group(1))
        return {
            "schema_version": "1.0",
            "status": "OK" if completed.returncode == 0 else "INFRA_FAIL",
            "reason": None if completed.returncode == 0 else "ngspice_nonzero_exit",
            "return_code": completed.returncode,
            "deck_sha256": sha256_file(deck),
            "log_file": str(log),
            "measurements": measurements,
            "started_at": started,
            "duration_seconds": round(time.monotonic() - start, 6),
        }


class SiteAdapter(ABC):
    """Private-site boundary: implementations live outside this public repository."""

    @abstractmethod
    def qualify(self, candidate_manifest: Dict[str, Any], qualification_plan: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError
