from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from .errors import ContractError
from .utils import load_json, safe_relative_path

ALLOWED_SUITES = {
    "structure",
    "trend",
    "diagnosis",
    "sizing",
    "migration",
    "system_impact",
    "design_closure",
    "architecture_choice",
}
ALLOWED_LEVELS = {"L1", "L2", "L3", "L4", "L5"}
ALLOWED_VARIANTS = {"canonical", "metamorphic", "counterexample", "regime", "difficulty"}
ALLOWED_SPLITS = {"dev", "validation", "test", "sealed"}
ALLOWED_MODES = {
    "direct_reasoning",
    "agentic_skill",
    "simulation_assisted",
    "full_design",
    "weak_agent_airgap",
}
ALLOWED_CHECKS = {
    "exact",
    "set_equals",
    "set_contains",
    "set_excludes",
    "numeric_close",
    "nonempty",
    "boolean",
}
ALLOWED_PROBE_REGIMES = {"op", "dc", "ac", "stb", "noise", "tran", "startup"}
ALLOWED_PROBE_FAMILIES = {
    "operating_point",
    "port_impedance",
    "three_point_trend",
    "loop_gain",
    "noise_transfer",
    "startup_escape",
    "transient_envelope",
}
ALLOWED_PROBE_USES = {"support", "falsify", "disambiguate"}


def _required(mapping: Mapping[str, Any], fields: Iterable[str], kind: str) -> None:
    missing = [field for field in fields if field not in mapping]
    if missing:
        raise ContractError("%s missing required fields: %s" % (kind, ", ".join(missing)))


def _string_list(value: Any, field: str, allow_empty: bool = True) -> List[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ContractError("%s must be a list of strings" % field)
    if not allow_empty and not value:
        raise ContractError("%s must not be empty" % field)
    if len(value) != len(set(value)):
        raise ContractError("%s must not contain duplicates" % field)
    return list(value)


@dataclass(frozen=True)
class Task:
    root: Path
    data: Dict[str, Any]

    @property
    def task_id(self) -> str:
        return self.data["task_id"]

    @property
    def family_id(self) -> str:
        return self.data["family_id"]

    @property
    def suite(self) -> str:
        return self.data["suite"]

    @property
    def split(self) -> str:
        return self.data["split"]

    @property
    def variant(self) -> str:
        return self.data["variant"]

    @property
    def prompt_path(self) -> Path:
        return self.root / safe_relative_path(self.data["prompt_file"])

    @property
    def input_paths(self) -> List[Path]:
        return [self.root / safe_relative_path(item) for item in self.data["input_files"]]


def validate_task(data: Dict[str, Any], root: Optional[Path] = None) -> Dict[str, Any]:
    _required(
        data,
        [
            "schema_version",
            "task_id",
            "family_id",
            "lineage_id",
            "split",
            "variant",
            "suite",
            "level",
            "capabilities",
            "title",
            "language",
            "prompt_file",
            "input_files",
            "answer_template_file",
            "eligible_modes",
            "budget",
        ],
        "task",
    )
    if data["schema_version"] != "1.0":
        raise ContractError("unsupported task schema_version: %s" % data["schema_version"])
    for field in ["task_id", "family_id", "lineage_id", "title", "language", "prompt_file", "answer_template_file"]:
        if not isinstance(data[field], str) or not data[field].strip():
            raise ContractError("task.%s must be a non-empty string" % field)
    if data["split"] not in ALLOWED_SPLITS:
        raise ContractError("unsupported split: %s" % data["split"])
    if data["variant"] not in ALLOWED_VARIANTS:
        raise ContractError("unsupported variant: %s" % data["variant"])
    if data["suite"] not in ALLOWED_SUITES:
        raise ContractError("unsupported suite: %s" % data["suite"])
    if data["level"] not in ALLOWED_LEVELS:
        raise ContractError("unsupported level: %s" % data["level"])
    _string_list(data["capabilities"], "task.capabilities", allow_empty=False)
    _string_list(data["input_files"], "task.input_files", allow_empty=False)
    modes = _string_list(data["eligible_modes"], "task.eligible_modes", allow_empty=False)
    if any(mode not in ALLOWED_MODES for mode in modes):
        raise ContractError("task contains unsupported eligible mode")
    budget = data["budget"]
    if not isinstance(budget, dict):
        raise ContractError("task.budget must be an object")
    _required(budget, ["timeout_seconds", "max_tool_calls"], "task.budget")
    if not isinstance(budget["timeout_seconds"], int) or budget["timeout_seconds"] <= 0:
        raise ContractError("budget.timeout_seconds must be a positive integer")
    if not isinstance(budget["max_tool_calls"], int) or budget["max_tool_calls"] < 0:
        raise ContractError("budget.max_tool_calls must be a non-negative integer")
    if "probe_policy" in data:
        policy = data["probe_policy"]
        if not isinstance(policy, dict):
            raise ContractError("task.probe_policy must be an object")
        for field in ("allowed_regimes", "allowed_probe_families", "required_held_fixed"):
            values = _string_list(policy.get(field, []), "task.probe_policy.%s" % field)
            if field == "allowed_regimes" and any(value not in ALLOWED_PROBE_REGIMES for value in values):
                raise ContractError("task probe policy contains unsupported regime")
            if field == "allowed_probe_families" and any(value not in ALLOWED_PROBE_FAMILIES for value in values):
                raise ContractError("task probe policy contains unsupported probe family")
    if root is not None:
        referenced = [data["prompt_file"], data["answer_template_file"]] + list(data["input_files"])
        for value in referenced:
            path = root / safe_relative_path(value)
            if not path.is_file():
                raise ContractError("referenced task file does not exist: %s" % path)
    return data


def load_task(task_dir: Path) -> Task:
    manifest = task_dir / "task.json"
    if not manifest.is_file():
        raise ContractError("task.json not found: %s" % task_dir)
    data = load_json(manifest)
    validate_task(data, task_dir)
    return Task(task_dir, data)


def validate_answer(data: Dict[str, Any], task: Optional[Task] = None) -> Dict[str, Any]:
    _required(
        data,
        [
            "schema_version",
            "task_id",
            "conclusion",
            "analysis_regime",
            "held_fixed",
            "evidence_facts",
            "mechanism_tags",
            "recommended_actions",
            "mechanism",
            "claim_boundary",
            "confidence",
        ],
        "answer",
    )
    if data["schema_version"] != "1.0":
        raise ContractError("unsupported answer schema_version: %s" % data["schema_version"])
    for field in ["schema_version", "task_id", "conclusion", "analysis_regime", "mechanism", "claim_boundary"]:
        if not isinstance(data[field], str) or not data[field].strip():
            raise ContractError("answer.%s must be a non-empty string" % field)
    for field in ["held_fixed", "evidence_facts", "mechanism_tags", "recommended_actions"]:
        _string_list(data[field], "answer.%s" % field)
    confidence = data["confidence"]
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 <= confidence <= 1:
        raise ContractError("answer.confidence must be a number in [0, 1]")
    if "numeric_results" in data:
        values = data["numeric_results"]
        if not isinstance(values, dict):
            raise ContractError("answer.numeric_results must be an object")
        for key, value in values.items():
            if not isinstance(key, str) or not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ContractError("numeric_results must map strings to numbers")
    if task is not None:
        case_paths = [path for path in task.input_paths if path.name == "case.json"]
        if not case_paths:
            raise ContractError("task does not provide inputs/case.json for controlled answer validation")
        case = load_json(case_paths[0])
        vocabulary = case.get("controlled_vocabulary")
        if not isinstance(vocabulary, dict):
            raise ContractError("task case is missing controlled_vocabulary")
        for field in ("conclusion", "analysis_regime"):
            allowed = vocabulary.get(field)
            if not isinstance(allowed, list) or data[field] not in allowed:
                raise ContractError("answer.%s is outside the task controlled vocabulary" % field)
        for field in ("held_fixed", "evidence_facts", "mechanism_tags", "recommended_actions"):
            allowed = vocabulary.get(field)
            if not isinstance(allowed, list):
                raise ContractError("task controlled vocabulary is missing %s" % field)
            invalid = sorted(set(data[field]).difference(allowed))
            if invalid:
                raise ContractError(
                    "answer.%s contains values outside the task controlled vocabulary: %s"
                    % (field, ", ".join(invalid))
                )
    return data


def validate_probe_contract(data: Dict[str, Any]) -> Dict[str, Any]:
    _required(
        data,
        [
            "schema_version",
            "task_id",
            "question",
            "analysis_regime",
            "held_fixed",
            "probe_family",
            "intervention",
            "measurement",
            "expected_use",
            "stop_condition",
            "claim_boundary",
        ],
        "probe contract",
    )
    if data["schema_version"] != "1.0":
        raise ContractError("unsupported probe schema_version: %s" % data["schema_version"])
    for field in ["schema_version", "task_id", "question", "claim_boundary"]:
        if not isinstance(data[field], str) or not data[field].strip():
            raise ContractError("probe.%s must be a non-empty string" % field)
    if data["analysis_regime"] not in ALLOWED_PROBE_REGIMES:
        raise ContractError("unsupported probe analysis regime: %s" % data["analysis_regime"])
    if data["probe_family"] not in ALLOWED_PROBE_FAMILIES:
        raise ContractError("unsupported probe family: %s" % data["probe_family"])
    if data["expected_use"] not in ALLOWED_PROBE_USES:
        raise ContractError("unsupported expected use: %s" % data["expected_use"])
    _string_list(data["held_fixed"], "probe.held_fixed")
    if "source_artifacts" in data:
        _string_list(data["source_artifacts"], "probe.source_artifacts")
    for field in ["intervention", "measurement", "stop_condition"]:
        if not isinstance(data[field], dict):
            raise ContractError("probe.%s must be an object" % field)
    if not data["measurement"]:
        raise ContractError("probe.measurement must not be empty")
    if not data["stop_condition"]:
        raise ContractError("probe.stop_condition must not be empty")
    return data


def validate_oracle(data: Dict[str, Any]) -> Dict[str, Any]:
    _required(data, ["schema_version", "task_id", "family_id", "checks"], "oracle")
    if data["schema_version"] != "1.0":
        raise ContractError("unsupported oracle schema_version: %s" % data["schema_version"])
    if not isinstance(data["checks"], list) or not data["checks"]:
        raise ContractError("oracle.checks must be a non-empty list")
    total = 0.0
    ids = set()
    for check in data["checks"]:
        if not isinstance(check, dict):
            raise ContractError("oracle check must be an object")
        _required(check, ["id", "path", "kind", "weight"], "oracle check")
        if check["id"] in ids:
            raise ContractError("duplicate oracle check id: %s" % check["id"])
        ids.add(check["id"])
        if check["kind"] not in ALLOWED_CHECKS:
            raise ContractError("unsupported check kind: %s" % check["kind"])
        if not isinstance(check["weight"], (int, float)) or check["weight"] <= 0:
            raise ContractError("check weight must be positive")
        if check["kind"] not in {"nonempty"} and "expected" not in check:
            raise ContractError("check %s requires expected" % check["id"])
        if check["kind"] in {"set_contains", "set_excludes"}:
            _string_list(check["expected"], "oracle check %s expected" % check["id"])
        if check["kind"] == "numeric_close":
            if "absolute_tolerance" not in check and "relative_tolerance" not in check:
                raise ContractError("numeric_close requires a tolerance")
            if (
                not isinstance(check["expected"], (int, float))
                or isinstance(check["expected"], bool)
            ):
                raise ContractError("numeric_close expected must be numeric")
            for tolerance in ["absolute_tolerance", "relative_tolerance"]:
                if tolerance in check and (
                    not isinstance(check[tolerance], (int, float))
                    or isinstance(check[tolerance], bool)
                    or check[tolerance] < 0
                ):
                    raise ContractError("%s must be a non-negative number" % tolerance)
        total += float(check["weight"])
    if abs(total - 100.0) > 1e-9:
        raise ContractError("oracle weights must sum to 100, got %s" % total)
    cap = data.get("critical_failure_cap", 49.0)
    if not isinstance(cap, (int, float)) or not 0 <= cap <= 100:
        raise ContractError("critical_failure_cap must be in [0, 100]")
    threshold = data.get("pass_threshold", 70.0)
    if not isinstance(threshold, (int, float)) or not 0 <= threshold <= 100:
        raise ContractError("pass_threshold must be in [0, 100]")
    return data
