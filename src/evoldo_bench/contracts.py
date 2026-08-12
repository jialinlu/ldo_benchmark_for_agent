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
    "eda_tool",
}
ALLOWED_LEVELS = {"L1", "L2", "L3", "L4", "L5"}
ALLOWED_VARIANTS = {"canonical", "metamorphic", "counterexample", "regime", "difficulty"}
ALLOWED_SPLITS = {"dev", "validation", "test", "sealed"}
ALLOWED_MODES = {
    "direct_reasoning",
    "knowledge_assisted",
    "agentic_skill",
    "simulation_assisted",
    "full_design",
    "weak_agent_airgap",
    "sizing_assisted",
    "eda_assisted",
}
ALLOWED_CHECKS = {
    "choice_credit",
    "exact",
    "set_equals",
    "set_contains",
    "set_excludes",
    "numeric_close",
    "nonempty",
    "ranking_pairwise",
    "set_f1",
    "boolean",
    "sequence_alignment",
    "numeric_score",
    "numeric_range",
    "mapping_credit",
    "multilabel_mapping_credit",
}
ALLOWED_EXTERNAL_NETWORK_POLICIES = {"no_network", "provider_control_plane_only"}
ALLOWED_DEPLOYMENT_TIERS = {
    "T0_foundation",
    "T1_local_advice",
    "T2_bounded_workflow",
    "T3_multi_constraint_closure",
    "T4_end_to_end_planning",
}
ALLOWED_ARTIFACT_FIELD_TYPES = {
    "string", "boolean", "number", "string_list", "number_map", "string_map",
    "string_list_map", "object"
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


def _validate_network_and_tool_policy(data: Dict[str, Any]) -> None:
    network = data.get("network_policy")
    tools = data.get("tool_policy")
    if not isinstance(network, dict):
        raise ContractError("task.network_policy must be an object")
    if network.get("model_web_search") != "forbidden":
        raise ContractError("task.network_policy.model_web_search must be forbidden")
    if network.get("external_network") not in ALLOWED_EXTERNAL_NETWORK_POLICIES:
        raise ContractError("unsupported task.network_policy.external_network")
    if not isinstance(tools, dict):
        raise ContractError("task.tool_policy must be an object")
    _string_list(tools.get("allowed_tools", []), "task.tool_policy.allowed_tools")
    forbidden = _string_list(
        tools.get("forbidden_tools", []), "task.tool_policy.forbidden_tools", allow_empty=False
    )
    required_forbidden = {"web_search", "browser", "remote_fetch"}
    missing_forbidden = sorted(required_forbidden.difference(forbidden))
    if missing_forbidden:
        raise ContractError(
            "task.tool_policy.forbidden_tools is missing: %s" % ", ".join(missing_forbidden)
        )


def _validate_artifact_field(name: str, value: Any, spec: Dict[str, Any]) -> None:
    field_type = spec.get("type")
    if field_type not in ALLOWED_ARTIFACT_FIELD_TYPES:
        raise ContractError("unsupported artifact field type for %s" % name)
    if field_type == "string":
        if not isinstance(value, str) or not value.strip():
            raise ContractError("answer.artifact.%s must be a non-empty string" % name)
        allowed = spec.get("allowed")
        if allowed is not None and (not isinstance(allowed, list) or value not in allowed):
            raise ContractError("answer.artifact.%s is outside the controlled vocabulary" % name)
    elif field_type == "boolean":
        if not isinstance(value, bool):
            raise ContractError("answer.artifact.%s must be boolean" % name)
    elif field_type == "number":
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ContractError("answer.artifact.%s must be numeric" % name)
    elif field_type == "string_list":
        values = _string_list(
            value, "answer.artifact.%s" % name, allow_empty=bool(spec.get("allow_empty", False))
        )
        minimum = int(spec.get("min_items", 0))
        maximum = spec.get("max_items")
        if len(values) < minimum or (maximum is not None and len(values) > int(maximum)):
            raise ContractError("answer.artifact.%s has an invalid item count" % name)
        allowed = spec.get("allowed")
        if allowed is not None:
            if not isinstance(allowed, list):
                raise ContractError("artifact contract allowed values must be a list")
            invalid = sorted(set(values).difference(allowed))
            if invalid:
                raise ContractError(
                    "answer.artifact.%s contains values outside the controlled vocabulary: %s"
                    % (name, ", ".join(invalid))
                )
    elif field_type in {"number_map", "string_map", "string_list_map"}:
        if not isinstance(value, dict):
            raise ContractError("answer.artifact.%s must be an object" % name)
        allowed_keys = spec.get("allowed_keys")
        required_keys = spec.get("required_keys", [])
        if not isinstance(required_keys, list) or any(not isinstance(item, str) for item in required_keys):
            raise ContractError("artifact contract required_keys must be a string list")
        missing = sorted(set(required_keys).difference(value))
        if missing:
            raise ContractError("answer.artifact.%s is missing keys: %s" % (name, ", ".join(missing)))
        if allowed_keys is not None:
            if not isinstance(allowed_keys, list) or any(not isinstance(item, str) for item in allowed_keys):
                raise ContractError("artifact contract allowed_keys must be a string list")
            unexpected = sorted(set(value).difference(allowed_keys))
            if unexpected:
                raise ContractError("answer.artifact.%s has unexpected keys: %s" % (name, ", ".join(unexpected)))
        if field_type == "number_map":
            wrong = any(not isinstance(item, (int, float)) or isinstance(item, bool) for item in value.values())
        elif field_type == "string_map":
            wrong = any(not isinstance(item, str) for item in value.values())
        else:
            wrong = any(
                not isinstance(item, list)
                or any(not isinstance(member, str) for member in item)
                or len(item) != len(set(item))
                for item in value.values()
            )
        if wrong:
            raise ContractError("answer.artifact.%s has values of the wrong type" % name)
        value_allowed = spec.get("value_allowed")
        if value_allowed is not None:
            mapped_values = (
                [member for items in value.values() for member in items]
                if field_type == "string_list_map" else list(value.values())
            )
            if any(item not in value_allowed for item in mapped_values):
                raise ContractError("answer.artifact.%s contains an invalid mapped value" % name)
    elif field_type == "object" and not isinstance(value, dict):
        raise ContractError("answer.artifact.%s must be an object" % name)


def _validate_v3_answer(
    data: Dict[str, Any], task: Optional["Task"], allow_field_errors: bool = False,
) -> Dict[str, Any]:
    _required(data, ["schema_version", "task_id", "artifact", "claim_boundary", "confidence"], "answer")
    if not isinstance(data["task_id"], str) or not data["task_id"].strip():
        raise ContractError("answer.task_id must be a non-empty string")
    if not isinstance(data["artifact"], dict) or not data["artifact"]:
        raise ContractError("answer.artifact must be a non-empty object")
    if not isinstance(data["claim_boundary"], str) or not data["claim_boundary"].strip():
        raise ContractError("answer.claim_boundary must be a non-empty string")
    confidence = data["confidence"]
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 <= confidence <= 1:
        raise ContractError("answer.confidence must be a number in [0, 1]")
    if task is None:
        return data
    case_paths = [path for path in task.input_paths if path.name == "case.json"]
    if not case_paths:
        raise ContractError("task does not provide case.json")
    case = load_json(case_paths[0])
    contract = case.get("answer_contract")
    if not isinstance(contract, dict) or not isinstance(contract.get("fields"), dict):
        raise ContractError("schema 3.0 task case is missing answer_contract.fields")
    fields = contract["fields"]
    required = {name for name, spec in fields.items() if isinstance(spec, dict) and spec.get("required", True)}
    missing = sorted(required.difference(data["artifact"]))
    unexpected = sorted(set(data["artifact"]).difference(fields))
    if missing or (unexpected and not contract.get("additional_fields", False)):
        raise ContractError("answer artifact mismatch; missing=%s unexpected=%s" % (missing, unexpected))
    for name, value in data["artifact"].items():
        if name in fields:
            spec = fields[name]
            if not isinstance(spec, dict):
                raise ContractError("artifact field contract must be an object")
            if allow_field_errors:
                try:
                    _validate_artifact_field(name, value, spec)
                except ContractError:
                    continue
            else:
                _validate_artifact_field(name, value, spec)
    return data


def validate_answer_for_grading(data: Dict[str, Any], task: "Task") -> Dict[str, Any]:
    """Validate answer ownership/envelope; atomic checks score malformed v3 fields as zero."""
    if data.get("schema_version") == "3.0":
        return _validate_v3_answer(data, task, allow_field_errors=True)
    return validate_answer(data, task)


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
        return self.source_path(self.data["prompt_file"])

    @property
    def input_paths(self) -> List[Path]:
        return [self.source_path(item) for item in self.data["input_files"]]

    @property
    def package_style(self) -> str:
        return "demo_task" if not (self.root / "task.json").is_file() and (self.root / "task.toml").is_file() else "legacy"

    @property
    def manifest_path(self) -> Path:
        return self.root / ("task.toml" if self.package_style == "demo_task" else "task.json")

    def source_path(self, value: str) -> Path:
        relative = safe_relative_path(value)
        direct = self.root / relative
        if direct.is_file():
            return direct
        starter = self.root / "environment" / "starter" / relative
        return starter


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
    if data["schema_version"] not in {"1.0", "2.0", "3.0"}:
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
    if data["schema_version"] == "3.0":
        _validate_network_and_tool_policy(data)
        tier = data.get("deployment_tier")
        if tier not in ALLOWED_DEPLOYMENT_TIERS:
            raise ContractError("unsupported task.deployment_tier")
        if data.get("knowledge_effect_expectation") not in {
            "benefit_expected", "neutral_expected", "override_resistant",
        }:
            raise ContractError("unsupported task.knowledge_effect_expectation")
        if data["budget"]["max_tool_calls"] == 0 and data["tool_policy"].get("allowed_tools"):
            raise ContractError("zero-tool tasks must have an empty allowed_tools list")
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
            relative = safe_relative_path(value)
            path = root / relative
            if not path.is_file():
                path = root / "environment" / "starter" / relative
            if not path.is_file():
                raise ContractError("referenced task file does not exist: %s" % path)
    return data


def load_task(task_dir: Path) -> Task:
    manifest = task_dir / "task.json"
    if manifest.is_file():
        data = load_json(manifest)
    else:
        package_manifest = task_dir / "task.toml"
        manifest = task_dir / "environment" / "starter" / "task_contract.json"
        if not package_manifest.is_file() or not manifest.is_file():
            raise ContractError("task.toml and environment/starter/task_contract.json not found: %s" % task_dir)
        data = load_json(manifest)
    validate_task(data, task_dir)
    return Task(task_dir, data)


def validate_answer(data: Dict[str, Any], task: Optional[Task] = None) -> Dict[str, Any]:
    if data.get("schema_version") == "3.0":
        return _validate_v3_answer(data, task)
    if data.get("schema_version") == "2.0":
        _required(data, ["schema_version", "task_id", "answers", "claim_boundary", "confidence"], "answer")
        if not isinstance(data["task_id"], str) or not data["task_id"].strip():
            raise ContractError("answer.task_id must be a non-empty string")
        if not isinstance(data["answers"], dict):
            raise ContractError("answer.answers must be an object")
        if not isinstance(data["claim_boundary"], str) or not data["claim_boundary"].strip():
            raise ContractError("answer.claim_boundary must be a non-empty string")
        confidence = data["confidence"]
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 <= confidence <= 1:
            raise ContractError("answer.confidence must be a number in [0, 1]")
        if task is not None:
            case_paths = [path for path in task.input_paths if path.name == "case.json"]
            if not case_paths:
                raise ContractError("task does not provide case.json")
            case = load_json(case_paths[0])
            question_ids = {item["id"] for item in case.get("questions", []) if isinstance(item, dict) and "id" in item}
            missing = sorted(question_ids.difference(data["answers"]))
            unexpected = sorted(set(data["answers"]).difference(question_ids))
            if missing or unexpected:
                raise ContractError("answer question mismatch; missing=%s unexpected=%s" % (missing, unexpected))
            for question in case.get("questions", []):
                qid = question["id"]
                actual = data["answers"][qid]
                kind = question.get("kind")
                option_ids = {
                    option["id"] for option in question.get("options", [])
                    if isinstance(option, dict) and isinstance(option.get("id"), str)
                }
                if kind in {"single_choice", "ordered_choice"}:
                    if not isinstance(actual, str) or actual not in option_ids:
                        raise ContractError("answer.answers.%s must be one declared option ID" % qid)
                elif kind == "ranked_choice":
                    ranked = _string_list(actual, "answer.answers.%s" % qid, allow_empty=False)
                    invalid = sorted(set(ranked).difference(option_ids))
                    if invalid:
                        raise ContractError("answer.answers.%s contains undeclared options: %s" % (qid, invalid))
                elif kind == "multi_select":
                    selected = _string_list(actual, "answer.answers.%s" % qid, allow_empty=False)
                    count = question.get("select_count")
                    if not isinstance(count, int) or count <= 0:
                        raise ContractError("task question %s has invalid select_count" % qid)
                    invalid = sorted(set(selected).difference(option_ids))
                    if invalid:
                        raise ContractError("answer.answers.%s contains undeclared options: %s" % (qid, invalid))
                elif kind == "numeric":
                    if not isinstance(actual, (int, float)) or isinstance(actual, bool):
                        raise ContractError("answer.answers.%s must be numeric" % qid)
        return data
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
    if "relevant_knowledge_ids" in data:
        _string_list(
            data["relevant_knowledge_ids"], "oracle.relevant_knowledge_ids"
        )
    total = 0.0
    ids = set()
    for check in data["checks"]:
        if not isinstance(check, dict):
            raise ContractError("oracle check must be an object")
        _required(check, ["id", "path", "kind", "weight"], "oracle check")
        if check["id"] in ids:
            raise ContractError("duplicate oracle check id: %s" % check["id"])
        ids.add(check["id"])
        if "dimension" in check and (not isinstance(check["dimension"], str) or not check["dimension"].strip()):
            raise ContractError("oracle check dimension must be a non-empty string")
        if check["kind"] not in ALLOWED_CHECKS:
            raise ContractError("unsupported check kind: %s" % check["kind"])
        if not isinstance(check["weight"], (int, float)) or check["weight"] <= 0:
            raise ContractError("check weight must be positive")
        if check["kind"] not in {"nonempty", "numeric_range"} and "expected" not in check:
            raise ContractError("check %s requires expected" % check["id"])
        if check["kind"] == "choice_credit":
            credits = check.get("credits")
            if not isinstance(credits, dict) or not credits:
                raise ContractError("choice_credit requires a non-empty credits object")
            if any(not isinstance(option, str) or not option for option in credits):
                raise ContractError("choice_credit option IDs must be non-empty strings")
            if any(
                not isinstance(credit, (int, float))
                or isinstance(credit, bool)
                or not 0 <= float(credit) <= 1
                for credit in credits.values()
            ):
                raise ContractError("choice_credit values must be numeric fractions in [0, 1]")
            if check["expected"] not in credits or float(credits[check["expected"]]) != 1.0:
                raise ContractError("choice_credit expected option must receive full credit")
            threshold = check.get("critical_credit_threshold", 1.0)
            if (
                not isinstance(threshold, (int, float))
                or isinstance(threshold, bool)
                or not 0 <= float(threshold) <= 1
            ):
                raise ContractError("critical_credit_threshold must be in [0, 1]")
        if check["kind"] in {"ranking_pairwise", "sequence_alignment", "set_contains", "set_excludes", "set_f1"}:
            _string_list(check["expected"], "oracle check %s expected" % check["id"])
        if check["kind"] in {"ranking_pairwise", "sequence_alignment"} and len(check["expected"]) < 2:
            raise ContractError("%s requires at least two expected items" % check["kind"])
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
        if check["kind"] == "numeric_score":
            if not isinstance(check.get("expected"), (int, float)) or isinstance(check.get("expected"), bool):
                raise ContractError("numeric_score expected must be numeric")
            full = check.get("full_tolerance")
            zero = check.get("zero_tolerance")
            if (
                not isinstance(full, (int, float)) or isinstance(full, bool) or full < 0
                or not isinstance(zero, (int, float)) or isinstance(zero, bool) or zero <= full
            ):
                raise ContractError("numeric_score requires 0 <= full_tolerance < zero_tolerance")
        if check["kind"] == "numeric_range":
            minimum = check.get("minimum")
            maximum = check.get("maximum")
            partial_minimum = check.get("partial_minimum", minimum)
            partial_maximum = check.get("partial_maximum", maximum)
            values = (minimum, maximum, partial_minimum, partial_maximum)
            if any(not isinstance(value, (int, float)) or isinstance(value, bool) for value in values):
                raise ContractError("numeric_range bounds must be numeric")
            if not partial_minimum <= minimum <= maximum <= partial_maximum:
                raise ContractError("numeric_range bounds are not ordered")
        if check["kind"] == "mapping_credit":
            if not isinstance(check.get("expected"), dict) or not check["expected"]:
                raise ContractError("mapping_credit expected must be a non-empty object")
        if check["kind"] == "multilabel_mapping_credit":
            expected_mapping = check.get("expected")
            if not isinstance(expected_mapping, dict) or not expected_mapping:
                raise ContractError("multilabel_mapping_credit expected must be a non-empty object")
            for key, values in expected_mapping.items():
                if not isinstance(key, str) or not key:
                    raise ContractError("multilabel_mapping_credit keys must be non-empty strings")
                _string_list(values, "oracle check %s expected.%s" % (check["id"], key))
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
