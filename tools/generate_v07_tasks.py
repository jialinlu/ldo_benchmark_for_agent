#!/usr/bin/env python3
"""Generate EvoLDO v0.7 workflow tasks in the Analog Arena demo-task layout.

The cases are clean-room synthetic engineering fixtures inspired by failure classes and
workflow gates observed in a real LDO automation project.  They do not copy private PDK
values, netlists, or project answers.  Edit this generator, not generated packages.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from copy import deepcopy
from pathlib import Path
import random
from typing import Any, Dict, List, Optional, Tuple


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "benchmarks" / "ldo_v07"
TASKS = OUT / "tasks"
ORACLES = OUT / "dev_reference" / "oracles"
KNOWLEDGE = OUT / "knowledge"
VERSION = "0.7.0"
BASE_IMAGE = "python:3.12-slim"
SKY130_IMAGE = "ghcr.io/arcadia-1/circuit-bench-sky130-ngspice@sha256:bd5c425675eb99fc1a2c3bca10b63a871c457613767e2c6984d6c207b3160500"


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def field_string(values: List[str], required: bool = True) -> Dict[str, Any]:
    return {"type": "string", "allowed": values, "required": required}


def field_list(values: List[str], minimum: int = 1, maximum: Optional[int] = None) -> Dict[str, Any]:
    result: Dict[str, Any] = {"type": "string_list", "allowed": values, "min_items": minimum}
    if maximum is not None:
        result["max_items"] = maximum
    return result


def field_map(keys: List[str], values: List[str]) -> Dict[str, Any]:
    return {"type": "string_map", "required_keys": keys, "allowed_keys": keys, "value_allowed": values}


def field_list_map(keys: List[str], values: List[str]) -> Dict[str, Any]:
    return {"type": "string_list_map", "required_keys": keys, "allowed_keys": keys, "value_allowed": values}


def exact(cid: str, path: str, expected: Any, weight: float, dimension: str,
          critical: bool = False, credits: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    check = {"id": cid, "path": "artifact." + path, "kind": "exact", "expected": expected,
             "weight": weight, "dimension": dimension, "critical": critical}
    if credits is not None:
        check.update({"kind": "choice_credit", "credits": credits})
        if critical:
            check["critical_credit_threshold"] = 0.01
    return check


def sequence(cid: str, path: str, expected: List[str], weight: float, dimension: str) -> Dict[str, Any]:
    return {"id": cid, "path": "artifact." + path, "kind": "sequence_alignment",
            "expected": expected, "weight": weight, "dimension": dimension}


def set_f1(cid: str, path: str, expected: List[str], weight: float, dimension: str,
           critical: bool = False) -> Dict[str, Any]:
    return {"id": cid, "path": "artifact." + path, "kind": "set_f1", "expected": expected,
            "weight": weight, "dimension": dimension, "critical": critical,
            **({"critical_credit_threshold": 0.01} if critical else {})}


def mapping(cid: str, path: str, expected: Dict[str, str], weight: float, dimension: str) -> Dict[str, Any]:
    return {"id": cid, "path": "artifact." + path, "kind": "mapping_credit",
            "expected": expected, "weight": weight, "dimension": dimension}


def multilabel_mapping(cid: str, path: str, expected: Dict[str, List[str]], weight: float,
                       dimension: str) -> Dict[str, Any]:
    return {"id": cid, "path": "artifact." + path, "kind": "multilabel_mapping_credit",
            "expected": expected, "weight": weight, "dimension": dimension}


def numeric(cid: str, path: str, expected: float, full: float, zero: float,
            weight: float, dimension: str) -> Dict[str, Any]:
    return {"id": cid, "path": "artifact." + path, "kind": "numeric_score",
            "expected": expected, "full_tolerance": full, "zero_tolerance": zero,
            "weight": weight, "dimension": dimension}


OVERRIDE_RESISTANT_TASKS = {
    "v07-foundation-03-unit-and-provenance",
    "v07-workflow-02-architecture-advice",
    "v07-workflow-04-sizing-result",
    "v07-workflow-05-causal-ledger",
    "v07-closure-02-banked-scope",
    "v07-closure-05-artifact-consistency",
}


def knowledge_effect_expectation(spec: Dict[str, Any]) -> str:
    if spec["task_id"] in OVERRIDE_RESISTANT_TASKS:
        return "override_resistant"
    if spec.get("relevant_knowledge_ids"):
        return "benefit_expected"
    return "neutral_expected"


def scramble_controlled_vocab(spec: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Remove answer-order hints while retaining a deterministic controlled vocabulary."""
    forbidden_sequences = {
        tuple(check["expected"])
        for check in spec["checks"]
        if check["kind"] in {"sequence_alignment", "ranking_pairwise"}
    }

    def shuffled(values: List[Any], label: str) -> List[Any]:
        result = list(values)
        if len(result) < 2:
            return result
        seed = int(hashlib.sha256((spec["task_id"] + ":" + label).encode()).hexdigest()[:16], 16)
        random.Random(seed).shuffle(result)
        if result == values:
            result = result[1:] + result[:1]
        if tuple(result) in forbidden_sequences:
            result = result[1:] + result[:1]
        return result

    catalogs = deepcopy(spec["catalogs"])
    for name, values in catalogs.items():
        if isinstance(values, list):
            catalogs[name] = shuffled(values, "catalog:" + name)
    fields = deepcopy(spec["fields"])
    for name, field in fields.items():
        for key in ("allowed", "value_allowed", "allowed_keys", "required_keys"):
            if isinstance(field.get(key), list):
                field[key] = shuffled(field[key], "field:%s:%s" % (name, key))
    return catalogs, fields


def validate_catalog_difficulty(spec: Dict[str, Any]) -> None:
    """Reject fields whose public vocabulary is already the complete expected set."""
    for check in spec["checks"]:
        if check["kind"] != "set_f1":
            continue
        field_name = check["path"].split(".")[-1]
        allowed = spec["fields"].get(field_name, {}).get("allowed")
        if isinstance(allowed, list) and set(allowed) == set(check["expected"]):
            raise ValueError(
                "%s.%s leaks its complete expected set through allowed values"
                % (spec["task_id"], field_name)
            )


VERIFY_PY = r'''#!/usr/bin/env python3
import json, math, os
from pathlib import Path

app = Path(os.environ.get("EVOLDO_APP", "/app"))
here = Path(__file__).resolve().parent
reward_path = Path(os.environ.get("EVOLDO_REWARD", "/logs/verifier/reward.json"))
reward_path.parent.mkdir(parents=True, exist_ok=True)

def get(value, path):
    for part in path.split("."):
        value = value[part]
    return value

def lcs(left, right):
    previous = [0] * (len(right) + 1)
    for a in left:
        current = [0]
        for index, b in enumerate(right, 1):
            current.append(previous[index - 1] + 1 if a == b else max(previous[index], current[-1]))
        previous = current
    return previous[-1]

def evaluate(check, value):
    kind = check["kind"]
    expected = check.get("expected")
    if kind == "exact": return float(value == expected)
    if kind == "choice_credit": return float(check["credits"].get(value, 0.0))
    if kind == "set_f1":
        actual, target = set(value), set(expected)
        overlap = len(actual & target)
        return 2.0 * overlap / (len(actual) + len(target)) if actual or target else 1.0
    if kind == "sequence_alignment":
        if len(value) != len(set(value)): return 0.0
        overlap = lcs(value, expected)
        p = overlap / len(value) if value else 0.0
        r = overlap / len(expected) if expected else 0.0
        return 2.0 * p * r / (p + r) if p + r else 0.0
    if kind == "mapping_credit":
        keys = set(expected)
        return sum(key in value and key in expected and value[key] == expected[key] for key in keys) / len(keys)
    if kind == "multilabel_mapping_credit":
        keys = set(expected)
        if not keys: return 0.0
        credit = 0.0
        for key in keys:
            actual_values = value.get(key, []) if isinstance(value, dict) else []
            expected_values = expected.get(key, [])
            if not isinstance(actual_values, list): continue
            actual_set, expected_set = set(actual_values), set(expected_values)
            if not actual_set and not expected_set: credit += 1.0
            elif actual_set or expected_set:
                credit += 2.0 * len(actual_set & expected_set) / (len(actual_set) + len(expected_set))
        return credit / len(keys)
    if kind == "numeric_score":
        distance = abs(float(value) - float(expected))
        full, zero = float(check["full_tolerance"]), float(check["zero_tolerance"])
        return 1.0 if distance <= full else max(0.0, (zero - distance) / (zero - full))
    if kind == "numeric_range":
        value = float(value); lo = float(check["minimum"]); hi = float(check["maximum"])
        plo = float(check.get("partial_minimum", lo)); phi = float(check.get("partial_maximum", hi))
        if lo <= value <= hi: return 1.0
        if plo <= value < lo and lo > plo: return (value - plo) / (lo - plo)
        if hi < value <= phi and phi > hi: return (phi - value) / (phi - hi)
        return 0.0
    if kind == "nonempty": return float(isinstance(value, (str, list, dict)) and len(value) > 0)
    raise ValueError("unsupported check " + kind)

try:
    answer = json.loads((app / "answer.json").read_text())
    oracle = json.loads((here / "expected.json").read_text())
    raw = 0.0; critical = []; details = []
    for check in oracle["checks"]:
        try: credit = evaluate(check, get(answer, check["path"]))
        except Exception: credit = 0.0
        raw += float(check["weight"]) * credit
        if check.get("critical") and credit < float(check.get("critical_credit_threshold", 1.0)):
            critical.append(check["id"])
        details.append({"id": check["id"], "credit_fraction": credit})
    score = min(raw, float(oracle.get("critical_failure_cap", 49.0))) if critical else raw
    payload = {"reward": score / 100.0, "tests_total": len(details),
               "tests_passed": sum(row["credit_fraction"] == 1.0 for row in details),
               "details": details, "critical_failed": critical}
except Exception as exc:
    payload = {"reward": 0.0, "tests_total": 0, "tests_passed": 0, "details": [{"error": str(exc)}]}
reward_path.write_text(json.dumps(payload) + "\n")
'''


def task_toml(task_id: str, title: str, mode: str = "direct_reasoning",
              artifacts: Optional[List[str]] = None) -> str:
    artifacts = artifacts or ["/app/answer.json"]
    return f'''schema_version = "1.3"
artifacts = {json.dumps(artifacts)}

[task]
name = "evoldo/{task_id}"
description = {json.dumps(title)}
authors = [{{ name = "EvoLDO-Bench contributors" }}]

[metadata]
checker_allow_ideal = []
task_id = "{task_id}"
revision = 1
maturity = "L4"
maturity_note = "Public clean-room development task with deterministic structured grading."
maturity_updated_at = "2026-08-12T00:00:00+08:00"
benchmark_version = "{VERSION}"
execution_mode = "{mode}"

[verifier]
environment_mode = "separate"

[environment]
network_mode = "no-network"
build_timeout_sec = 1800.0
cpus = 8
memory_mb = 4096
storage_mb = 10240
'''


def make_reasoning_task(spec: Dict[str, Any]) -> Dict[str, Any]:
    validate_catalog_difficulty(spec)
    task_id = spec["task_id"]
    root = TASKS / task_id
    starter = root / "environment" / "starter"
    tests = root / "tests"
    solution = root / "solution"
    write(root / "task.toml", task_toml(task_id, spec["title"]))
    write(root / "instruction.md", f'''# {spec["title"]}

Act as the design-review engineer for this isolated LDO case. Read `case.json` and produce
`/app/answer.json` following `answer_template.json`. The deliverable is a structured engineering
artifact, not a multiple-choice explanation: classify every requested record, compute requested
values, and order only the actions that the supplied evidence authorizes.

Rules:

- Use only supplied case material and, in a declared KG-on treatment, the frozen local retrieval.
- Web search, browsing, remote retrieval, and undeclared tools are forbidden in every treatment.
- Return exactly one JSON object; preserve task ID `{task_id}` and all controlled identifiers.
- Keep `claim_boundary` concise and restrict it to evidence actually supplied.
''')
    catalogs, fields = scramble_controlled_vocab(spec)
    contract = {
        "schema_version": "3.0", "task_id": task_id,
        "family_id": spec.get("family_id", task_id), "lineage_id": spec.get("lineage_id", task_id),
        "split": "dev", "variant": spec.get("variant", "canonical"), "suite": spec["suite"],
        "level": spec["level"], "capabilities": spec["capabilities"], "title": spec["title"],
        "language": "en", "prompt_file": "instruction.md",
        "input_files": ["case.json", "answer_template.json"],
        "answer_template_file": "answer_template.json",
        "eligible_modes": ["direct_reasoning", "knowledge_assisted"],
        "budget": {"timeout_seconds": spec.get("timeout_seconds", 420), "max_tool_calls": 0},
        "network_policy": {"model_web_search": "forbidden", "external_network": "provider_control_plane_only"},
        "tool_policy": {"allowed_tools": [], "forbidden_tools": ["web_search", "browser", "remote_fetch"]},
        "benchmark_version": VERSION, "evaluation_role": spec.get("evaluation_role", "core"),
        "deployment_tier": spec["deployment_tier"],
        "knowledge_effect_expectation": knowledge_effect_expectation(spec),
        "scoring_dimensions": sorted({check["dimension"] for check in spec["checks"]}),
    }
    case = {
        "schema_version": "3.0", "task_id": task_id, "scenario": spec["scenario"],
        "materials": spec["materials"], "catalogs": catalogs,
        "answer_contract": {"additional_fields": False, "fields": fields},
        "provenance": {"origin": "clean-room synthetic fixture", "private_pdk_content": False},
    }
    template_artifact = {}
    for name, field in fields.items():
        template_artifact[name] = {
            "string": "CONTROLLED_VALUE", "boolean": False, "number": 0.0,
            "string_list": [], "number_map": {}, "string_map": {}, "string_list_map": {}, "object": {},
        }[field["type"]]
    answer_template = {"schema_version": "3.0", "task_id": task_id, "artifact": template_artifact,
                       "claim_boundary": "State only what the supplied evidence establishes.", "confidence": 0.0}
    answer = {"schema_version": "3.0", "task_id": task_id, "artifact": spec["answer"],
              "claim_boundary": spec.get("claim_boundary", "Limited to supplied evidence and named conditions."),
              "confidence": 0.95}
    oracle = {"schema_version": "1.0", "task_id": task_id, "family_id": contract["family_id"],
              "checks": spec["checks"], "critical_failure_cap": 49, "pass_threshold": 70,
              "relevant_knowledge_ids": spec.get("relevant_knowledge_ids", [])}
    dump(starter / "task_contract.json", contract)
    dump(starter / "case.json", case)
    dump(starter / "answer_template.json", answer_template)
    write(root / "environment" / "Dockerfile",
          f"FROM {BASE_IMAGE}\nWORKDIR /app\nCOPY starter/ /app/\n"
          "RUN git init -q && git add . && git -c user.email=benchmark@example.invalid "
          "-c user.name=benchmark commit -qm starter\nCMD [\"bash\"]\n")
    dump(tests / "expected.json", oracle)
    write(tests / "verify.py", VERIFY_PY)
    write(tests / "test.sh", "#!/usr/bin/env sh\nset -eu\npython3 /app/analog_arena_tests/verify.py\n")
    write(tests / "Dockerfile", f"FROM {BASE_IMAGE}\nWORKDIR /app/analog_arena_tests\nCOPY . .\n")
    dump(solution / "answer.json", answer)
    write(solution / "solve.sh", "#!/usr/bin/env sh\nset -eu\ncp /solution/answer.json /app/answer.json\n")
    dump(ORACLES / (task_id + ".oracle.json"), oracle)
    return contract


def package_hash(root: Path) -> str:
    lines = []
    for path in sorted(root.rglob("*")):
        if path.is_file():
            lines.append(path.relative_to(root).as_posix() + ":" + hashlib.sha256(path.read_bytes()).hexdigest())
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()


BASE_FIELDS = {
    "decision": field_string(["proceed", "repair_first", "retry_infrastructure", "insufficient_evidence", "reject"]),
    "failure_class": field_string(["none", "circuit", "measurement", "pipeline", "infrastructure", "evidence_integrity"]),
    "evidence_used": field_list([], minimum=1),
    "action_sequence": field_list([], minimum=1),
    "prohibited_actions": field_list([], minimum=1),
}


def core_specs() -> List[Dict[str, Any]]:
    return [
        {
            "task_id": "v07-foundation-01-feedback-trace", "title": "Trace feedback sign and legal loop evidence",
            "suite": "structure", "level": "L1", "deployment_tier": "T0_foundation",
            "capabilities": ["structure", "feedback_stability", "evidence_integrity"],
            "scenario": "A PMOS-pass LDO review contains sign measurements plus distractor prose. Reconstruct the physical loop and decide what has actually been established.",
            "materials": {
                "observations": [
                    {"id": "e1", "fact": "A +8 mV forced VOUT perturbation makes VFB increase by 4 mV."},
                    {"id": "e2", "fact": "The error-amplifier output rises by 22 mV after VFB rises."},
                    {"id": "e3", "fact": "Raising a PMOS pass gate voltage reduces delivered current."},
                    {"id": "e4", "fact": "A nominal transient settles monotonically once."},
                    {"id": "e5", "fact": "An old report says phase margin was 67 degrees on another netlist."},
                ]
            },
            "catalogs": {
                "loop_conclusion": ["negative_feedback_small_signal", "positive_feedback", "sign_unknown"],
                "evidence_ids": ["e1", "e2", "e3", "e4", "e5"],
                "claim_scope": ["polarity_only", "polarity_and_stability", "full_qualification"],
                "probes": ["bias_preserving_return_ratio", "reuse_old_phase_margin", "startup_only", "none"],
            },
            "fields": {
                "loop_conclusion": field_string(["negative_feedback_small_signal", "positive_feedback", "sign_unknown"]),
                "evidence_used": field_list(["e1", "e2", "e3", "e4", "e5"], 1),
                "claim_scope": field_string(["polarity_only", "polarity_and_stability", "full_qualification"]),
                "next_probe": field_string(["bias_preserving_return_ratio", "reuse_old_phase_margin", "startup_only", "none"]),
            },
            "answer": {"loop_conclusion": "negative_feedback_small_signal", "evidence_used": ["e1", "e2", "e3"],
                       "claim_scope": "polarity_only", "next_probe": "bias_preserving_return_ratio"},
            "checks": [
                exact("loop", "loop_conclusion", "negative_feedback_small_signal", 35, "physical_conclusion", True),
                set_f1("evidence", "evidence_used", ["e1", "e2", "e3"], 30, "evidence_selection"),
                exact("scope", "claim_scope", "polarity_only", 20, "claim_boundary"),
                exact("probe", "next_probe", "bias_preserving_return_ratio", 15, "validation_plan"),
            ],
            "relevant_knowledge_ids": ["kg-feedback-return-ratio"],
        },
        {
            "task_id": "v07-foundation-02-headroom-budget", "title": "Compute headroom and classify the first blocker",
            "suite": "sizing", "level": "L1", "deployment_tier": "T0_foundation",
            "capabilities": ["operating_point", "sizing", "numeric_reasoning"],
            "scenario": "A two-stack error-amplifier branch is reviewed at the lowest supply. Compute its remaining voltage and choose the earliest admissible action.",
            "materials": {
                "vin_min_v": 1.05, "vout_target_v": 0.90, "required_stack_headroom_v": 0.31,
                "measured_ea_low_limit_v": 0.055, "pass_gate_required_v": 0.030,
                "op": {"input_pair": "saturation", "cascode": "triode", "pass": "conducting"},
            },
            "catalogs": {
                "blockers": ["cascode_headroom", "pass_drive", "feedback_ratio", "none"],
                "actions": ["recover_cascode_headroom", "increase_pass_width", "change_feedback_ratio", "run_full_pvt"],
                "prohibited": ["full_pvt_before_op", "blind_multi_knob_sweep", "ideal_cascode_force", "reuse_old_op"],
            },
            "fields": {
                "available_headroom_mv": {"type": "number"},
                "stack_deficit_mv": {"type": "number"},
                "primary_blocker": field_string(["cascode_headroom", "pass_drive", "feedback_ratio", "none"]),
                "next_action": field_string(["recover_cascode_headroom", "increase_pass_width", "change_feedback_ratio", "run_full_pvt"]),
                "prohibited_actions": field_list(["full_pvt_before_op", "blind_multi_knob_sweep", "ideal_cascode_force", "reuse_old_op"], 1),
            },
            "answer": {"available_headroom_mv": 150.0, "stack_deficit_mv": 160.0,
                       "primary_blocker": "cascode_headroom", "next_action": "recover_cascode_headroom",
                       "prohibited_actions": ["full_pvt_before_op", "blind_multi_knob_sweep", "ideal_cascode_force"]},
            "checks": [
                numeric("available", "available_headroom_mv", 150, 1, 80, 20, "numeric_reasoning"),
                numeric("deficit", "stack_deficit_mv", 160, 1, 80, 20, "numeric_reasoning"),
                exact("blocker", "primary_blocker", "cascode_headroom", 25, "diagnosis", True),
                exact("action", "next_action", "recover_cascode_headroom", 20, "action_selection"),
                set_f1("prohibited", "prohibited_actions", ["full_pvt_before_op", "blind_multi_knob_sweep", "ideal_cascode_force"], 15, "safety"),
            ],
            "relevant_knowledge_ids": ["kg-op-first"],
        },
        {
            "task_id": "v07-foundation-03-unit-and-provenance", "title": "Normalize metrics without crossing provenance boundaries",
            "suite": "diagnosis", "level": "L2", "deployment_tier": "T1_local_advice",
            "capabilities": ["evidence_integrity", "numeric_reasoning", "diagnosis"],
            "scenario": "A review table mixes units and candidate hashes. Normalize only admissible records and classify each record.",
            "materials": {
                "current_candidate_hash": "cand-91",
                "records": [
                    {"id": "r1", "candidate_hash": "cand-91", "metric": "iq", "value": 0.000084, "unit": "A", "status": "measured"},
                    {"id": "r2", "candidate_hash": "cand-91", "metric": "dropout", "value": 73, "unit": "mV", "status": "measured"},
                    {"id": "r3", "candidate_hash": "cand-77", "metric": "phase_margin", "value": 64, "unit": "deg", "status": "measured"},
                    {"id": "r4", "candidate_hash": "cand-91", "metric": "noise", "value": "failed", "unit": "uVrms", "status": "sentinel"},
                    {"id": "r5", "candidate_hash": None, "metric": "startup", "value": True, "unit": "boolean", "status": "narrative"},
                ]
            },
            "catalogs": {
                "record_classes": ["admissible_current", "stale_unbound", "quarantine_sentinel", "narrative_not_measurement"],
                "evidence_ids": ["r1", "r2", "r3", "r4", "r5"],
                "decisions": ["advice_ready", "insufficient_current_evidence", "full_qualification"],
            },
            "fields": {
                "record_classes": field_map(["r1", "r2", "r3", "r4", "r5"],
                                            ["admissible_current", "stale_unbound", "quarantine_sentinel", "narrative_not_measurement"]),
                "iq_ua": {"type": "number"}, "dropout_mv": {"type": "number"},
                "evidence_used": field_list(["r1", "r2", "r3", "r4", "r5"], 1),
                "decision": field_string(["advice_ready", "insufficient_current_evidence", "full_qualification"]),
            },
            "answer": {"record_classes": {"r1": "admissible_current", "r2": "admissible_current",
                                            "r3": "stale_unbound", "r4": "quarantine_sentinel",
                                            "r5": "narrative_not_measurement"},
                       "iq_ua": 84.0, "dropout_mv": 73.0, "evidence_used": ["r1", "r2"],
                       "decision": "insufficient_current_evidence"},
            "checks": [
                mapping("classes", "record_classes", {"r1": "admissible_current", "r2": "admissible_current",
                                                        "r3": "stale_unbound", "r4": "quarantine_sentinel",
                                                        "r5": "narrative_not_measurement"}, 35, "evidence_classification"),
                numeric("iq", "iq_ua", 84, 0.1, 30, 15, "unit_conversion"),
                numeric("dropout", "dropout_mv", 73, 0.1, 30, 15, "unit_conversion"),
                set_f1("used", "evidence_used", ["r1", "r2"], 20, "evidence_selection"),
                exact("decision", "decision", "insufficient_current_evidence", 15, "claim_boundary", True),
            ],
            "relevant_knowledge_ids": ["kg-evidence-admission"],
        },
        {
            "task_id": "v07-workflow-01-op-recovery-order", "title": "Recover an LDO operating point in gate order",
            "suite": "diagnosis", "level": "L3", "deployment_tier": "T2_bounded_workflow",
            "capabilities": ["operating_point", "startup_enable", "feedback_stability", "workflow_planning"],
            "scenario": "The initial netlist converges, but internal bias is dead. Build the admissible recovery plan without using qualification-only crutches.",
            "materials": {
                "connectivity": {"terminal_order_verified": False, "body_connections_verified": True,
                                 "cdf_parameters_netlisted": False, "feedback_closed": True},
                "dc_op": {"vout_v": 0.02, "target_v": 0.80, "bias_branch_a": 0.0,
                          "cascode_region": "cutoff", "pass_region": "cutoff"},
                "startup": {"zero_state_success": False, "nodeset_success": True},
                "stb": {"single_0db_crossing": False, "phase_margin_deg": None},
            },
            "catalogs": {
                "stages": ["connectivity_cdf", "dc_op_bias", "cascode_headroom", "pass_regulation",
                           "zero_state_startup", "stb_crossing", "quick_qualification", "full_qualification"],
                "root_causes": ["terminal_order_and_cdf", "startup_only", "stability_only", "pass_width_only"],
                "prohibited": ["accept_nodeset_as_final", "run_full_before_stb", "sweep_pass_width_before_connectivity",
                               "force_internal_bias", "skip_body_check"],
            },
            "fields": {
                "primary_root_cause": field_string(["terminal_order_and_cdf", "startup_only", "stability_only", "pass_width_only"]),
                "action_sequence": field_list(["connectivity_cdf", "dc_op_bias", "cascode_headroom", "pass_regulation",
                                                "zero_state_startup", "stb_crossing", "quick_qualification", "full_qualification"], 1),
                "stop_after_stage": field_string(["connectivity_cdf", "dc_op_bias", "cascode_headroom", "pass_regulation",
                                                   "zero_state_startup", "stb_crossing", "quick_qualification", "full_qualification"]),
                "prohibited_actions": field_list(["accept_nodeset_as_final", "run_full_before_stb",
                                                   "sweep_pass_width_before_connectivity", "force_internal_bias",
                                                   "skip_body_check"], 1),
            },
            "answer": {"primary_root_cause": "terminal_order_and_cdf",
                       "action_sequence": ["connectivity_cdf", "dc_op_bias", "cascode_headroom", "pass_regulation",
                                           "zero_state_startup", "stb_crossing", "quick_qualification", "full_qualification"],
                       "stop_after_stage": "connectivity_cdf",
                       "prohibited_actions": ["accept_nodeset_as_final", "run_full_before_stb",
                                              "sweep_pass_width_before_connectivity", "force_internal_bias"]},
            "checks": [
                exact("cause", "primary_root_cause", "terminal_order_and_cdf", 25, "diagnosis", True),
                sequence("sequence", "action_sequence", ["connectivity_cdf", "dc_op_bias", "cascode_headroom", "pass_regulation",
                                                           "zero_state_startup", "stb_crossing", "quick_qualification", "full_qualification"],
                         35, "workflow_order"),
                exact("stop", "stop_after_stage", "connectivity_cdf", 20, "stop_rule"),
                set_f1("prohibited", "prohibited_actions", ["accept_nodeset_as_final", "run_full_before_stb",
                                                              "sweep_pass_width_before_connectivity", "force_internal_bias"],
                       20, "safety"),
            ],
            "relevant_knowledge_ids": ["kg-op-first", "kg-startup-evidence", "kg-stb-crossing"],
        },
        {
            "task_id": "v07-workflow-02-architecture-advice", "title": "Issue evidence-bound architecture advice",
            "suite": "architecture_choice", "level": "L3", "deployment_tier": "T2_bounded_workflow",
            "capabilities": ["architecture_choice", "evidence_integrity", "operating_point", "controlled_experiment"],
            "scenario": "A designer asks how to improve low gain. Apply the declared admission and ranking policy to current measurements, unbound history, and analytical priors; do not smuggle an unstated architecture preference into the answer.",
            "materials": {
                "current_netlist_sha256": "sha-new",
                "evidence": [
                    {"id": "e1", "hash": "sha-new", "kind": "op", "facts": {"input_pair": "saturation", "cascode_headroom_mv": 22,
                                                                                  "cascode_headroom_min_mv": 15}},
                    {"id": "e2", "hash": "sha-new", "kind": "ac", "facts": {"gain_db": 41, "target_db": 55, "phase_margin_deg": 58}},
                    {"id": "e3", "hash": "sha-old", "kind": "sweep", "facts": {"longer_l_gain_db": 59}},
                    {"id": "e4", "hash": None, "kind": "literature_prior", "facts": {"claim": "gain boost may raise gain"}},
                ],
                "current_knobs": {"cascode_bias_v": 0.51, "input_l_um": 0.50, "recycle_ratio": None},
                "constraints": {"min_phase_margin_deg": 50, "max_iq_ua": 120},
                "admission_policy": {
                    "advice_ready_requires": ["current_hash_bound_problem_measurement", "healthy_critical_operating_point"],
                    "measured_current_definition": "A hash-bound current-candidate measurement or operating-point fact.",
                    "unbound_old_definition": "A measurement bound to another candidate hash.",
                    "analytical_prior_definition": "A literature or device-physics prior without a current-candidate measurement.",
                    "healthy_critical_operating_point": "Every supplied device-region fact passes and cascode_headroom_mv is at least cascode_headroom_min_mv.",
                    "action_ranking": [
                        "first: the smallest reversible one-knob experiment directly tied to a measured weak margin",
                        "then: other bounded current knobs, preserving their listed order",
                        "then: global geometry changes",
                        "last: topology changes",
                        "exclude actions that are verification stages rather than design experiments",
                        "do not rank an action whose current knob value is missing"
                    ],
                    "required_checks": "Any retained design experiment must preserve OP headroom, gain, phase margin, IQ, startup, and worst-corner qualification."
                },
            },
            "catalogs": {
                "states": ["advice_ready_measured", "hypothesis_only", "operating_point_first", "problem_not_reproduced"],
                "actions": ["small_bidirectional_cascode_bias_test", "increase_all_lengths", "add_gain_boost_stage",
                            "increase_recycle_ratio", "run_full_pvt"],
                "evidence_ids": ["e1", "e2", "e3", "e4"],
                "labels": ["measured_current", "unbound_old", "analytical_prior", "not_evidence"],
                "required_checks": ["op_headroom", "gain", "phase_margin", "iq", "startup", "worst_corner", "screenshot_only"],
            },
            "fields": {
                "state": field_string(["advice_ready_measured", "hypothesis_only", "operating_point_first", "problem_not_reproduced"]),
                "evidence_labels": field_map(["e1", "e2", "e3", "e4"],
                                             ["measured_current", "unbound_old", "analytical_prior", "not_evidence"]),
                "ranked_actions": field_list(["small_bidirectional_cascode_bias_test", "increase_all_lengths", "add_gain_boost_stage",
                                              "increase_recycle_ratio", "run_full_pvt"], 1),
                "next_action": field_string(["small_bidirectional_cascode_bias_test", "increase_all_lengths", "add_gain_boost_stage",
                                               "increase_recycle_ratio", "run_full_pvt"]),
                "required_checks": field_list(["op_headroom", "gain", "phase_margin", "iq", "startup", "worst_corner", "screenshot_only"], 1),
            },
            "answer": {"state": "advice_ready_measured",
                       "evidence_labels": {"e1": "measured_current", "e2": "measured_current",
                                           "e3": "unbound_old", "e4": "analytical_prior"},
                       "ranked_actions": ["small_bidirectional_cascode_bias_test", "increase_all_lengths",
                                          "add_gain_boost_stage"],
                       "next_action": "small_bidirectional_cascode_bias_test",
                       "required_checks": ["op_headroom", "gain", "phase_margin", "iq", "startup", "worst_corner"]},
            "checks": [
                exact("state", "state", "advice_ready_measured", 20, "admission_state", True),
                mapping("labels", "evidence_labels", {"e1": "measured_current", "e2": "measured_current",
                                                       "e3": "unbound_old", "e4": "analytical_prior"}, 25, "evidence_hierarchy"),
                sequence("rank", "ranked_actions", ["small_bidirectional_cascode_bias_test", "increase_all_lengths",
                                                      "add_gain_boost_stage"], 20, "action_ranking"),
                exact("next", "next_action", "small_bidirectional_cascode_bias_test", 20, "bounded_action"),
                set_f1("checks", "required_checks", ["op_headroom", "gain", "phase_margin", "iq", "startup", "worst_corner"], 15, "regression_plan"),
            ],
            "relevant_knowledge_ids": ["kg-evidence-admission", "kg-architecture-advice-order"],
        },
        {
            "task_id": "v07-workflow-03-search-space", "title": "Construct a role-aware sizing campaign",
            "suite": "sizing", "level": "L3", "deployment_tier": "T2_bounded_workflow",
            "capabilities": ["sizing", "search_space", "evidence_integrity", "workflow_planning"],
            "scenario": "Prepare a bounded sizing campaign from a healthy baseline and an inventory-resolved parameter space. Follow the supplied reduction policy exactly; avoid invented couplings and unsupported CDF assumptions.",
            "materials": {
                "baseline": {"hash_bound": True, "sim_ok": True, "startup_success": True,
                             "dropout_mv": 112, "dropout_limit_mv": 90, "phase_margin_deg": 47,
                             "phase_margin_limit_deg": 50, "iq_ua": 91, "iq_limit_ua": 120},
                "resolved_parameters": [
                    {"id": "p1", "path": "top/mpass/w", "role": "pass", "domain": [700, 1400], "kind": "continuous"},
                    {"id": "p2", "path": "top/driver/w", "role": "driver", "domain": [8, 24], "kind": "continuous"},
                    {"id": "p3", "path": "top/ccomp/c", "role": "compensation", "domain": [2, 12], "kind": "continuous"},
                    {"id": "p4", "path": "top/input/nf", "role": "input_pair", "domain": [2, 4, 6, 8], "kind": "integer"},
                    {"id": "p5", "path": "top/startup/w", "role": "startup", "domain": [1, 5], "kind": "continuous"},
                    {"id": "p6", "path": "top/mystery/nf", "role": None, "domain": [1, 2, 3], "kind": "integer"},
                ],
                "role_alias_coverage": 0.83,
                "reduction_policy": {
                    "state_rules_in_priority_order": [
                        "baseline unhealthy -> sizing_blocked_baseline",
                        "unresolved parameter role or role_alias_coverage below 0.80 -> needs_role_aliases",
                        "otherwise -> sizing_config_ready"
                    ],
                    "metric_priority": "Order currently failed hard metrics by normalized violation (value-limit)/limit descending; append passing IQ only as a guard; do not include passing startup in the objective list.",
                    "selected_roles": ["pass", "driver", "compensation", "input_pair"],
                    "held_roles": ["startup", "unresolved"],
                    "launch_rule": "A complete inventory with sufficient role coverage launches a callback-aware run; unresolved paths remain held fixed."
                },
            },
            "catalogs": {
                "states": ["sizing_config_ready", "sizing_blocked_baseline", "needs_role_aliases", "prepare_parameter_space"],
                "parameter_ids": ["p1", "p2", "p3", "p4", "p5", "p6"],
                "priorities": ["dropout", "phase_margin", "iq", "startup"],
                "actions": ["formal_callback_aware_run", "optimization_only_final", "invent_p6_alias", "expand_all_domains"],
                "prohibited": ["invent_matching_coupling", "rewrite_integer_domain", "include_unmapped_p6", "treat_search_as_final",
                               "hold_unresolved_fixed"],
            },
            "fields": {
                "state": field_string(["sizing_config_ready", "sizing_blocked_baseline", "needs_role_aliases", "prepare_parameter_space"]),
                "metric_priority": field_list(["dropout", "phase_margin", "iq", "startup"], 1),
                "selected_parameters": field_list(["p1", "p2", "p3", "p4", "p5", "p6"], 1),
                "held_parameters": field_list(["p1", "p2", "p3", "p4", "p5", "p6"], 1),
                "next_action": field_string(["formal_callback_aware_run", "optimization_only_final", "invent_p6_alias", "expand_all_domains"]),
                "prohibited_actions": field_list(["invent_matching_coupling", "rewrite_integer_domain", "include_unmapped_p6",
                                                   "treat_search_as_final", "hold_unresolved_fixed"], 1),
            },
            "answer": {"state": "sizing_config_ready", "metric_priority": ["dropout", "phase_margin", "iq"],
                       "selected_parameters": ["p1", "p2", "p3", "p4"], "held_parameters": ["p5", "p6"],
                       "next_action": "formal_callback_aware_run",
                       "prohibited_actions": ["invent_matching_coupling", "rewrite_integer_domain", "include_unmapped_p6", "treat_search_as_final"]},
            "checks": [
                exact("state", "state", "sizing_config_ready", 15, "campaign_state", True),
                sequence("priority", "metric_priority", ["dropout", "phase_margin", "iq"], 20, "constraint_priority"),
                set_f1("selected", "selected_parameters", ["p1", "p2", "p3", "p4"], 25, "role_aware_space"),
                set_f1("held", "held_parameters", ["p5", "p6"], 10, "held_fixed"),
                exact("next", "next_action", "formal_callback_aware_run", 15, "workflow_stage"),
                set_f1("prohibited", "prohibited_actions", ["invent_matching_coupling", "rewrite_integer_domain",
                                                              "include_unmapped_p6", "treat_search_as_final"], 15, "safety"),
            ],
            "relevant_knowledge_ids": ["kg-sizing-two-pass", "kg-search-is-not-final"],
        },
        {
            "task_id": "v07-workflow-04-sizing-result", "title": "Interpret an autosizer result without overclaiming",
            "suite": "sizing", "level": "L4", "deployment_tier": "T3_multi_constraint_closure",
            "capabilities": ["sizing", "candidate_selection", "evidence_integrity", "controlled_experiment"],
            "scenario": "A sizing run produced several artifacts and candidate metrics. Apply the supplied result contract and hard limits to determine the terminal decision, best admissible candidate, failure lane, and next action.",
            "materials": {
                "autosize_report": {"terminal_status": "completed_verified", "best_candidate": "c3", "best_score": 87.4, "best_hard_pass": True},
                "result_manifest": {"terminal_status": "optimization_only", "best_candidate": "c3", "best_score": 87.4, "best_hard_pass": True,
                                    "backannotation": False, "fresh_final": False},
                "candidates": [
                    {"id": "c1", "dropout_mv": 89, "pm_deg": 49, "iq_ua": 102, "score": 81.0},
                    {"id": "c2", "dropout_mv": 93, "pm_deg": 56, "iq_ua": 109, "score": 83.1},
                    {"id": "c3", "dropout_mv": 86, "pm_deg": 53, "iq_ua": 117, "score": 87.4},
                    {"id": "c4", "dropout_mv": 82, "pm_deg": 54, "iq_ua": 128, "score": 91.2},
                ],
                "hard_limits": {"dropout_max_mv": 90, "pm_min_deg": 50, "iq_max_ua": 120},
                "baseline_score": 79.0,
                "result_contract": {
                    "hard_gate_precedence": "A candidate is admissible only if every hard limit passes; raw score cannot compensate.",
                    "candidate_selection": "Among admissible candidates select the highest score.",
                    "terminal_precedence": [
                        "report/manifest identity or metric disagreement -> evidence_integrity",
                        "optimization-only, missing callback backannotation, or missing fresh final -> pipeline",
                        "verified hard-gate failure -> circuit",
                        "provider or simulator launch failure -> infrastructure",
                        "otherwise -> none"
                    ],
                    "status_authority": "The immutable result_manifest controls acceptance status; autosize_report terminal_status is progress metadata and cannot upgrade it.",
                    "final_acceptance": "Final verification requires matching report/manifest status, callback-aware backannotation, and a fresh final run. With result_manifest=optimization_only, the decision is search_only_not_final and the failure lane is pipeline."
                },
            },
            "catalogs": {
                "decisions": ["final_verified_improved", "search_only_not_final", "search_no_feasible_candidate",
                              "insufficient_evidence", "final_verified_no_gain"],
                "candidate_ids": ["c1", "c2", "c3", "c4", "none"],
                "failure_classes": ["none", "circuit", "pipeline", "infrastructure", "evidence_integrity"],
                "actions": ["formal_backannotation_and_fresh_final", "register_c3", "expand_all_bounds", "change_topology"],
            },
            "fields": {
                "decision": field_string(["final_verified_improved", "search_only_not_final", "search_no_feasible_candidate",
                                           "insufficient_evidence", "final_verified_no_gain"]),
                "best_admissible_candidate": field_string(["c1", "c2", "c3", "c4", "none"]),
                "candidate_gate_map": field_map(["c1", "c2", "c3", "c4"], ["hard_pass", "pm_fail", "dropout_fail", "iq_fail", "multiple_fail"]),
                "failure_class": field_string(["none", "circuit", "pipeline", "infrastructure", "evidence_integrity"]),
                "next_action": field_string(["formal_backannotation_and_fresh_final", "register_c3", "expand_all_bounds", "change_topology"]),
            },
            "answer": {"decision": "search_only_not_final", "best_admissible_candidate": "c3",
                       "candidate_gate_map": {"c1": "pm_fail", "c2": "dropout_fail", "c3": "hard_pass", "c4": "iq_fail"},
                       "failure_class": "pipeline", "next_action": "formal_backannotation_and_fresh_final"},
            "checks": [
                exact("decision", "decision", "search_only_not_final", 25, "terminal_decision", True),
                exact("candidate", "best_admissible_candidate", "c3", 15, "candidate_selection"),
                mapping("gates", "candidate_gate_map", {"c1": "pm_fail", "c2": "dropout_fail", "c3": "hard_pass", "c4": "iq_fail"}, 30, "constraint_accounting"),
                exact("class", "failure_class", "pipeline", 15, "failure_classification"),
                exact("next", "next_action", "formal_backannotation_and_fresh_final", 15, "next_action"),
            ],
            "relevant_knowledge_ids": ["kg-search-is-not-final", "kg-final-artifact-consistency"],
        },
        {
            "task_id": "v07-workflow-05-causal-ledger", "title": "Admit controlled experiments into a design ledger",
            "suite": "diagnosis", "level": "L3", "deployment_tier": "T2_bounded_workflow",
            "capabilities": ["controlled_experiment", "evidence_integrity", "knowledge_admission"],
            "scenario": "Classify experiment cards before using them as sizing knowledge. A correlation or a prose lesson is not automatically a local sensitivity.",
            "materials": {
                "cards": [
                    {"id": "x1", "changed_knobs": ["ccomp"], "same_bench": True, "same_corner": True,
                     "distinct_candidate_hashes": True, "numeric_metrics": True, "evidence_hashes_valid": True},
                    {"id": "x2", "changed_knobs": ["ccomp", "driver_w"], "same_bench": True, "same_corner": True,
                     "distinct_candidate_hashes": True, "numeric_metrics": True, "evidence_hashes_valid": True},
                    {"id": "x3", "changed_knobs": ["pass_w"], "same_bench": False, "same_corner": False,
                     "distinct_candidate_hashes": True, "numeric_metrics": True, "evidence_hashes_valid": True},
                    {"id": "x4", "changed_knobs": ["bias_i"], "same_bench": True, "same_corner": True,
                     "distinct_candidate_hashes": False, "numeric_metrics": True, "evidence_hashes_valid": True},
                    {"id": "x5", "changed_knobs": ["input_l"], "same_bench": True, "same_corner": True,
                     "distinct_candidate_hashes": True, "numeric_metrics": False, "evidence_hashes_valid": True},
                ],
                "narrative": "Across 40 unrelated candidates, larger pass width correlates with lower dropout.",
            },
            "catalogs": {
                "classes": ["validated_single_variable", "multi_knob_confounded", "bench_corner_confounded",
                            "identity_not_distinct", "nonnumeric_or_missing", "analytical_prior"],
                "card_ids": ["x1", "x2", "x3", "x4", "x5"],
                "knowledge_levels": ["validated_local_sensitivity", "hypothesis", "candidate_correlation", "measured_fact"],
                "actions": ["admit_x1_only", "admit_all_numeric", "rewrite_cards_as_pass", "discard_all"],
            },
            "fields": {
                "card_classes": field_map(["x1", "x2", "x3", "x4", "x5"],
                                          ["validated_single_variable", "multi_knob_confounded", "bench_corner_confounded",
                                           "identity_not_distinct", "nonnumeric_or_missing", "analytical_prior"]),
                "admissible_cards": field_list(["x1", "x2", "x3", "x4", "x5"], 1),
                "narrative_level": field_string(["validated_local_sensitivity", "hypothesis", "candidate_correlation", "measured_fact"]),
                "next_action": field_string(["admit_x1_only", "admit_all_numeric", "rewrite_cards_as_pass", "discard_all"]),
            },
            "answer": {"card_classes": {"x1": "validated_single_variable", "x2": "multi_knob_confounded",
                                         "x3": "bench_corner_confounded", "x4": "identity_not_distinct",
                                         "x5": "nonnumeric_or_missing"},
                       "admissible_cards": ["x1"], "narrative_level": "candidate_correlation", "next_action": "admit_x1_only"},
            "checks": [
                mapping("classes", "card_classes", {"x1": "validated_single_variable", "x2": "multi_knob_confounded",
                                                      "x3": "bench_corner_confounded", "x4": "identity_not_distinct",
                                                      "x5": "nonnumeric_or_missing"}, 45, "card_validation"),
                set_f1("admissible", "admissible_cards", ["x1"], 20, "knowledge_admission", True),
                exact("narrative", "narrative_level", "candidate_correlation", 20, "causal_boundary"),
                exact("next", "next_action", "admit_x1_only", 15, "next_action"),
            ],
            "relevant_knowledge_ids": ["kg-controlled-experiment"],
        },
        {
            "task_id": "v07-closure-01-stb-stop-rule", "title": "Stop a corner campaign when STB evidence is undefined",
            "suite": "design_closure", "level": "L4", "deployment_tier": "T3_multi_constraint_closure",
            "capabilities": ["feedback_stability", "design_closure", "stop_rule", "failure_classification"],
            "scenario": "A nominal candidate looks good, but some load/corner STB rows lack a unique 0 dB crossing. Decide whether the expensive full matrix is authorized.",
            "materials": {
                "stb_rows": [
                    {"id": "s1", "corner": "tt_1v8_27c_light", "crossings": 1, "pm_deg": 56, "gm_db": 12},
                    {"id": "s2", "corner": "ss_1v62_125c_heavy", "crossings": 1, "pm_deg": 51, "gm_db": 9},
                    {"id": "s3", "corner": "ff_1v98_m40c_light", "crossings": 0, "pm_deg": 74, "gm_db": None},
                    {"id": "s4", "corner": "ff_1v98_27c_heavy", "crossings": 2, "pm_deg": 38, "gm_db": -2},
                ],
                "quick_metrics": {"dropout_pass": True, "iq_pass": True, "startup_pass": True},
                "full_matrix_cost_runs": 72,
            },
            "catalogs": {
                "row_classes": ["valid_pass", "valid_fail", "undefined_no_crossing", "ambiguous_multiple_crossings"],
                "decisions": ["run_full_matrix", "repair_stb_then_repeat_quick", "accept_finite_pm", "infrastructure_retry"],
                "actions": ["inspect_loop_break_and_pole_order", "increase_pass_width", "accept_s3_pm", "run_noise"],
                "prohibited": ["treat_no_crossing_pm_as_pass", "average_phase_margin", "run_full_matrix_before_stb_repair",
                               "discard_valid_crossing_rows"],
            },
            "fields": {
                "row_classes": field_map(["s1", "s2", "s3", "s4"],
                                         ["valid_pass", "valid_fail", "undefined_no_crossing", "ambiguous_multiple_crossings"]),
                "decision": field_string(["run_full_matrix", "repair_stb_then_repeat_quick", "accept_finite_pm", "infrastructure_retry"]),
                "next_action": field_string(["inspect_loop_break_and_pole_order", "increase_pass_width", "accept_s3_pm", "run_noise"]),
                "prohibited_actions": field_list(["treat_no_crossing_pm_as_pass", "average_phase_margin",
                                                   "run_full_matrix_before_stb_repair", "discard_valid_crossing_rows"], 1),
            },
            "answer": {"row_classes": {"s1": "valid_pass", "s2": "valid_pass", "s3": "undefined_no_crossing",
                                         "s4": "ambiguous_multiple_crossings"},
                       "decision": "repair_stb_then_repeat_quick", "next_action": "inspect_loop_break_and_pole_order",
                       "prohibited_actions": ["treat_no_crossing_pm_as_pass", "average_phase_margin", "run_full_matrix_before_stb_repair"]},
            "checks": [
                mapping("rows", "row_classes", {"s1": "valid_pass", "s2": "valid_pass", "s3": "undefined_no_crossing",
                                                  "s4": "ambiguous_multiple_crossings"}, 40, "stb_interpretation"),
                exact("decision", "decision", "repair_stb_then_repeat_quick", 25, "stop_rule", True),
                exact("next", "next_action", "inspect_loop_break_and_pole_order", 20, "diagnostic_action"),
                set_f1("prohibited", "prohibited_actions", ["treat_no_crossing_pm_as_pass", "average_phase_margin",
                                                              "run_full_matrix_before_stb_repair"], 15, "safety"),
            ],
            "relevant_knowledge_ids": ["kg-stb-crossing", "kg-gated-qualification"],
        },
        {
            "task_id": "v07-closure-02-banked-scope", "title": "Separate banked performance from open functional gates",
            "suite": "design_closure", "level": "L4", "deployment_tier": "T3_multi_constraint_closure",
            "capabilities": ["design_closure", "startup_enable", "evidence_integrity", "qualification"],
            "scenario": "A candidate improves all steady-state metrics, yet startup and enable sequencing are incomplete. State exactly what can be banked and what cannot be claimed.",
            "materials": {
                "baseline": {"dropout_mv": 96, "pm_deg": 52, "iq_ua": 111, "startup_pass": True, "enable_pass": True},
                "candidate": {"dropout_mv": 82, "pm_deg": 59, "iq_ua": 104, "psrr_100khz_db": 31,
                              "startup_fast": True, "startup_nominal": False, "startup_slow": None,
                              "enable_shutdown_restart": False, "candidate_hash": "cand-new"},
                "evidence": {"steady_state_hash_bound": True, "startup_hash_bound": True,
                             "full_corner_complete": False, "materialization_readback": False},
            },
            "catalogs": {
                "scopes": ["steady_state_performance", "startup", "enable_restart", "full_corner", "materialization", "complete_design"],
                "statuses": ["banked", "open_fail", "open_missing", "not_applicable"],
                "decisions": ["register_complete", "bank_partial_continue", "reject_all_progress", "retry_infrastructure"],
                "actions": ["repair_startup_and_enable", "rerun_steady_state_only", "publish_champion", "change_reference"],
            },
            "fields": {
                "scope_status": field_map(["steady_state_performance", "startup", "enable_restart", "full_corner", "materialization", "complete_design"],
                                          ["banked", "open_fail", "open_missing", "not_applicable"]),
                "decision": field_string(["register_complete", "bank_partial_continue", "reject_all_progress", "retry_infrastructure"]),
                "next_action": field_string(["repair_startup_and_enable", "rerun_steady_state_only", "publish_champion", "change_reference"]),
                "claimable_scopes": field_list(["steady_state_performance", "startup", "enable_restart", "full_corner", "materialization", "complete_design"], 1),
            },
            "answer": {"scope_status": {"steady_state_performance": "banked", "startup": "open_fail",
                                         "enable_restart": "open_fail", "full_corner": "open_missing",
                                         "materialization": "open_missing", "complete_design": "open_fail"},
                       "decision": "bank_partial_continue", "next_action": "repair_startup_and_enable",
                       "claimable_scopes": ["steady_state_performance"]},
            "checks": [
                mapping("scope", "scope_status", {"steady_state_performance": "banked", "startup": "open_fail",
                                                   "enable_restart": "open_fail", "full_corner": "open_missing",
                                                   "materialization": "open_missing", "complete_design": "open_fail"}, 45, "scope_accounting"),
                exact("decision", "decision", "bank_partial_continue", 20, "qualification_decision", True),
                exact("next", "next_action", "repair_startup_and_enable", 20, "next_action"),
                set_f1("claim", "claimable_scopes", ["steady_state_performance"], 15, "claim_boundary"),
            ],
            "relevant_knowledge_ids": ["kg-banked-scope", "kg-startup-evidence"],
        },
        {
            "task_id": "v07-closure-03-corner-qualification", "title": "Audit a multi-corner LDO qualification manifest",
            "suite": "design_closure", "level": "L4", "deployment_tier": "T3_multi_constraint_closure",
            "capabilities": ["qualification", "corner_analysis", "evidence_integrity", "numeric_reasoning"],
            "scenario": "An 18-corner qualification summary contains missing metrics, mixed candidate hashes, and metric-specific worst corners. Audit it without inventing one global worst corner.",
            "materials": {
                "current_candidate_hash": "h42", "expected_corner_count": 18,
                "summary": {"completed_rows": 18, "reported_hard_pass": True},
                "rows": [
                    {"id": "r1", "hash": "h42", "corner": "ss_low_hot_heavy", "dropout_mv": 88, "pm_deg": 53, "startup": True, "iq_ua": 105},
                    {"id": "r2", "hash": "h42", "corner": "ff_high_cold_light", "dropout_mv": 61, "pm_deg": None, "startup": True, "iq_ua": 119},
                    {"id": "r3", "hash": "h-old", "corner": "tt_nom_room_heavy", "dropout_mv": 70, "pm_deg": 58, "startup": True, "iq_ua": 101},
                    {"id": "r4", "hash": "h42", "corner": "sf_low_cold_light", "dropout_mv": 77, "pm_deg": 49, "startup": False, "iq_ua": 108},
                ],
                "limits": {"dropout_max_mv": 90, "pm_min_deg": 50, "iq_max_ua": 120, "startup_required": True},
                "note": "The other 14 rows are current-hash complete and pass all four limits.",
            },
            "catalogs": {
                "row_classes": ["valid_pass", "metric_missing", "stale_hash", "hard_fail", "infrastructure_fail"],
                "decisions": ["qualified", "not_qualified", "infrastructure_retry", "partial_bank_only"],
                "missing_gates": ["pm_r2", "current_hash_r3", "pm_r4", "startup_r4", "none"],
                "worst_keys": ["dropout", "phase_margin", "iq", "startup"],
                "corner_ids": ["ss_low_hot_heavy", "ff_high_cold_light", "tt_nom_room_heavy", "sf_low_cold_light", "undefined"],
            },
            "fields": {
                "row_classes": field_map(["r1", "r2", "r3", "r4"], ["valid_pass", "metric_missing", "stale_hash", "hard_fail", "infrastructure_fail"]),
                "decision": field_string(["qualified", "not_qualified", "infrastructure_retry", "partial_bank_only"]),
                "missing_or_failed_gates": field_list(["pm_r2", "current_hash_r3", "pm_r4", "startup_r4", "none"], 1),
                "metric_worst_corners": field_map(["dropout", "phase_margin", "iq", "startup"],
                                                  ["ss_low_hot_heavy", "ff_high_cold_light", "tt_nom_room_heavy", "sf_low_cold_light", "undefined"]),
            },
            "answer": {"row_classes": {"r1": "valid_pass", "r2": "metric_missing", "r3": "stale_hash", "r4": "hard_fail"},
                       "decision": "not_qualified", "missing_or_failed_gates": ["pm_r2", "current_hash_r3", "pm_r4", "startup_r4"],
                       "metric_worst_corners": {"dropout": "ss_low_hot_heavy", "phase_margin": "sf_low_cold_light",
                                                "iq": "ff_high_cold_light", "startup": "sf_low_cold_light"}},
            "checks": [
                mapping("rows", "row_classes", {"r1": "valid_pass", "r2": "metric_missing", "r3": "stale_hash", "r4": "hard_fail"}, 30, "row_audit"),
                exact("decision", "decision", "not_qualified", 25, "qualification_decision", True),
                set_f1("gates", "missing_or_failed_gates", ["pm_r2", "current_hash_r3", "pm_r4", "startup_r4"], 25, "gate_accounting"),
                mapping("worst", "metric_worst_corners", {"dropout": "ss_low_hot_heavy", "phase_margin": "sf_low_cold_light",
                                                            "iq": "ff_high_cold_light", "startup": "sf_low_cold_light"}, 20, "worst_corner_analysis"),
            ],
            "relevant_knowledge_ids": ["kg-gated-qualification", "kg-metric-specific-worst"],
        },
        {
            "task_id": "v07-closure-04-candidate-pareto", "title": "Select a deployable LDO candidate under coupled gates",
            "suite": "architecture_choice", "level": "L4", "deployment_tier": "T3_multi_constraint_closure",
            "capabilities": ["candidate_selection", "architecture_choice", "multi_objective", "qualification"],
            "scenario": "Choose a candidate for formal verification. Scores are secondary to hard gates; a dominated but robust candidate may be preferable to a higher raw score.",
            "materials": {
                "limits": {"dropout_max_mv": 90, "pm_min_deg": 50, "iq_max_ua": 120, "noise_max_uv": 10,
                           "startup_required": True, "max_area_index": 1.40},
                "candidates": [
                    {"id": "a", "dropout_mv": 84, "pm_deg": 54, "iq_ua": 112, "noise_uv": 8.9, "startup": True, "area": 1.22, "raw_score": 86},
                    {"id": "b", "dropout_mv": 78, "pm_deg": 48, "iq_ua": 110, "noise_uv": 8.2, "startup": True, "area": 1.30, "raw_score": 91},
                    {"id": "c", "dropout_mv": 86, "pm_deg": 57, "iq_ua": 124, "noise_uv": 7.8, "startup": True, "area": 1.18, "raw_score": 89},
                    {"id": "d", "dropout_mv": 80, "pm_deg": 55, "iq_ua": 115, "noise_uv": 9.7, "startup": False, "area": 1.37, "raw_score": 93},
                    {"id": "e", "dropout_mv": 88, "pm_deg": 52, "iq_ua": 118, "noise_uv": 9.5, "startup": True, "area": 1.45, "raw_score": 84},
                ],
                "formal_budget": "one candidate",
            },
            "catalogs": {
                "candidate_ids": ["a", "b", "c", "d", "e", "none"],
                "gate_classes": ["hard_pass", "pm_fail", "iq_fail", "startup_fail", "area_fail", "multiple_fail"],
                "actions": ["formal_verify_a", "formal_verify_b", "formal_verify_d", "rescore_only"],
                "checks": ["fresh_op", "startup_matrix", "stb_load_corners", "noise", "full_pvt", "materialization_readback",
                           "reuse_search_metrics_only"],
            },
            "fields": {
                "candidate_gate_map": field_map(["a", "b", "c", "d", "e"],
                                                ["hard_pass", "pm_fail", "iq_fail", "startup_fail", "area_fail", "multiple_fail"]),
                "selected_candidate": field_string(["a", "b", "c", "d", "e", "none"]),
                "next_action": field_string(["formal_verify_a", "formal_verify_b", "formal_verify_d", "rescore_only"]),
                "formal_checks": field_list(["fresh_op", "startup_matrix", "stb_load_corners", "noise", "full_pvt",
                                              "materialization_readback", "reuse_search_metrics_only"], 1),
            },
            "answer": {"candidate_gate_map": {"a": "hard_pass", "b": "pm_fail", "c": "iq_fail", "d": "startup_fail", "e": "area_fail"},
                       "selected_candidate": "a", "next_action": "formal_verify_a",
                       "formal_checks": ["fresh_op", "startup_matrix", "stb_load_corners", "noise", "full_pvt", "materialization_readback"]},
            "checks": [
                mapping("gates", "candidate_gate_map", {"a": "hard_pass", "b": "pm_fail", "c": "iq_fail", "d": "startup_fail", "e": "area_fail"}, 40, "constraint_accounting"),
                exact("selected", "selected_candidate", "a", 25, "candidate_selection", True),
                exact("next", "next_action", "formal_verify_a", 15, "next_action"),
                set_f1("checks", "formal_checks", ["fresh_op", "startup_matrix", "stb_load_corners", "noise", "full_pvt", "materialization_readback"], 20, "verification_plan"),
            ],
            "relevant_knowledge_ids": ["kg-hard-gates-before-score", "kg-gated-qualification"],
        },
        {
            "task_id": "v07-system-01-spectral-impact", "title": "Translate LDO spectra into a downstream error budget",
            "suite": "system_impact", "level": "L3", "deployment_tier": "T2_bounded_workflow",
            "capabilities": ["system_impact", "psrr", "noise", "numeric_reasoning"],
            "scenario": "Compute downstream RMS error from independent LDO noise and supply-ripple paths, then identify which mitigation is supported by the spectrum.",
            "materials": {
                "ldo_output_noise_uv_rms": 24.0,
                "supply_ripple": [{"frequency_hz": 1000, "vin_mv_rms": 12.0, "psrr_db": 44.0},
                                  {"frequency_hz": 2000000, "vin_mv_rms": 4.0, "psrr_db": 18.0}],
                "load_sensitivity_v_per_v": 0.65,
                "system_limit_uv_rms": 80.0,
                "assumption": "The three paths are independent RMS sources.",
                "definitions": {
                    "psrr_db": "20*log10(VIN_ripple_rms / VOUT_ripple_rms)",
                    "downstream_transfer": "Multiply each LDO-output disturbance by load_sensitivity_v_per_v.",
                    "independent_rms_combination": "Take the square root of the sum of squared downstream RMS paths."
                },
            },
            "catalogs": {
                "dominant_paths": ["ldo_noise", "low_frequency_ripple", "high_frequency_ripple", "equal"],
                "actions": ["improve_high_frequency_feedthrough", "increase_dc_loop_gain", "reduce_reference_noise", "no_change"],
                "combination_rules": ["rss", "linear_sum", "max_only"],
            },
            "fields": {
                "low_frequency_downstream_uv_rms": {"type": "number"},
                "high_frequency_downstream_uv_rms": {"type": "number"},
                "downstream_total_uv_rms": {"type": "number"},
                "dominant_path": field_string(["ldo_noise", "low_frequency_ripple", "high_frequency_ripple", "equal"]),
                "combination_rule": field_string(["rss", "linear_sum", "max_only"]),
                "next_action": field_string(["improve_high_frequency_feedthrough", "increase_dc_loop_gain", "reduce_reference_noise", "no_change"]),
            },
            "answer": {"low_frequency_downstream_uv_rms": 49.2, "high_frequency_downstream_uv_rms": 327.3,
                       "downstream_total_uv_rms": 331.4, "dominant_path": "high_frequency_ripple",
                       "combination_rule": "rss", "next_action": "improve_high_frequency_feedthrough"},
            "checks": [
                numeric("low", "low_frequency_downstream_uv_rms", 49.2, 1.0, 30, 15, "numeric_reasoning"),
                numeric("high", "high_frequency_downstream_uv_rms", 327.3, 4.0, 120, 20, "numeric_reasoning"),
                numeric("total", "downstream_total_uv_rms", 331.4, 4.0, 100, 20, "numeric_reasoning"),
                exact("dominant", "dominant_path", "high_frequency_ripple", 15, "system_diagnosis", True),
                exact("rule", "combination_rule", "rss", 10, "assumption_handling"),
                exact("next", "next_action", "improve_high_frequency_feedthrough", 20, "action_selection"),
            ],
            "relevant_knowledge_ids": ["kg-psrr-system-budget"],
        },
        {
            "task_id": "v07-migration-01-intent-map", "title": "Map LDO sizing intent into SKY130 legal controls",
            "suite": "migration", "level": "L3", "deployment_tier": "T2_bounded_workflow",
            "capabilities": ["migration", "pdk_semantics", "sizing", "evidence_integrity"],
            "scenario": "Translate source-process sizing intent into a legal SKY130 first-pass plan. Do not copy W/L literally or assume CDF names from another PDK.",
            "materials": {
                "source_roles": [
                    {"id": "src_pass", "intent": {"type": "pmos_pass", "current_ma": 12, "gm_id": 8.5, "headroom_mv": 95}},
                    {"id": "src_input", "intent": {"type": "nmos_input_pair", "branch_ua": 18, "gm_id": 14.0, "intrinsic_gain_min": 20}},
                    {"id": "src_ccomp", "intent": {"type": "mim_compensation", "cap_pf": 7.5, "voltage_v": 1.8}},
                    {"id": "src_start", "intent": {"type": "startup_injection", "cold_na": 2.2, "hot_leakage_max_na": 45}},
                ],
                "sky130_survey": [
                    {"id": "t_pass", "primitive": "sky130_fd_pr__pfet_01v8", "pins_verified": True, "legal_l_um": [0.15, 0.18, 0.50]},
                    {"id": "t_input", "primitive": "sky130_fd_pr__nfet_01v8", "pins_verified": True, "legal_l_um": [0.15, 0.50, 1.00]},
                    {"id": "t_mim", "primitive": "sky130_fd_pr__cap_mim_m3_1", "pins_verified": True, "voltage_rating_v": 2.0},
                    {"id": "t_diode", "primitive": "sky130_fd_pr__diode_pw2nd_05v5", "pins_verified": False},
                ],
            },
            "catalogs": {
                "source_ids": ["src_pass", "src_input", "src_ccomp", "src_start"],
                "target_ids": ["t_pass", "t_input", "t_mim", "t_diode", "unresolved"],
                "actions": ["characterize_idw_and_headroom", "characterize_gmid_and_gain", "compute_area_then_pvt",
                            "verify_startup_primitive_pins_and_leakage", "copy_source_geometry"],
                "stages": ["device_smoke", "intent_mapping", "nominal_op", "startup", "stb", "pvt"],
            },
            "fields": {
                "role_mapping": field_map(["src_pass", "src_input", "src_ccomp", "src_start"], ["t_pass", "t_input", "t_mim", "t_diode", "unresolved"]),
                "role_actions": field_map(["src_pass", "src_input", "src_ccomp", "src_start"],
                                          ["characterize_idw_and_headroom", "characterize_gmid_and_gain", "compute_area_then_pvt",
                                           "verify_startup_primitive_pins_and_leakage", "copy_source_geometry"]),
                "action_sequence": field_list(["device_smoke", "intent_mapping", "nominal_op", "startup", "stb", "pvt"], 1),
                "blocked_roles": field_list(["src_pass", "src_input", "src_ccomp", "src_start"], 1),
            },
            "answer": {"role_mapping": {"src_pass": "t_pass", "src_input": "t_input", "src_ccomp": "t_mim", "src_start": "unresolved"},
                       "role_actions": {"src_pass": "characterize_idw_and_headroom", "src_input": "characterize_gmid_and_gain",
                                        "src_ccomp": "compute_area_then_pvt", "src_start": "verify_startup_primitive_pins_and_leakage"},
                       "action_sequence": ["device_smoke", "intent_mapping", "nominal_op", "startup", "stb", "pvt"],
                       "blocked_roles": ["src_start"]},
            "checks": [
                mapping("mapping", "role_mapping", {"src_pass": "t_pass", "src_input": "t_input", "src_ccomp": "t_mim", "src_start": "unresolved"}, 35, "intent_mapping"),
                mapping("actions", "role_actions", {"src_pass": "characterize_idw_and_headroom", "src_input": "characterize_gmid_and_gain",
                                                      "src_ccomp": "compute_area_then_pvt", "src_start": "verify_startup_primitive_pins_and_leakage"}, 30, "migration_plan"),
                sequence("sequence", "action_sequence", ["device_smoke", "intent_mapping", "nominal_op", "startup", "stb", "pvt"], 20, "workflow_order"),
                set_f1("blocked", "blocked_roles", ["src_start"], 15, "blocker_recognition", True),
            ],
            "relevant_knowledge_ids": ["kg-migration-intent", "kg-op-first"],
        },
        {
            "task_id": "v07-eda-01-oa-readback-plan", "title": "Plan a safe Virtuoso OA sizing edit",
            "suite": "eda_tool", "level": "L3", "deployment_tier": "T2_bounded_workflow",
            "capabilities": ["virtuoso", "skill", "oa", "materialization"],
            "scenario": "Given an IC618 scratch-cell task, plan one parameter edit and prove it persists. The answer must distinguish logical OA connectivity, visible geometry, CDF callbacks, and fresh netlist evidence.",
            "materials": {
                "target": {"library": "EVOLDO_SCRATCH", "cell": "ldo_candidate", "view": "schematic",
                           "instance": "MPASS", "parameter": "w", "from": "120u", "to": "160u"},
                "constraints": {"existing_libraries_read_only": True, "scratch_copy_required": True,
                                "pdk_parameter_requires_cdf_callback": True, "fresh_netlist_required": True},
                "observed_state": {"source_oa_open": True, "scratch_created": False, "saved": False},
            },
            "catalogs": {
                "steps": ["open_source_read_only", "create_scratch_copy", "edit_parameter", "invoke_cdf_callback", "schematic_check",
                          "save_close", "reopen_readback", "fresh_netlist", "fresh_op", "accept_or_revert"],
                "proofs": ["oa_property_readback", "netlist_parameter_readback", "fresh_op_provenance", "screenshot_only", "source_python_bom"],
                "prohibited": ["edit_source_library", "skip_cdf_callback", "accept_without_reopen", "claim_from_screenshot",
                               "use_scratch_copy"],
                "decisions": ["execute_in_scratch", "edit_source_directly", "accept_visual_only", "insufficient_contract"],
            },
            "fields": {
                "decision": field_string(["execute_in_scratch", "edit_source_directly", "accept_visual_only", "insufficient_contract"]),
                "action_sequence": field_list(["open_source_read_only", "create_scratch_copy", "edit_parameter", "invoke_cdf_callback", "schematic_check",
                                                "save_close", "reopen_readback", "fresh_netlist", "fresh_op", "accept_or_revert"], 1),
                "required_proofs": field_list(["oa_property_readback", "netlist_parameter_readback", "fresh_op_provenance", "screenshot_only", "source_python_bom"], 1),
                "prohibited_actions": field_list(["edit_source_library", "skip_cdf_callback", "accept_without_reopen",
                                                   "claim_from_screenshot", "use_scratch_copy"], 1),
            },
            "answer": {"decision": "execute_in_scratch",
                       "action_sequence": ["open_source_read_only", "create_scratch_copy", "edit_parameter", "invoke_cdf_callback", "schematic_check",
                                           "save_close", "reopen_readback", "fresh_netlist", "fresh_op", "accept_or_revert"],
                       "required_proofs": ["oa_property_readback", "netlist_parameter_readback", "fresh_op_provenance"],
                       "prohibited_actions": ["edit_source_library", "skip_cdf_callback", "accept_without_reopen", "claim_from_screenshot"]},
            "checks": [
                exact("decision", "decision", "execute_in_scratch", 20, "safety_decision", True),
                sequence("sequence", "action_sequence", ["open_source_read_only", "create_scratch_copy", "edit_parameter", "invoke_cdf_callback", "schematic_check",
                                                           "save_close", "reopen_readback", "fresh_netlist", "fresh_op", "accept_or_revert"], 35, "eda_workflow"),
                set_f1("proofs", "required_proofs", ["oa_property_readback", "netlist_parameter_readback", "fresh_op_provenance"], 25, "persistence_evidence"),
                set_f1("prohibited", "prohibited_actions", ["edit_source_library", "skip_cdf_callback", "accept_without_reopen", "claim_from_screenshot"], 20, "safety"),
            ],
            "relevant_knowledge_ids": ["kg-oa-save-readback", "kg-cdf-netlist"],
        },
        {
            "task_id": "v07-eda-02-net-vs-wire", "title": "Repair an OA connectivity and display mismatch",
            "suite": "eda_tool", "level": "L3", "deployment_tier": "T2_bounded_workflow",
            "capabilities": ["virtuoso", "skill", "oa", "connectivity"],
            "scenario": "An LDO schematic looks connected, but extracted connectivity and netlisting disagree. Classify observations and order a non-destructive repair.",
            "materials": {
                "observations": [
                    {"id": "o1", "source": "screenshot", "fact": "A drawn wire visually touches MPASS gate."},
                    {"id": "o2", "source": "oa", "fact": "MPASS/G has net=nil."},
                    {"id": "o3", "source": "oa", "fact": "A shape labeled VCTRL ends 0.0625 grid units from the pin figure."},
                    {"id": "o4", "source": "netlist", "fact": "MPASS gate is emitted as an unconnected generated net."},
                    {"id": "o5", "source": "schematic_check", "fact": "One dangling terminal is reported."},
                ],
                "scratch_cell": True,
            },
            "catalogs": {
                "observation_ids": ["o1", "o2", "o3", "o4", "o5"],
                "classes": ["visual_only", "logical_connectivity", "geometry_gap", "netlist_evidence", "checker_evidence"],
                "steps": ["read_terminal_pin_geometry", "create_named_net", "create_wire_to_pin", "schematic_check", "save_close",
                          "reopen_connectivity", "fresh_netlist", "visual_screenshot"],
                "decisions": ["repair_logical_and_visible", "add_label_only", "accept_visual", "infrastructure_retry"],
            },
            "fields": {
                "observation_classes": field_map(["o1", "o2", "o3", "o4", "o5"],
                                                 ["visual_only", "logical_connectivity", "geometry_gap", "netlist_evidence", "checker_evidence"]),
                "decision": field_string(["repair_logical_and_visible", "add_label_only", "accept_visual", "infrastructure_retry"]),
                "action_sequence": field_list(["read_terminal_pin_geometry", "create_named_net", "create_wire_to_pin", "schematic_check", "save_close",
                                                "reopen_connectivity", "fresh_netlist", "visual_screenshot"], 1),
            },
            "answer": {"observation_classes": {"o1": "visual_only", "o2": "logical_connectivity", "o3": "geometry_gap",
                                                   "o4": "netlist_evidence", "o5": "checker_evidence"},
                       "decision": "repair_logical_and_visible",
                       "action_sequence": ["read_terminal_pin_geometry", "create_named_net", "create_wire_to_pin", "schematic_check",
                                           "save_close", "reopen_connectivity", "fresh_netlist", "visual_screenshot"]},
            "checks": [
                mapping("classes", "observation_classes", {"o1": "visual_only", "o2": "logical_connectivity", "o3": "geometry_gap",
                                                             "o4": "netlist_evidence", "o5": "checker_evidence"}, 40, "evidence_classification"),
                exact("decision", "decision", "repair_logical_and_visible", 25, "repair_decision", True),
                sequence("sequence", "action_sequence", ["read_terminal_pin_geometry", "create_named_net", "create_wire_to_pin", "schematic_check",
                                                           "save_close", "reopen_connectivity", "fresh_netlist", "visual_screenshot"], 35, "eda_workflow"),
            ],
            "relevant_knowledge_ids": ["kg-oa-net-vs-wire", "kg-oa-save-readback"],
        },
        {
            "task_id": "v07-foundation-04-divider-candidates", "title": "Size and screen a feedback divider",
            "suite": "sizing", "level": "L1", "deployment_tier": "T0_foundation",
            "capabilities": ["sizing", "numeric_reasoning", "constraint_accounting"],
            "scenario": "Compute divider behavior and screen candidates against accuracy, current, and noise-resistance gates. Among hard-pass candidates, select minimum absolute output error; break a tie by lower total resistance.",
            "materials": {
                "vref_v": 0.60, "target_vout_v": 1.20,
                "limits": {"abs_error_max_mv": 3.0, "divider_current_max_ua": 3.0, "rtop_plus_rbot_max_kohm": 900},
                "candidates": [
                    {"id": "d1", "rtop_kohm": 300, "rbot_kohm": 300},
                    {"id": "d2", "rtop_kohm": 499, "rbot_kohm": 500},
                    {"id": "d3", "rtop_kohm": 240, "rbot_kohm": 241},
                    {"id": "d4", "rtop_kohm": 680, "rbot_kohm": 680},
                ]
            },
            "catalogs": {
                "candidate_ids": ["d1", "d2", "d3", "d4", "none"],
                "gate_classes": ["hard_pass", "accuracy_fail", "current_fail", "resistance_fail", "multiple_fail"],
                "actions": ["select_d1", "select_d2", "select_d3", "select_d4", "respec"],
            },
            "fields": {
                "candidate_gate_map": field_map(["d1", "d2", "d3", "d4"],
                                                ["hard_pass", "accuracy_fail", "current_fail", "resistance_fail", "multiple_fail"]),
                "selected_candidate": field_string(["d1", "d2", "d3", "d4", "none"]),
                "selected_vout_mv": {"type": "number"}, "selected_current_ua": {"type": "number"},
                "next_action": field_string(["select_d1", "select_d2", "select_d3", "select_d4", "respec"]),
            },
            "answer": {"candidate_gate_map": {"d1": "hard_pass", "d2": "resistance_fail", "d3": "hard_pass", "d4": "resistance_fail"},
                       "selected_candidate": "d1", "selected_vout_mv": 1200.0, "selected_current_ua": 2.0,
                       "next_action": "select_d1"},
            "checks": [
                mapping("gates", "candidate_gate_map", {"d1": "hard_pass", "d2": "resistance_fail", "d3": "hard_pass", "d4": "resistance_fail"}, 35, "constraint_accounting"),
                exact("selected", "selected_candidate", "d1", 20, "candidate_selection"),
                numeric("vout", "selected_vout_mv", 1200, 0.5, 50, 15, "numeric_reasoning"),
                numeric("current", "selected_current_ua", 2, 0.02, 1, 15, "numeric_reasoning"),
                exact("next", "next_action", "select_d1", 15, "action_selection"),
            ],
            "relevant_knowledge_ids": [],
        },
        {
            "task_id": "v07-foundation-05-failure-lane", "title": "Separate circuit, measurement, and infrastructure failures",
            "suite": "diagnosis", "level": "L1", "deployment_tier": "T0_foundation",
            "capabilities": ["diagnosis", "failure_classification", "workflow_planning"],
            "scenario": "Route independent failures to the correct lane before deciding which runs can be scored.",
            "materials": {
                "events": [
                    {"id": "f1", "facts": ["provider HTTP 502", "no model response", "no answer artifact"]},
                    {"id": "f2", "facts": ["ngspice exit 0", "VOUT=0.12V", "target=0.80V", "bias branches measured active"]},
                    {"id": "f3", "facts": ["spectre run completed", "requested vector absent", "testbench saved wrong node"]},
                    {"id": "f4", "facts": ["answer JSON present", "uses undeclared option ID", "provider healthy"]},
                    {"id": "f5", "facts": ["license checkout denied", "simulator did not start"]},
                ]
            },
            "catalogs": {
                "classes": ["provider_infrastructure", "circuit", "measurement", "format", "eda_infrastructure"],
                "event_ids": ["f1", "f2", "f3", "f4", "f5"],
                "retry_ids": ["f1", "f2", "f3", "f4", "f5"],
                "score_ids": ["f1", "f2", "f3", "f4", "f5"],
            },
            "fields": {
                "failure_classes": field_map(["f1", "f2", "f3", "f4", "f5"],
                                             ["provider_infrastructure", "circuit", "measurement", "format", "eda_infrastructure"]),
                "must_retry_not_score": field_list(["f1", "f2", "f3", "f4", "f5"], 1),
                "model_answer_failures": field_list(["f1", "f2", "f3", "f4", "f5"], 1),
            },
            "answer": {"failure_classes": {"f1": "provider_infrastructure", "f2": "circuit", "f3": "measurement",
                                            "f4": "format", "f5": "eda_infrastructure"},
                       "must_retry_not_score": ["f1", "f3", "f5"], "model_answer_failures": ["f4"]},
            "checks": [
                mapping("classes", "failure_classes", {"f1": "provider_infrastructure", "f2": "circuit", "f3": "measurement",
                                                        "f4": "format", "f5": "eda_infrastructure"}, 50, "failure_classification"),
                set_f1("retry", "must_retry_not_score", ["f1", "f3", "f5"], 30, "retry_policy", True),
                set_f1("answer", "model_answer_failures", ["f4"], 20, "model_failure_attribution"),
            ],
            "relevant_knowledge_ids": ["kg-gated-qualification"],
        },
        {
            "task_id": "v07-local-01-pass-turning", "title": "Recognize a pass-width turning point",
            "suite": "trend", "level": "L2", "deployment_tier": "T1_local_advice",
            "capabilities": ["trend", "sizing", "feedback_stability", "candidate_selection"],
            "scenario": "Select the smallest robust pass width from a characterized sweep and state why the trend is not monotonic in total quality.",
            "materials": {
                "limits": {"dropout_max_mv": 90, "pm_min_deg": 50, "settling_max_us": 8.0},
                "sweep": [
                    {"id": "w1", "width_um": 400, "dropout_mv": 121, "pm_deg": 61, "settling_us": 6.2, "gate_cap_pf": 8},
                    {"id": "w2", "width_um": 600, "dropout_mv": 94, "pm_deg": 57, "settling_us": 6.8, "gate_cap_pf": 12},
                    {"id": "w3", "width_um": 800, "dropout_mv": 86, "pm_deg": 53, "settling_us": 7.5, "gate_cap_pf": 16},
                    {"id": "w4", "width_um": 1000, "dropout_mv": 78, "pm_deg": 47, "settling_us": 9.4, "gate_cap_pf": 20},
                    {"id": "w5", "width_um": 1200, "dropout_mv": 72, "pm_deg": 41, "settling_us": 12.1, "gate_cap_pf": 24},
                ]
            },
            "catalogs": {
                "candidate_ids": ["w1", "w2", "w3", "w4", "w5", "none"],
                "mechanisms": ["ron_vs_gate_capacitance", "divider_loading", "reference_noise", "startup_leakage"],
                "actions": ["verify_w3_across_corners", "choose_w5_lowest_dropout", "increase_width_unbounded", "change_reference"],
                "hard_pass_ids": ["w1", "w2", "w3", "w4", "w5"],
            },
            "fields": {
                "hard_pass_candidates": field_list(["w1", "w2", "w3", "w4", "w5"], 1),
                "selected_candidate": field_string(["w1", "w2", "w3", "w4", "w5", "none"]),
                "dominant_tradeoff": field_string(["ron_vs_gate_capacitance", "divider_loading", "reference_noise", "startup_leakage"]),
                "next_action": field_string(["verify_w3_across_corners", "choose_w5_lowest_dropout", "increase_width_unbounded", "change_reference"]),
            },
            "answer": {"hard_pass_candidates": ["w3"], "selected_candidate": "w3",
                       "dominant_tradeoff": "ron_vs_gate_capacitance", "next_action": "verify_w3_across_corners"},
            "checks": [
                set_f1("pass", "hard_pass_candidates", ["w3"], 30, "constraint_accounting"),
                exact("selected", "selected_candidate", "w3", 25, "candidate_selection", True),
                exact("mechanism", "dominant_tradeoff", "ron_vs_gate_capacitance", 25, "physical_mechanism"),
                exact("next", "next_action", "verify_w3_across_corners", 20, "validation_plan"),
            ],
            "relevant_knowledge_ids": ["kg-hard-gates-before-score"],
        },
        {
            "task_id": "v07-local-02-startup-window", "title": "Diagnose a startup-helper strength window",
            "suite": "trend", "level": "L2", "deployment_tier": "T1_local_advice",
            "capabilities": ["startup_enable", "trend", "sizing", "controlled_experiment"],
            "scenario": "Interpret a one-variable startup-helper sweep across cold and hot conditions, then choose the bounded next experiment.",
            "materials": {
                "limits": {"cold_start_max_us": 25, "hot_leakage_max_na": 50, "vout_error_max_mv": 8},
                "sweep": [
                    {"id": "k1", "strength": 0.5, "cold_start_us": None, "hot_leakage_na": 9, "vout_error_mv": 1},
                    {"id": "k2", "strength": 1.0, "cold_start_us": 31, "hot_leakage_na": 18, "vout_error_mv": 2},
                    {"id": "k3", "strength": 1.5, "cold_start_us": 18, "hot_leakage_na": 31, "vout_error_mv": 4},
                    {"id": "k4", "strength": 2.0, "cold_start_us": 13, "hot_leakage_na": 47, "vout_error_mv": 9},
                    {"id": "k5", "strength": 3.0, "cold_start_us": 8, "hot_leakage_na": 79, "vout_error_mv": 17},
                ],
                "held_fixed": ["bench", "candidate_except_helper", "corner_endpoints", "load"],
            },
            "catalogs": {
                "candidate_ids": ["k1", "k2", "k3", "k4", "k5", "none"],
                "classes": ["no_start", "slow_start", "hard_pass", "accuracy_fail", "leakage_and_accuracy_fail"],
                "mechanisms": ["minimum_injection_vs_hot_exit_leakage", "loop_gain_only", "pass_ron_only", "measurement_error"],
                "actions": ["verify_k3_full_startup_matrix", "choose_k5", "change_all_biases", "accept_k4"],
            },
            "fields": {
                "candidate_classes": field_map(["k1", "k2", "k3", "k4", "k5"],
                                               ["no_start", "slow_start", "hard_pass", "accuracy_fail", "leakage_and_accuracy_fail"]),
                "selected_candidate": field_string(["k1", "k2", "k3", "k4", "k5", "none"]),
                "dominant_tradeoff": field_string(["minimum_injection_vs_hot_exit_leakage", "loop_gain_only", "pass_ron_only", "measurement_error"]),
                "next_action": field_string(["verify_k3_full_startup_matrix", "choose_k5", "change_all_biases", "accept_k4"]),
            },
            "answer": {"candidate_classes": {"k1": "no_start", "k2": "slow_start", "k3": "hard_pass",
                                                "k4": "accuracy_fail", "k5": "leakage_and_accuracy_fail"},
                       "selected_candidate": "k3", "dominant_tradeoff": "minimum_injection_vs_hot_exit_leakage",
                       "next_action": "verify_k3_full_startup_matrix"},
            "checks": [
                mapping("classes", "candidate_classes", {"k1": "no_start", "k2": "slow_start", "k3": "hard_pass",
                                                           "k4": "accuracy_fail", "k5": "leakage_and_accuracy_fail"}, 40, "constraint_accounting"),
                exact("selected", "selected_candidate", "k3", 20, "candidate_selection", True),
                exact("tradeoff", "dominant_tradeoff", "minimum_injection_vs_hot_exit_leakage", 20, "physical_mechanism"),
                exact("next", "next_action", "verify_k3_full_startup_matrix", 20, "validation_plan"),
            ],
            "relevant_knowledge_ids": ["kg-startup-evidence"],
        },
        {
            "task_id": "v07-local-03-measurement-repair", "title": "Repair a misleading PSRR measurement",
            "suite": "diagnosis", "level": "L2", "deployment_tier": "T1_local_advice",
            "capabilities": ["psrr", "measurement", "diagnosis", "controlled_experiment"],
            "scenario": "A surprising PSRR improvement appears after a testbench edit. Determine whether it is circuit evidence and define the shortest valid repair.",
            "materials": {
                "before": {"candidate_hash": "c88", "vin_dc_v": 1.8, "vin_ac_v": 1.0, "load_ma": 5,
                           "probe": "vout", "psrr_100khz_db": 24},
                "after": {"candidate_hash": "c88", "vin_dc_v": 1.8, "vin_ac_v": 0.001, "load_ma": 0.5,
                          "probe": "vfb", "reported_psrr_100khz_db": 66},
                "circuit_changed": False,
            },
            "catalogs": {
                "classes": ["circuit_improvement", "measurement_contract_changed", "provider_infrastructure", "roundoff_only"],
                "mismatches": ["ac_amplitude", "load", "probe_node", "candidate_hash", "dc_supply"],
                "steps": ["restore_same_ac_normalization", "restore_same_load", "probe_vout", "fresh_run", "compare_same_hash",
                          "resize_pass", "accept_report"],
                "claim_scopes": ["no_circuit_claim", "psrr_improved", "full_qualification"],
            },
            "fields": {
                "failure_class": field_string(["circuit_improvement", "measurement_contract_changed", "provider_infrastructure", "roundoff_only"]),
                "contract_mismatches": field_list(["ac_amplitude", "load", "probe_node", "candidate_hash", "dc_supply"], 1),
                "action_sequence": field_list(["restore_same_ac_normalization", "restore_same_load", "probe_vout", "fresh_run", "compare_same_hash",
                                                "resize_pass", "accept_report"], 1),
                "claim_scope": field_string(["no_circuit_claim", "psrr_improved", "full_qualification"]),
            },
            "answer": {"failure_class": "measurement_contract_changed",
                       "contract_mismatches": ["ac_amplitude", "load", "probe_node"],
                       "action_sequence": ["restore_same_ac_normalization", "restore_same_load", "probe_vout", "fresh_run", "compare_same_hash"],
                       "claim_scope": "no_circuit_claim"},
            "checks": [
                exact("class", "failure_class", "measurement_contract_changed", 25, "failure_classification", True),
                set_f1("mismatch", "contract_mismatches", ["ac_amplitude", "load", "probe_node"], 30, "measurement_audit"),
                sequence("sequence", "action_sequence", ["restore_same_ac_normalization", "restore_same_load", "probe_vout", "fresh_run", "compare_same_hash"], 30, "repair_plan"),
                exact("scope", "claim_scope", "no_circuit_claim", 15, "claim_boundary"),
            ],
            "relevant_knowledge_ids": ["kg-evidence-admission"],
        },
        {
            "task_id": "v07-local-04-compensation-plan", "title": "Choose a bounded compensation experiment",
            "suite": "sizing", "level": "L2", "deployment_tier": "T1_local_advice",
            "capabilities": ["sizing", "feedback_stability", "controlled_experiment", "validation_plan"],
            "scenario": "A capless LDO fails light-load PM but passes heavy load. Choose a one-variable compensation experiment that preserves interpretability.",
            "materials": {
                "baseline": {"ccomp_pf": 5.0, "rz_kohm": 18, "driver_w_um": 12,
                             "light_pm_deg": 43, "light_ugb_mhz": 1.8, "heavy_pm_deg": 58,
                             "heavy_ugb_mhz": 3.1, "settling_us": 5.8, "settling_limit_us": 8.0},
                "analytic_priors": ["Increasing Ccomp often lowers crossover but may improve PM.",
                                    "Rz can move a zero and may worsen the wrong load regime."],
                "legal_values": {"ccomp_pf": [4, 5, 6, 7], "rz_kohm": [12, 18, 24], "driver_w_um": [10, 12, 14]},
            },
            "catalogs": {
                "experiments": ["ccomp_4_5_6_7_fixed_others", "change_ccomp_rz_driver", "rz_only_12_18_24", "full_random_search"],
                "held": ["rz", "driver_w", "pass_w", "bias", "bench", "load_matrix", "ccomp"],
                "measurements": ["light_pm", "light_ugb", "heavy_pm", "heavy_ugb", "settling", "op", "iq", "startup_only"],
                "stop_rules": ["stop_if_no_light_pm_gain_or_settling_fails", "stop_after_best_nominal", "never_stop"],
            },
            "fields": {
                "experiment": field_string(["ccomp_4_5_6_7_fixed_others", "change_ccomp_rz_driver", "rz_only_12_18_24", "full_random_search"]),
                "held_fixed": field_list(["rz", "driver_w", "pass_w", "bias", "bench", "load_matrix", "ccomp"], 1),
                "measurements": field_list(["light_pm", "light_ugb", "heavy_pm", "heavy_ugb", "settling", "op", "iq", "startup_only"], 1),
                "stop_rule": field_string(["stop_if_no_light_pm_gain_or_settling_fails", "stop_after_best_nominal", "never_stop"]),
            },
            "answer": {"experiment": "ccomp_4_5_6_7_fixed_others",
                       "held_fixed": ["rz", "driver_w", "pass_w", "bias", "bench", "load_matrix"],
                       "measurements": ["light_pm", "light_ugb", "heavy_pm", "heavy_ugb", "settling", "op", "iq"],
                       "stop_rule": "stop_if_no_light_pm_gain_or_settling_fails"},
            "checks": [
                exact("experiment", "experiment", "ccomp_4_5_6_7_fixed_others", 30, "experiment_design", True),
                set_f1("held", "held_fixed", ["rz", "driver_w", "pass_w", "bias", "bench", "load_matrix"], 25, "held_fixed"),
                set_f1("measure", "measurements", ["light_pm", "light_ugb", "heavy_pm", "heavy_ugb", "settling", "op", "iq"], 25, "measurement_plan"),
                exact("stop", "stop_rule", "stop_if_no_light_pm_gain_or_settling_fails", 20, "stop_rule"),
            ],
            "relevant_knowledge_ids": ["kg-controlled-experiment", "kg-stb-crossing"],
        },
        {
            "task_id": "v07-closure-05-artifact-consistency", "title": "Reconcile a contradictory closure artifact set",
            "suite": "design_closure", "level": "L4", "deployment_tier": "T3_multi_constraint_closure",
            "capabilities": ["evidence_integrity", "qualification", "failure_classification", "workflow_planning"],
            "scenario": "A closure package contains contradictory hashes and terminal states. Reconcile the set before any design claim or rerun.",
            "materials": {
                "artifacts": [
                    {"id": "a1", "type": "candidate_manifest", "candidate_hash": "h9", "profile_hash": "p4", "status": "materialized"},
                    {"id": "a2", "type": "autosize_report", "candidate_hash": "h9", "profile_hash": "p4", "status": "completed_verified", "score": 88.2},
                    {"id": "a3", "type": "result_manifest", "candidate_hash": "h8", "profile_hash": "p4", "status": "completed_verified", "score": 88.2},
                    {"id": "a4", "type": "qualification", "candidate_hash": "h9", "profile_hash": "p3", "status": "hard_pass", "corners": 18},
                    {"id": "a5", "type": "oa_readback", "candidate_hash": "h9", "profile_hash": "p4", "status": "missing"},
                    {"id": "a6", "type": "startup", "candidate_hash": "h9", "profile_hash": "p4", "status": "pass"},
                ]
            },
            "catalogs": {
                "classes": ["consistent_current", "candidate_hash_mismatch", "profile_hash_mismatch", "missing_required", "stale", "unknown"],
                "artifact_ids": ["a1", "a2", "a3", "a4", "a5", "a6"],
                "decisions": ["qualified", "insufficient_evidence", "circuit_fail", "infrastructure_retry"],
                "actions": ["regenerate_manifest_and_qualification_from_h9_p4", "accept_majority_hash", "rerun_all_without_reconciling", "register_h9"],
                "claim_scopes": ["no_final_claim", "search_improved", "fully_qualified"],
            },
            "fields": {
                "artifact_classes": field_map(["a1", "a2", "a3", "a4", "a5", "a6"],
                                              ["consistent_current", "candidate_hash_mismatch", "profile_hash_mismatch", "missing_required", "stale", "unknown"]),
                "decision": field_string(["qualified", "insufficient_evidence", "circuit_fail", "infrastructure_retry"]),
                "blocking_artifacts": field_list(["a1", "a2", "a3", "a4", "a5", "a6"], 1),
                "next_action": field_string(["regenerate_manifest_and_qualification_from_h9_p4", "accept_majority_hash", "rerun_all_without_reconciling", "register_h9"]),
                "claim_scope": field_string(["no_final_claim", "search_improved", "fully_qualified"]),
            },
            "answer": {"artifact_classes": {"a1": "consistent_current", "a2": "consistent_current",
                                              "a3": "candidate_hash_mismatch", "a4": "profile_hash_mismatch",
                                              "a5": "missing_required", "a6": "consistent_current"},
                       "decision": "insufficient_evidence", "blocking_artifacts": ["a3", "a4", "a5"],
                       "next_action": "regenerate_manifest_and_qualification_from_h9_p4", "claim_scope": "no_final_claim"},
            "checks": [
                mapping("classes", "artifact_classes", {"a1": "consistent_current", "a2": "consistent_current",
                                                          "a3": "candidate_hash_mismatch", "a4": "profile_hash_mismatch",
                                                          "a5": "missing_required", "a6": "consistent_current"}, 40, "artifact_reconciliation"),
                exact("decision", "decision", "insufficient_evidence", 20, "terminal_decision", True),
                set_f1("blocking", "blocking_artifacts", ["a3", "a4", "a5"], 15, "blocker_identification"),
                exact("next", "next_action", "regenerate_manifest_and_qualification_from_h9_p4", 15, "recovery_plan"),
                exact("scope", "claim_scope", "no_final_claim", 10, "claim_boundary"),
            ],
            "relevant_knowledge_ids": ["kg-final-artifact-consistency", "kg-oa-save-readback"],
        },
        {
            "task_id": "v07-architecture-01-advice-gates", "title": "Gate an existing-architecture optimization plan",
            "suite": "architecture_choice", "level": "L5", "deployment_tier": "T4_end_to_end_planning",
            "capabilities": ["architecture_choice", "operating_point", "evidence_integrity", "controlled_experiment", "workflow_planning"],
            "scenario": "Review a proposed gain-improvement plan for an existing capless LDO. Separate what current evidence authorizes now from contingent hypotheses and qualification-only work.",
            "materials": {
                "current_identity": {"candidate_hash": "h31", "bench_hash": "b7", "corner": "tt_nom_room"},
                "evidence": [
                    {"id": "m1", "candidate_hash": "h31", "bench_hash": "b7", "kind": "op",
                     "facts": {"input_pair": "saturation", "cascode": "triode", "cascode_headroom_mv": 18, "required_headroom_mv": 35}},
                    {"id": "m2", "candidate_hash": "h31", "bench_hash": "b7", "kind": "ac",
                     "facts": {"dc_gain_db": 43, "target_gain_db": 58, "phase_margin_deg": 52}},
                    {"id": "m3", "candidate_hash": "h24", "bench_hash": "b7", "kind": "controlled_pair",
                     "facts": {"input_l_change": "+40%", "gain_delta_db": 9, "phase_margin_delta_deg": -3}},
                    {"id": "m4", "candidate_hash": None, "bench_hash": None, "kind": "analytical_prior",
                     "facts": {"claim": "gain boosting can increase loop gain but adds poles and current"}},
                    {"id": "m5", "candidate_hash": "h31", "bench_hash": "b7", "kind": "startup",
                     "facts": {"zero_state_startup": "pass", "iq_ua": 106, "iq_limit_ua": 120}}
                ],
                "current_knobs": {"cascode_bias_v": 0.51, "input_l_um": 0.50, "recycle_ratio": None, "pass_w_um": 820},
                "proposals": [
                    {"id": "p1", "action": "increase_pass_width_20pct", "changed_knobs": ["pass_w"], "evidence_ids": []},
                    {"id": "p2", "action": "small_cascode_bias_pair", "changed_knobs": ["cascode_bias"], "evidence_ids": ["m1"]},
                    {"id": "p3", "action": "increase_recycle_ratio", "changed_knobs": ["recycle_ratio"], "evidence_ids": []},
                    {"id": "p4", "action": "input_length_controlled_pair", "changed_knobs": ["input_l"], "evidence_ids": ["m3"]},
                    {"id": "p5", "action": "add_gain_boost_stage", "changed_knobs": ["topology", "bias"], "evidence_ids": ["m4"]},
                    {"id": "p6", "action": "run_full_pvt", "changed_knobs": [], "evidence_ids": ["m2", "m5"]}
                ],
                "review_policy": {
                    "evidence_order": ["current_hash_bound_measurement", "unbound_old_measurement", "analytical_prior"],
                    "hard_gate": "A critical device in triode blocks performance sizing and full qualification until OP recovery is measured on the current hash.",
                    "controlled_pair": "One known current knob, same bench/corner, hash-bound baseline and candidate, followed by current OP and affected-metric checks.",
                    "missing_knob": "Do not propose a delta from an unknown current value.",
                    "topology_change": "Defer until bounded same-architecture levers have current evidence.",
                    "conditional_plan": "Only the OP-recovery experiment is authorized now; downstream sizing remains contingent on a passing fresh OP.",
                    "proposal_status_rules": {
                        "admissible_op_recovery": "Directly repairs the current measured OP blocker with one known knob.",
                        "contingent_after_op": "Has a relevant measured controlled-pair result, but that result is bound to an older candidate and must be repeated only after OP recovery.",
                        "unsupported_before_op": "Has no supporting evidence and does not directly repair the measured OP blocker.",
                        "blocked_missing_current_knob": "Requires a delta from an unknown current knob value.",
                        "deferred_topology": "Changes topology before bounded same-architecture levers are exhausted.",
                        "blocked_qualification_gate": "Attempts qualification while a prerequisite hard gate is open."
                    }
                }
            },
            "catalogs": {
                "evidence_ids": ["m1", "m2", "m3", "m4", "m5"],
                "evidence_labels": ["measured_current", "unbound_old", "analytical_prior"],
                "proposal_ids": ["p1", "p2", "p3", "p4", "p5", "p6"],
                "proposal_statuses": ["admissible_op_recovery", "unsupported_before_op", "blocked_missing_current_knob",
                                      "contingent_after_op", "deferred_topology", "blocked_qualification_gate"],
                "gates": ["recover_operating_point", "measure_gain_only", "full_qualification", "change_topology"],
                "actions": ["small_cascode_bias_pair", "verify_op_headroom", "remeasure_gain_pm_iq_startup",
                            "input_length_controlled_pair", "increase_pass_width_20pct", "add_gain_boost_stage", "run_full_pvt"],
                "stages": ["op_recovery_experiment", "same_architecture_sizing", "quick_regression", "full_qualification"],
                "stop_rules": ["stop_if_op_headroom_or_pm_or_iq_worsens", "stop_after_nominal_gain", "never_stop"]
            },
            "fields": {
                "evidence_labels": field_map(["m1", "m2", "m3", "m4", "m5"],
                                             ["measured_current", "unbound_old", "analytical_prior"]),
                "proposal_status": field_map(["p1", "p2", "p3", "p4", "p5", "p6"],
                                             ["admissible_op_recovery", "unsupported_before_op", "blocked_missing_current_knob",
                                              "contingent_after_op", "deferred_topology", "blocked_qualification_gate"]),
                "primary_gate": field_string(["recover_operating_point", "measure_gain_only", "full_qualification", "change_topology"]),
                "authorized_action_sequence": field_list(["small_cascode_bias_pair", "verify_op_headroom", "remeasure_gain_pm_iq_startup",
                                                            "input_length_controlled_pair", "increase_pass_width_20pct",
                                                            "add_gain_boost_stage", "run_full_pvt"], 1),
                "contingent_next_action": field_string(["small_cascode_bias_pair", "input_length_controlled_pair",
                                                         "increase_pass_width_20pct", "add_gain_boost_stage", "run_full_pvt"]),
                "max_authorized_stage": field_string(["op_recovery_experiment", "same_architecture_sizing", "quick_regression", "full_qualification"]),
                "stop_rule": field_string(["stop_if_op_headroom_or_pm_or_iq_worsens", "stop_after_nominal_gain", "never_stop"])
            },
            "answer": {
                "evidence_labels": {"m1": "measured_current", "m2": "measured_current", "m3": "unbound_old",
                                    "m4": "analytical_prior", "m5": "measured_current"},
                "proposal_status": {"p1": "unsupported_before_op", "p2": "admissible_op_recovery",
                                    "p3": "blocked_missing_current_knob", "p4": "contingent_after_op",
                                    "p5": "deferred_topology", "p6": "blocked_qualification_gate"},
                "primary_gate": "recover_operating_point",
                "authorized_action_sequence": ["small_cascode_bias_pair", "verify_op_headroom", "remeasure_gain_pm_iq_startup"],
                "contingent_next_action": "input_length_controlled_pair",
                "max_authorized_stage": "op_recovery_experiment",
                "stop_rule": "stop_if_op_headroom_or_pm_or_iq_worsens"
            },
            "checks": [
                mapping("evidence", "evidence_labels", {"m1": "measured_current", "m2": "measured_current",
                                                          "m3": "unbound_old", "m4": "analytical_prior",
                                                          "m5": "measured_current"}, 20, "evidence_hierarchy"),
                mapping("proposals", "proposal_status", {"p1": "unsupported_before_op", "p2": "admissible_op_recovery",
                                                            "p3": "blocked_missing_current_knob", "p4": "contingent_after_op",
                                                            "p5": "deferred_topology", "p6": "blocked_qualification_gate"},
                        30, "proposal_admission"),
                exact("gate", "primary_gate", "recover_operating_point", 15, "operating_point_gate", True),
                sequence("sequence", "authorized_action_sequence",
                         ["small_cascode_bias_pair", "verify_op_headroom", "remeasure_gain_pm_iq_startup"],
                         15, "workflow_order"),
                exact("contingent", "contingent_next_action", "input_length_controlled_pair", 10, "conditional_plan"),
                exact("stage", "max_authorized_stage", "op_recovery_experiment", 5, "claim_boundary"),
                exact("stop", "stop_rule", "stop_if_op_headroom_or_pm_or_iq_worsens", 5, "stop_rule")
            ],
            "relevant_knowledge_ids": ["kg-op-first", "kg-evidence-admission", "kg-architecture-advice-order", "kg-controlled-experiment"]
        },
        {
            "task_id": "v07-sizing-01-optimizer-admission", "title": "Admit sizing evaluations and design the next probe",
            "suite": "sizing", "level": "L5", "deployment_tier": "T4_end_to_end_planning",
            "capabilities": ["sizing", "failure_classification", "evidence_integrity", "controlled_experiment", "candidate_selection"],
            "scenario": "Audit a mixed sizing ledger, keep infrastructure and measurement failures out of the optimizer, select the best hard-pass candidate, and construct the next legal one-variable experiment.",
            "materials": {
                "current_profile_hash": "p9",
                "hard_limits": {"dropout_max_mv": 90, "pm_min_deg": 50, "iq_max_ua": 120, "startup_required": True},
                "legal_space": {"driver_w_um": [12, 14, 16, 18, 20], "ccomp_pf": [5, 6, 7], "input_nf": [2, 4, 6, 8]},
                "evaluations": [
                    {"id": "e1", "status": "MEASURED", "profile_hash": "p9", "candidate_hash": "c1",
                     "params": {"driver_w_um": 14, "ccomp_pf": 5, "input_nf": 4},
                     "metrics": {"dropout_mv": 96, "pm_deg": 47, "iq_ua": 101, "startup": True, "score": 72}},
                    {"id": "e2", "status": "INFRA_ERROR", "failure": "license_checkout", "profile_hash": "p9", "metrics": {}},
                    {"id": "e3", "status": "MEAS_ERROR", "failure": "pm_vector_missing", "profile_hash": "p9",
                     "metrics": {"dropout_mv": 91, "iq_ua": 104}},
                    {"id": "e4", "status": "INVALID_CANDIDATE", "failure": "input_nf_not_on_legal_grid", "profile_hash": "p9",
                     "params": {"driver_w_um": 16, "ccomp_pf": 6, "input_nf": 5}, "metrics": {}},
                    {"id": "e5", "status": "MEASURED", "profile_hash": "p9", "candidate_hash": "c5",
                     "params": {"driver_w_um": 16, "ccomp_pf": 6, "input_nf": 4},
                     "metrics": {"dropout_mv": 93, "pm_deg": 52, "iq_ua": 107, "startup": True, "score": 81}},
                    {"id": "e6", "status": "MEASURED", "profile_hash": "p9", "candidate_hash": "c6",
                     "params": {"driver_w_um": 18, "ccomp_pf": 6, "input_nf": 4},
                     "metrics": {"dropout_mv": 88, "pm_deg": 54, "iq_ua": 119, "startup": True, "score": 88}},
                    {"id": "e7", "status": "MEASURED", "profile_hash": "p9", "candidate_hash": "c7",
                     "params": {"driver_w_um": 20, "ccomp_pf": 7, "input_nf": 4},
                     "metrics": {"dropout_mv": 85, "pm_deg": 57, "iq_ua": 126, "startup": True, "score": 91}},
                    {"id": "e8", "status": "MEASURED", "profile_hash": "p-old", "candidate_hash": "c8",
                     "params": {"driver_w_um": 18, "ccomp_pf": 6, "input_nf": 4},
                     "metrics": {"dropout_mv": 84, "pm_deg": 56, "iq_ua": 112, "startup": True, "score": 94}},
                    {"id": "e9", "status": "INFRA_ERROR", "failure": "provider_http_503", "profile_hash": "p9", "metrics": {}}
                ],
                "admission_policy": {
                    "measured": "A current-profile MEASURED row with all required numeric/boolean metrics is an objective observation and consumes design budget.",
                    "invalid_candidate": "A deterministic legal-space rejection is a feasibility observation and consumes design budget, but never receives invented metric values.",
                    "infra_or_measurement": "INFRA_ERROR and MEAS_ERROR are retried, excluded from both surrogates, and consume no design budget.",
                    "stale_identity": "A row from another profile is evidence-integrity excluded and rerun on the current profile before use.",
                    "selection": "Select the highest-score candidate among rows passing every hard limit.",
                    "next_probe": "Because e7 changes both driver width and Ccomp relative to e6, isolate driver_w=20 at e6's Ccomp and input_nf before inferring a driver sensitivity."
                }
            },
            "catalogs": {
                "evaluation_ids": ["e1", "e2", "e3", "e4", "e5", "e6", "e7", "e8", "e9"],
                "tags": ["measured", "objective_observation", "design_budget", "infrastructure", "measurement",
                         "retry", "exclude", "invalid_candidate", "feasibility_observation", "evidence_integrity"],
                "candidate_ids": ["e1", "e4", "e5", "e6", "e7", "e8", "none"],
                "experiment_bases": ["isolate_driver_from_e6", "continue_from_highest_raw_score", "repeat_infrastructure_as_design", "expand_legal_grid"],
                "stop_rules": ["stop_if_iq_fails_or_no_score_gain", "stop_after_one_simulation", "never_stop"]
            },
            "fields": {
                "evaluation_tags": field_list_map(
                    ["e1", "e2", "e3", "e4", "e5", "e6", "e7", "e8", "e9"],
                    ["measured", "objective_observation", "design_budget", "infrastructure", "measurement",
                     "retry", "exclude", "invalid_candidate", "feasibility_observation", "evidence_integrity"]),
                "admitted_evaluations": field_list(["e1", "e2", "e3", "e4", "e5", "e6", "e7", "e8", "e9"], 1),
                "design_budget_consumed": {"type": "number"},
                "best_hard_pass_candidate": field_string(["e1", "e4", "e5", "e6", "e7", "e8", "none"]),
                "next_driver_w_um": {"type": "number"},
                "next_ccomp_pf": {"type": "number"},
                "next_experiment_basis": field_string(["isolate_driver_from_e6", "continue_from_highest_raw_score",
                                                         "repeat_infrastructure_as_design", "expand_legal_grid"]),
                "stop_rule": field_string(["stop_if_iq_fails_or_no_score_gain", "stop_after_one_simulation", "never_stop"])
            },
            "answer": {
                "evaluation_tags": {
                    "e1": ["measured", "objective_observation", "design_budget"],
                    "e2": ["infrastructure", "retry", "exclude"],
                    "e3": ["measurement", "retry", "exclude"],
                    "e4": ["invalid_candidate", "feasibility_observation", "design_budget"],
                    "e5": ["measured", "objective_observation", "design_budget"],
                    "e6": ["measured", "objective_observation", "design_budget"],
                    "e7": ["measured", "objective_observation", "design_budget"],
                    "e8": ["evidence_integrity", "retry", "exclude"],
                    "e9": ["infrastructure", "retry", "exclude"]
                },
                "admitted_evaluations": ["e1", "e4", "e5", "e6", "e7"],
                "design_budget_consumed": 5,
                "best_hard_pass_candidate": "e6",
                "next_driver_w_um": 20,
                "next_ccomp_pf": 6,
                "next_experiment_basis": "isolate_driver_from_e6",
                "stop_rule": "stop_if_iq_fails_or_no_score_gain"
            },
            "checks": [
                multilabel_mapping("tags", "evaluation_tags", {
                    "e1": ["measured", "objective_observation", "design_budget"],
                    "e2": ["infrastructure", "retry", "exclude"],
                    "e3": ["measurement", "retry", "exclude"],
                    "e4": ["invalid_candidate", "feasibility_observation", "design_budget"],
                    "e5": ["measured", "objective_observation", "design_budget"],
                    "e6": ["measured", "objective_observation", "design_budget"],
                    "e7": ["measured", "objective_observation", "design_budget"],
                    "e8": ["evidence_integrity", "retry", "exclude"],
                    "e9": ["infrastructure", "retry", "exclude"]}, 40, "evaluation_admission"),
                set_f1("admitted", "admitted_evaluations", ["e1", "e4", "e5", "e6", "e7"], 15, "surrogate_admission"),
                numeric("budget", "design_budget_consumed", 5, 0, 3, 10, "budget_accounting"),
                exact("best", "best_hard_pass_candidate", "e6", 15, "candidate_selection", True),
                numeric("driver", "next_driver_w_um", 20, 0, 5, 7.5, "experiment_design"),
                numeric("ccomp", "next_ccomp_pf", 6, 0, 2, 7.5, "held_fixed"),
                exact("basis", "next_experiment_basis", "isolate_driver_from_e6", 3, "experiment_design"),
                exact("stop", "stop_rule", "stop_if_iq_fails_or_no_score_gain", 2, "stop_rule")
            ],
            "relevant_knowledge_ids": ["kg-controlled-experiment", "kg-hard-gates-before-score", "kg-search-is-not-final"]
        },
        {
            "task_id": "v07-closure-06-cross-stage-recovery", "title": "Plan a cross-stage LDO closure recovery",
            "suite": "design_closure", "level": "L5", "deployment_tier": "T4_end_to_end_planning",
            "capabilities": ["workflow_planning", "sizing", "qualification", "eda_tool", "evidence_integrity"],
            "scenario": "A partially materialized candidate fails at several stages. Produce a minimal, gate-respecting recovery plan with one causal change per loop.",
            "materials": {
                "state": {
                    "source_hash": "h20", "oa_hash": "h19", "netlist_hash": "h19",
                    "connectivity": "pass", "op": "pass", "startup": "pass", "stb": "light_load_pm_fail",
                    "quick": {"dropout": "pass", "iq": "pass", "noise": "pass", "transient": "undershoot_fail"},
                    "full": "not_run", "oa_readback": "parameter_mismatch"
                },
                "candidate_history": [
                    {"id": "c1", "change": "driver_w_plus_15pct", "light_pm_delta_deg": 5, "undershoot_delta_mv": -9, "iq_delta_ua": 6,
                     "same_bench_corner": True, "hash_bound": True},
                    {"id": "c2", "change": "ccomp_plus_20pct_and_driver_plus_20pct", "light_pm_delta_deg": 9, "undershoot_delta_mv": -14,
                     "iq_delta_ua": 8, "same_bench_corner": True, "hash_bound": True},
                    {"id": "c3", "change": "pass_w_plus_30pct", "light_pm_delta_deg": -7, "undershoot_delta_mv": -3, "iq_delta_ua": 0,
                     "same_bench_corner": False, "hash_bound": True},
                ],
                "limits": {"light_pm_min_deg": 50, "current_light_pm_deg": 46, "undershoot_max_mv": 60,
                           "current_undershoot_mv": 68, "iq_margin_ua": 12},
                "recovery_contract": {
                    "artifact_gate": "Resolve source/OA/netlist identity and persistent readback before interpreting downstream simulation evidence.",
                    "causal_gate": "Only a hash-bound, same-bench, same-corner, one-knob comparison is a reusable local sensitivity.",
                    "qualification_gate": "After readback and a fresh netlist, re-establish OP/startup, run one bounded causal experiment, repeat quick STB/transient/IQ, and stop on any failed quick limit before full qualification.",
                    "registration_gate": "Register only after full qualification and final OA readback are current."
                },
            },
            "catalogs": {
                "root_causes": ["source_oa_hash_divergence", "stb_and_transient_coupled", "pass_width_only", "infrastructure"],
                "stages": ["reconcile_source_oa", "save_close_reopen", "fresh_netlist", "fresh_op_startup", "single_driver_experiment",
                           "quick_stb_transient_iq", "full_qualification", "register"],
                "history_classes": ["valid_single_variable", "confounded_multi_variable", "bench_confounded", "invalid"],
                "prohibited": ["run_full_on_h19", "apply_c2_as_causal", "increase_pass_width", "register_without_readback",
                               "discard_hash_bound_c1"],
                "stop_rules": ["stop_if_readback_or_hash_mismatch", "stop_if_pm_or_undershoot_or_iq_fails", "never_stop"],
            },
            "fields": {
                "primary_root_cause": field_string(["source_oa_hash_divergence", "stb_and_transient_coupled", "pass_width_only", "infrastructure"]),
                "history_classes": field_map(["c1", "c2", "c3"], ["valid_single_variable", "confounded_multi_variable", "bench_confounded", "invalid"]),
                "action_sequence": field_list(["reconcile_source_oa", "save_close_reopen", "fresh_netlist", "fresh_op_startup", "single_driver_experiment",
                                                "quick_stb_transient_iq", "full_qualification", "register"], 1),
                "prohibited_actions": field_list(["run_full_on_h19", "apply_c2_as_causal", "increase_pass_width",
                                                   "register_without_readback", "discard_hash_bound_c1"], 1),
                "stop_rule": field_string(["stop_if_readback_or_hash_mismatch", "stop_if_pm_or_undershoot_or_iq_fails", "never_stop"]),
            },
            "answer": {"primary_root_cause": "source_oa_hash_divergence",
                       "history_classes": {"c1": "valid_single_variable", "c2": "confounded_multi_variable", "c3": "bench_confounded"},
                       "action_sequence": ["reconcile_source_oa", "save_close_reopen", "fresh_netlist", "fresh_op_startup",
                                           "single_driver_experiment", "quick_stb_transient_iq", "full_qualification", "register"],
                       "prohibited_actions": ["run_full_on_h19", "apply_c2_as_causal", "increase_pass_width", "register_without_readback"],
                       "stop_rule": "stop_if_pm_or_undershoot_or_iq_fails"},
            "checks": [
                exact("cause", "primary_root_cause", "source_oa_hash_divergence", 20, "root_cause", True),
                mapping("history", "history_classes", {"c1": "valid_single_variable", "c2": "confounded_multi_variable", "c3": "bench_confounded"}, 25, "evidence_classification"),
                sequence("sequence", "action_sequence", ["reconcile_source_oa", "save_close_reopen", "fresh_netlist", "fresh_op_startup",
                                                           "single_driver_experiment", "quick_stb_transient_iq", "full_qualification", "register"], 30, "workflow_order"),
                set_f1("prohibited", "prohibited_actions", ["run_full_on_h19", "apply_c2_as_causal", "increase_pass_width", "register_without_readback"], 15, "safety"),
                exact("stop", "stop_rule", "stop_if_pm_or_undershoot_or_iq_fails", 10, "stop_rule"),
            ],
            "relevant_knowledge_ids": ["kg-oa-save-readback", "kg-controlled-experiment", "kg-gated-qualification"],
        },
        {
            "task_id": "v07-eda-03-failure-recovery", "title": "Route a Virtuoso and simulator failure stack",
            "suite": "eda_tool", "level": "L4", "deployment_tier": "T3_multi_constraint_closure",
            "capabilities": ["virtuoso", "skill", "failure_classification", "workflow_planning"],
            "scenario": "A VM-based IC618 run reports several failures. Route each failure and choose the first repair without modifying the DUT to hide infrastructure or bench defects.",
            "materials": {
                "events": [
                    {"id": "v1", "stage": "ssh_preflight", "returncode": 255, "message": "connection reset"},
                    {"id": "v2", "stage": "oa_open", "returncode": 0, "message": "cellview opens read-only"},
                    {"id": "v3", "stage": "netlist", "returncode": 1, "message": "unknown CDF parameter fingers on MPASS"},
                    {"id": "v4", "stage": "spectre", "returncode": 1, "message": "model section ff not found"},
                    {"id": "v5", "stage": "measure", "returncode": 0, "message": "VOUT vector absent because save selection excludes it"},
                    {"id": "v6", "stage": "dc_op", "returncode": 0, "message": "with corrected fixture VOUT remains 0.18V at target 0.8V"},
                ],
                "attempt_order": ["v1", "v2", "v3", "v4", "v5", "v6"],
            },
            "catalogs": {
                "classes": ["transport_infrastructure", "healthy_control", "cdf_netlisting", "pdk_fixture", "measurement_fixture", "circuit"],
                "event_ids": ["v1", "v2", "v3", "v4", "v5", "v6"],
                "actions": ["retry_transport", "fix_cdf_mapping", "fix_model_section", "fix_save_selection", "diagnose_circuit_op", "resize_dut"],
                "scoreable_ids": ["v1", "v2", "v3", "v4", "v5", "v6"],
            },
            "fields": {
                "failure_classes": field_map(["v1", "v2", "v3", "v4", "v5", "v6"],
                                             ["transport_infrastructure", "healthy_control", "cdf_netlisting", "pdk_fixture", "measurement_fixture", "circuit"]),
                "repair_sequence": field_list(["retry_transport", "fix_cdf_mapping", "fix_model_section", "fix_save_selection", "diagnose_circuit_op", "resize_dut"], 1),
                "first_circuit_evidence": field_string(["v1", "v2", "v3", "v4", "v5", "v6"]),
                "not_scoreable_as_model_circuit_failure": field_list(["v1", "v2", "v3", "v4", "v5", "v6"], 1),
            },
            "answer": {"failure_classes": {"v1": "transport_infrastructure", "v2": "healthy_control", "v3": "cdf_netlisting",
                                            "v4": "pdk_fixture", "v5": "measurement_fixture", "v6": "circuit"},
                       "repair_sequence": ["retry_transport", "fix_cdf_mapping", "fix_model_section", "fix_save_selection", "diagnose_circuit_op"],
                       "first_circuit_evidence": "v6", "not_scoreable_as_model_circuit_failure": ["v1", "v3", "v4", "v5"]},
            "checks": [
                mapping("classes", "failure_classes", {"v1": "transport_infrastructure", "v2": "healthy_control", "v3": "cdf_netlisting",
                                                        "v4": "pdk_fixture", "v5": "measurement_fixture", "v6": "circuit"}, 40, "failure_classification"),
                sequence("sequence", "repair_sequence", ["retry_transport", "fix_cdf_mapping", "fix_model_section", "fix_save_selection", "diagnose_circuit_op"], 30, "recovery_order"),
                exact("circuit", "first_circuit_evidence", "v6", 15, "evidence_boundary", True),
                set_f1("not_score", "not_scoreable_as_model_circuit_failure", ["v1", "v3", "v4", "v5"], 15, "attribution_policy"),
            ],
            "relevant_knowledge_ids": ["kg-cdf-netlist", "kg-gated-qualification"],
        },
    ]


def knowledge_corpus() -> Dict[str, Any]:
    entries = [
        ("kg-feedback-return-ratio", "Feedback polarity and return ratio",
         "A perturbation sign chain can establish local negative feedback, but stability requires a bias-preserving return-ratio measurement at the same operating point.", ["feedback", "polarity", "return ratio"]),
        ("kg-op-first", "Operating-point-first recovery",
         "Verify generated-netlist connectivity, terminal order, body and CDF semantics before restoring DC bias, cascode headroom, pass regulation, startup, STB, and qualification in that order.", ["operating point", "headroom", "workflow"]),
        ("kg-startup-evidence", "Startup evidence boundary",
         "Convergence with a nodeset, initial condition, or internal force is diagnostic evidence only. Final startup evidence must begin from the required physical zero state without those crutches.", ["startup", "nodeset", "force"]),
        ("kg-stb-crossing", "STB crossing validity",
         "Phase margin is meaningful only for the declared loop and a valid crossing rule. Missing or multiple zero-dB crossings require diagnosis rather than accepting a finite printed number.", ["stb", "phase margin", "crossing"]),
        ("kg-evidence-admission", "Evidence admission",
         "Current measured facts must be bound to the candidate, profile, bench, and corner. Old or unbound measurements and literature priors may rank tests but cannot authorize a design change.", ["hash", "evidence", "provenance"]),
        ("kg-architecture-advice-order", "Architecture advice order",
         "For low gain, repair unhealthy operating points and cascode headroom first, then test architecture-specific bounded levers, output resistance, transconductance efficiency, loading, and only then topology changes.", ["architecture", "gain", "cascode"]),
        ("kg-sizing-two-pass", "Two-pass sizing space",
         "Use the production pipeline to inventory exact legal parameter paths first, then build a role-aware reduced space. Do not invent aliases, matching couplings, or rewrite integer legal domains.", ["sizing", "parameter space", "roles"]),
        ("kg-search-is-not-final", "Search is not final",
         "Optimization-only results are search evidence. Acceptance requires callback-aware backannotation, immutable result artifacts, and a fresh final verification on the materialized candidate.", ["search", "backannotation", "final"]),
        ("kg-final-artifact-consistency", "Final artifact consistency",
         "A final result requires mutually consistent report and manifest status, candidate identity, score, hard-gate state, and fresh-final provenance. Missing or contradictory artifacts mean insufficient evidence.", ["manifest", "candidate", "final"]),
        ("kg-controlled-experiment", "Controlled experiment admission",
         "Causal or local-sensitivity language requires exactly one changed knob, the same bench/profile/corner, distinct candidate hashes, numeric paired metrics, and verified evidence hashes.", ["controlled experiment", "causal", "ledger"]),
        ("kg-gated-qualification", "Gated qualification",
         "Run cheap prerequisite gates before expensive matrices. Missing operating point, startup, or STB evidence blocks full qualification and is reported separately from simulator infrastructure failure.", ["qualification", "gates", "stop rule"]),
        ("kg-banked-scope", "Banked scope",
         "A candidate may bank a hash-bound performance improvement while startup, enable, full-corner, or materialization gates remain open. Banked scope is not complete design qualification.", ["banked", "scope", "startup"]),
        ("kg-metric-specific-worst", "Metric-specific worst corners",
         "Different metrics often have different worst corners. Preserve each metric's stress point and do not average hard constraints or invent one universal worst corner.", ["corner", "worst case", "pvt"]),
        ("kg-hard-gates-before-score", "Hard gates before scores",
         "A higher objective score never compensates for a failed hard gate. Select among hard-pass candidates before comparing Pareto performance and resource cost.", ["hard gate", "pareto", "candidate"]),
        ("kg-psrr-system-budget", "PSRR system budgeting",
         "Convert each supply-ripple tone through the linear PSRR attenuation, apply downstream sensitivity, and combine independent RMS paths by root-sum-square.", ["psrr", "ripple", "rss"]),
        ("kg-migration-intent", "Process migration by intent",
         "Migrate current density, gm over ID, intrinsic gain, headroom, passive value and voltage rating into target-PDK legal devices. Do not copy source geometry or CDF names literally.", ["migration", "gmid", "pdk"]),
        ("kg-oa-save-readback", "OA persistence evidence",
         "For a Virtuoso edit, work in a scratch copy, save, close, reopen, read OA properties and connectivity back, then produce a fresh netlist or simulation before acceptance.", ["virtuoso", "oa", "readback"]),
        ("kg-cdf-netlist", "CDF parameter semantics",
         "PDK instance edits may require CDF callbacks before netlisting. Verify the generated netlist parameter rather than assuming an OA display property changed simulation semantics.", ["cdf", "netlist", "skill"]),
        ("kg-oa-net-vs-wire", "Logical net versus visible wire",
         "A visible shape or label does not prove OA terminal connectivity, and a logical net alone may not satisfy schematic readability. Verify both connectivity and persistent geometry when both are required.", ["oa", "wire", "connectivity"]),
    ]
    return {"schema_version": "1.0", "corpus_id": "evoldo-v07-clean-room-kg",
            "license": "Apache-2.0", "entries": [
                {"id": ident, "title": title, "text": text, "tags": tags, "source_class": "clean_room_design_rule"}
                for ident, title, text, tags in entries
            ]}


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    ORACLES.mkdir(parents=True)
    contracts = [make_reasoning_task(spec) for spec in core_specs()]
    if len(contracts) != 27 or len({contract["task_id"] for contract in contracts}) != len(contracts):
        raise ValueError("v0.7 core must contain 27 uniquely identified tasks")
    rows = []
    for contract in contracts:
        root = TASKS / contract["task_id"]
        rows.append({key: contract[key] for key in ("task_id", "family_id", "suite", "level", "variant", "split")} | {
            "manifest_sha256": hashlib.sha256((root / "task.toml").read_bytes()).hexdigest(),
            "package_sha256": package_hash(root), "evaluation_role": contract["evaluation_role"],
            "deployment_tier": contract["deployment_tier"],
            "knowledge_effect_expectation": contract["knowledge_effect_expectation"],
        })
    write(OUT / "registry.jsonl", "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows))
    tier_counts = {tier: sum(row["deployment_tier"] == tier for row in rows) for tier in sorted({row["deployment_tier"] for row in rows})}
    suite_counts = {suite: sum(row["suite"] == suite for row in rows) for suite in sorted({row["suite"] for row in rows})}
    kg_expectation_counts = {
        value: sum(row["knowledge_effect_expectation"] == value for row in rows)
        for value in sorted({row["knowledge_effect_expectation"] for row in rows})
    }
    manifest = {"benchmark_version": VERSION, "task_count": len(rows), "pure_model_core": len(rows),
                "tier_counts": tier_counts, "suite_counts": suite_counts, "rollouts_per_model": 3,
                "knowledge_effect_expectation_counts": kg_expectation_counts,
                "required_treatments": ["direct_reasoning", "knowledge_assisted"],
                "web_search_policy": "forbidden_all_treatments",
                "task_ids_sha256": hashlib.sha256("\n".join(row["task_id"] for row in rows).encode()).hexdigest()}
    dump(OUT / "manifest.json", manifest)
    dump(KNOWLEDGE / "ldo_kg_v1.json", knowledge_corpus())
    dump(OUT / "public_pdk_manifest.json", {
        "provider": "sky130", "repository": "https://github.com/opensource-analog-circuits/sky130_pdk",
        "revision": "e8308aa273c1a6737a5dee89178c4d48270ff87e", "simulator": "ngspice",
        "model_entry": "libs.tech/ngspice/sky130.lib.spice",
        "model_entry_sha256": "5efa041a988893c1a3580d0ecd57870ea3146b27741c7d42b56baaa336b9549e",
        "validated_version": "46"
    })
    write(OUT / "README.md", """# EvoLDO v0.7 task store

This directory is generated by `python3 tools/generate_v07_tasks.py`. It contains structured,
workflow-level pure-model cases in the Analog Arena demo-task layout. Every task is eligible for an
identical direct/KG-on paired evaluation and forbids web search. Private calibration outputs do not
belong in this directory. See `docs/BENCHMARK_V07.md`.
""")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
