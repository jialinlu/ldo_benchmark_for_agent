from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .errors import ContractError
from .utils import dump_json, sha256_file, sha256_text, utc_timestamp


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TRACK_ROOT = ROOT / "benchmarks" / "ldo_design_closure"
PUBLIC_PDK_MANIFEST = DEFAULT_TRACK_ROOT / "public_pdk_manifest.json"
MEASUREMENT_RE = re.compile(r"(?im)^\s*([a-z][a-z0-9_]*)\s*=\s*([-+0-9.eE]+)")
FORBIDDEN_DIRECTIVES = {".ic", ".nodeset"}
FORBIDDEN_DEVICE_PREFIXES = {"a", "b", "e", "f", "g", "h", "i", "s", "v", "w"}
ALLOWED_SUBCKT_DIRECTIVES = {".param"}
ALLOWED_TOP_LEVEL_DIRECTIVES = {".param"}
INFRA_LOG_RE = re.compile(
    r"(?i)(cannot open|can't open|no such file|could not find (?:a valid )?model|model\s+\S+\s+not found|osdi|shared library)"
)


def load_closure_registry(track_root: Path = DEFAULT_TRACK_ROOT) -> Dict[str, Any]:
    path = track_root / "registry.json"
    if not path.is_file():
        raise ContractError("closure registry does not exist: %s" % path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != "1.0" or not isinstance(data.get("tasks"), list):
        raise ContractError("invalid closure registry")
    ids = [item.get("task_id") for item in data["tasks"] if isinstance(item, dict)]
    if len(ids) != len(data["tasks"]):
        raise ContractError("closure registry entries must be objects")
    if any(not isinstance(item, str) or not item for item in ids) or len(ids) != len(set(ids)):
        raise ContractError("closure registry task IDs must be unique non-empty strings")
    return data


def load_closure_task(task_id: str, track_root: Path = DEFAULT_TRACK_ROOT) -> Dict[str, Any]:
    registry = load_closure_registry(track_root)
    entry = next((item for item in registry["tasks"] if item["task_id"] == task_id), None)
    if entry is None:
        raise ContractError("unknown closure task: %s" % task_id)
    path = (track_root / entry["task_file"]).resolve()
    try:
        path.relative_to(track_root.resolve())
    except ValueError as exc:
        raise ContractError("closure task file escapes track root") from exc
    data = json.loads(path.read_text(encoding="utf-8"))
    if (
        data.get("task_id") != task_id
        or data.get("pdk") != "sky130"
        or data.get("simulator") != "ngspice"
        or not isinstance(data.get("starter_candidate"), str)
        or not isinstance(data.get("scenarios"), list)
        or not data["scenarios"]
    ):
        raise ContractError("invalid closure task contract: %s" % path)
    scenario_ids = set()
    for scenario in data["scenarios"]:
        if not isinstance(scenario, dict) or not isinstance(scenario.get("scenario_id"), str):
            raise ContractError("invalid closure scenario in %s" % path)
        if scenario["scenario_id"] in scenario_ids:
            raise ContractError("duplicate closure scenario ID in %s" % path)
        scenario_ids.add(scenario["scenario_id"])
        if scenario.get("corner", "tt") not in {"tt", "ff", "ss", "fs", "sf"}:
            raise ContractError("unsupported SKY130 corner in %s" % path)
        if not isinstance(scenario.get("bench_template"), str) or not isinstance(scenario.get("limits"), dict) or not scenario["limits"]:
            raise ContractError("closure scenario requires a bench template and limits")
        for metric, bounds in scenario["limits"].items():
            if not isinstance(metric, str) or not isinstance(bounds, dict) or not ({"min", "max"} & set(bounds)):
                raise ContractError("invalid metric limits in %s" % path)
            if any(not isinstance(bounds[key], (int, float)) for key in ("min", "max") if key in bounds):
                raise ContractError("metric limits must be numeric in %s" % path)
    return data


def expected_sky130_entry_sha256(track_root: Path = DEFAULT_TRACK_ROOT) -> str:
    manifest_path = track_root / PUBLIC_PDK_MANIFEST.name
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    value = manifest.get("providers", {}).get("sky130", {}).get("entry_sha256")
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value):
        raise ContractError("public PDK manifest has an invalid SKY130 entry hash")
    return value


def resolve_sky130_model_root(pdk_root: Path) -> Path:
    candidates = (
        pdk_root / "sky130_pdk" / "libs.tech" / "ngspice" / "sky130.lib.spice",
        pdk_root / "libs.tech" / "ngspice" / "sky130.lib.spice",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise ContractError(
        "SKY130 ngspice entry was not found; pass the checkout root or its sky130_pdk directory"
    )


def scan_dut_policy(candidate: Path) -> Dict[str, Any]:
    if not candidate.is_file():
        raise ContractError("candidate netlist does not exist: %s" % candidate)
    violations: List[Dict[str, Any]] = []
    in_subckt = False
    for line_number, raw in enumerate(candidate.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("*"):
            continue
        token = line.split(None, 1)[0].lower()
        if token.startswith("+"):
            continue
        if token == ".subckt":
            in_subckt = True
            continue
        if token == ".ends":
            in_subckt = False
            continue
        if not in_subckt:
            if token in ALLOWED_TOP_LEVEL_DIRECTIVES:
                continue
            violations.append({"line": line_number, "code": "TOP_LEVEL_CANDIDATE_CONTENT", "token": token})
            continue
        if token in FORBIDDEN_DIRECTIVES:
            violations.append({"line": line_number, "code": "FORCED_INITIAL_STATE", "token": token})
        elif token.startswith(".") and token not in ALLOWED_SUBCKT_DIRECTIVES:
            violations.append({"line": line_number, "code": "FORBIDDEN_DUT_DIRECTIVE", "token": token})
        elif token[0] in FORBIDDEN_DEVICE_PREFIXES:
            violations.append({"line": line_number, "code": "FORBIDDEN_IDEAL_DEVICE", "token": token})
    return {
        "status": "PASS" if not violations else "FAIL",
        "candidate_sha256": sha256_file(candidate),
        "violations": violations,
        "rule": "candidate must contain only physical DUT subcircuits; top-level bench content, includes, independent/behavioral/controlled/switch elements, and forced state are forbidden",
    }


def parse_measurements(log_text: str) -> Dict[str, float]:
    measurements: Dict[str, float] = {}
    for match in MEASUREMENT_RE.finditer(log_text):
        try:
            measurements[match.group(1).lower()] = float(match.group(2))
        except ValueError:
            continue
    return measurements


def _check_limits(measurements: Mapping[str, float], limits: Mapping[str, Mapping[str, float]]) -> Tuple[bool, List[Dict[str, Any]]]:
    checks: List[Dict[str, Any]] = []
    passed = True
    for name, bounds in limits.items():
        value = measurements.get(name.lower())
        status = "PASS"
        if value is None:
            status = "MISSING"
        elif "min" in bounds and value < float(bounds["min"]):
            status = "FAIL"
        elif "max" in bounds and value > float(bounds["max"]):
            status = "FAIL"
        if status != "PASS":
            passed = False
        checks.append({"metric": name, "value": value, "limits": dict(bounds), "status": status})
    return passed, checks


def _render_deck(template: str, model_lib: Path, candidate_name: str, corner: str, temperature_c: float = 27.0) -> str:
    values = {
        "{{MODEL_LIB}}": model_lib.as_posix(),
        "{{CANDIDATE_NETLIST}}": candidate_name,
        "{{CORNER}}": corner,
        "{{TEMPERATURE_C}}": str(temperature_c),
    }
    rendered = template
    for token, value in values.items():
        rendered = rendered.replace(token, value)
    if "{{" in rendered or "}}" in rendered:
        raise ContractError("unresolved testbench template token")
    return rendered


def run_closure_task(
    task_id: str,
    pdk_root: Path,
    output_root: Path,
    candidate: Optional[Path] = None,
    track_root: Path = DEFAULT_TRACK_ROOT,
    ngspice: str = "ngspice",
    timeout_seconds: int = 180,
) -> Dict[str, Any]:
    task = load_closure_task(task_id, track_root)
    try:
        model_lib = resolve_sky130_model_root(pdk_root)
    except ContractError:
        return {
            "schema_version": "1.0", "task_id": task_id, "status": "INFRA_FAIL", "passed": False,
            "reason": "model_entry_unavailable",
        }
    model_entry_sha256 = sha256_file(model_lib)
    if model_entry_sha256 != expected_sky130_entry_sha256(track_root):
        return {
            "schema_version": "1.0", "task_id": task_id, "status": "INFRA_FAIL", "passed": False,
            "reason": "model_entry_hash_mismatch", "model_entry_sha256": model_entry_sha256,
        }
    executable = shutil.which(ngspice)
    if executable is None:
        return {"schema_version": "1.0", "task_id": task_id, "status": "INFRA_FAIL", "passed": False, "reason": "ngspice_unavailable"}
    task_dir = track_root / "tasks" / task_id
    candidate_path = candidate.resolve() if candidate else (task_dir / task["starter_candidate"]).resolve()
    policy = scan_dut_policy(candidate_path)
    output_root.mkdir(parents=True, exist_ok=True)
    run_root = output_root / task_id
    run_root.mkdir(parents=True, exist_ok=True)
    local_candidate = run_root / "candidate.sp"
    shutil.copy2(candidate_path, local_candidate)
    candidate_sha256 = sha256_file(local_candidate)
    scenarios: List[Dict[str, Any]] = []
    started = utc_timestamp()
    wall_start = time.monotonic()
    if policy["status"] != "PASS":
        result = {
            "schema_version": "1.0", "task_id": task_id, "title": task["title"],
            "status": "POLICY_FAIL", "passed": False, "candidate_sha256": candidate_sha256,
            "model_provider": "sky130", "model_entry_sha256": model_entry_sha256,
            "policy": policy, "scenarios": [], "started_at": started,
            "duration_seconds": round(time.monotonic() - wall_start, 6),
        }
        dump_json(run_root / "result.json", result)
        return result
    for index, scenario in enumerate(task["scenarios"]):
        scenario_id = scenario["scenario_id"]
        template_path = task_dir / scenario["bench_template"]
        deck = run_root / ("%02d_%s.sp" % (index + 1, scenario_id))
        log = run_root / ("%02d_%s.log" % (index + 1, scenario_id))
        rendered = _render_deck(
            template_path.read_text(encoding="utf-8"), model_lib, local_candidate.name,
            scenario.get("corner", "tt"), float(scenario.get("temperature_c", 27.0)),
        )
        deck.write_text(rendered, encoding="utf-8")
        start = time.monotonic()
        try:
            completed = subprocess.run(
                [executable, "-b", "-o", str(log), str(deck)],
                cwd=str(run_root), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=timeout_seconds, check=False,
            )
            duration = round(time.monotonic() - start, 6)
        except subprocess.TimeoutExpired:
            scenarios.append({"scenario_id": scenario_id, "corner": scenario.get("corner", "tt"), "status": "INFRA_FAIL", "reason": "ngspice_timeout"})
            continue
        log_text = log.read_text(encoding="utf-8", errors="replace") if log.is_file() else ""
        measurements = parse_measurements(log_text)
        limits_passed, checks = _check_limits(measurements, scenario["limits"])
        missing = any(item["status"] == "MISSING" for item in checks)
        if completed.returncode != 0 and INFRA_LOG_RE.search(log_text):
            status, reason = "INFRA_FAIL", "ngspice_environment_or_model_error"
        elif completed.returncode != 0:
            status, reason = "CIRCUIT_FAIL", "candidate_simulation_error"
        elif missing and re.search(r"(?i)measure\s+\S+.*out of interval|\.meas\s+.*failed", log_text):
            status, reason = "CIRCUIT_FAIL", "measurement_threshold_not_reached"
        elif missing:
            status, reason = "MEAS_FAIL", "declared_measurement_missing"
        elif not limits_passed:
            status, reason = "CIRCUIT_FAIL", "specification_not_met"
        else:
            status, reason = "PASS", None
        deck_sha256 = sha256_file(deck)
        log_sha256 = sha256_file(log) if log.is_file() else None
        evidence_sha256 = sha256_text(":".join((candidate_sha256, deck_sha256, log_sha256 or "missing")))
        scenarios.append({
            "scenario_id": scenario_id,
            "corner": scenario.get("corner", "tt"),
            "temperature_c": scenario.get("temperature_c", 27.0),
            "status": status,
            "reason": reason,
            "measurements": measurements,
            "checks": checks,
            "deck_sha256": deck_sha256,
            "log_sha256": log_sha256,
            "evidence_sha256": evidence_sha256,
            "duration_seconds": duration,
        })
    passed = policy["status"] == "PASS" and all(item["status"] == "PASS" for item in scenarios)
    if policy["status"] != "PASS":
        status = "POLICY_FAIL"
    elif any(item["status"] == "INFRA_FAIL" for item in scenarios):
        status = "INFRA_FAIL"
    elif any(item["status"] == "MEAS_FAIL" for item in scenarios):
        status = "MEAS_FAIL"
    else:
        status = "PASS" if passed else "CIRCUIT_FAIL"
    result = {
        "schema_version": "1.0",
        "task_id": task_id,
        "title": task["title"],
        "status": status,
        "passed": passed,
        "candidate_sha256": candidate_sha256,
        "model_provider": "sky130",
        "model_entry_sha256": model_entry_sha256,
        "policy": policy,
        "scenarios": scenarios,
        "started_at": started,
        "duration_seconds": round(time.monotonic() - wall_start, 6),
    }
    dump_json(run_root / "result.json", result)
    return result


def run_closure_suite(
    task_ids: Sequence[str], pdk_root: Path, output_root: Path, candidate: Optional[Path] = None,
    track_root: Path = DEFAULT_TRACK_ROOT, ngspice: str = "ngspice", timeout_seconds: int = 180,
) -> Dict[str, Any]:
    results = [
        run_closure_task(task_id, pdk_root, output_root, candidate, track_root, ngspice, timeout_seconds)
        for task_id in task_ids
    ]
    return {
        "schema_version": "1.0",
        "status": "PASS" if all(item.get("passed") for item in results) else "FAIL",
        "passed": all(item.get("passed") for item in results),
        "task_count": len(results),
        "passed_task_count": sum(1 for item in results if item.get("passed")),
        "results": results,
    }
