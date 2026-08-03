from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional

from .contracts import Task, validate_probe_contract

REGIME_MEASUREMENT_HINTS = {
    "op": ("voltage", "current", "region", "gm", "gds", "vgs", "vds", "vbs"),
    "dc": ("voltage", "current", "dropout", "line", "load", "sweep"),
    "ac": ("gain", "phase", "impedance", "psrr", "frequency"),
    "stb": ("loop", "margin", "ugf", "gain", "phase"),
    "noise": ("noise", "density", "rms", "integrated"),
    "tran": ("settling", "overshoot", "undershoot", "slew", "envelope", "time"),
    "startup": ("startup", "escape", "restart", "time", "voltage"),
}


def _flatten_keys(value: Any, prefix: str = "") -> List[str]:
    keys: List[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            dotted = "%s.%s" % (prefix, key) if prefix else str(key)
            keys.append(dotted.lower())
            keys.extend(_flatten_keys(item, dotted))
    elif isinstance(value, list):
        for item in value:
            keys.extend(_flatten_keys(item, prefix))
    return keys


def evaluate_probe_contract(
    probe: Dict[str, Any],
    task: Optional[Task] = None,
    available_artifacts: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """Validate syntax and conservative anti-confounding/tool-policy rules.

    The semantic gate intentionally errs on the side of asking for a better probe. It never decides
    circuit performance; it only decides whether the proposed evidence can answer the stated question.
    """
    validate_probe_contract(probe)
    violations: List[Dict[str, str]] = []
    if task is not None:
        if probe["task_id"] != task.task_id:
            violations.append({"code": "TASK_MISMATCH", "detail": "probe task_id does not match runtime task"})
        if int(task.data["budget"]["max_tool_calls"]) <= 0:
            violations.append({"code": "TOOL_NOT_ALLOWED", "detail": "task budget permits no tool calls"})
        policy = task.data.get("probe_policy", {})
        allowed_regimes = policy.get("allowed_regimes", [])
        if allowed_regimes and probe["analysis_regime"] not in allowed_regimes:
            violations.append({"code": "WRONG_REGIME", "detail": "analysis regime is outside task probe policy"})
        allowed_families = policy.get("allowed_probe_families", [])
        if allowed_families and probe["probe_family"] not in allowed_families:
            violations.append({"code": "UNRELATED_PROBE", "detail": "probe family is outside task probe policy"})
        required_held = set(policy.get("required_held_fixed", []))
        missing_held = sorted(required_held.difference(probe["held_fixed"]))
        if missing_held:
            violations.append({"code": "HELD_FIXED_MISSING", "detail": ", ".join(missing_held)})

    intervention_keys = {key.split(".")[-1] for key in _flatten_keys(probe["intervention"])}
    held = {str(item).lower() for item in probe["held_fixed"]}
    overlap = sorted(intervention_keys.intersection(held))
    if overlap:
        violations.append({"code": "CONFOUNDED_INTERVENTION", "detail": "also declared held fixed: %s" % ", ".join(overlap)})
    if probe["probe_family"] == "three_point_trend":
        swept = [key for key, value in probe["intervention"].items() if isinstance(value, list) and len(value) >= 2]
        if len(swept) != 1:
            violations.append({"code": "CONFOUNDED_INTERVENTION", "detail": "three_point_trend requires exactly one swept variable"})

    measurement_text = " ".join(_flatten_keys(probe["measurement"])).lower()
    hints = REGIME_MEASUREMENT_HINTS[probe["analysis_regime"]]
    if not any(hint in measurement_text for hint in hints):
        violations.append({"code": "MEASUREMENT_REGIME_MISMATCH", "detail": "measurement does not name an observable for the selected regime"})

    requested = probe.get("source_artifacts", [])
    if requested:
        available = set(available_artifacts or [])
        invented = sorted(set(requested).difference(available))
        if invented:
            violations.append({"code": "INVENTED_ARTIFACT", "detail": ", ".join(invented)})

    return {
        "schema_version": "1.0",
        "task_id": probe["task_id"],
        "passed": not violations,
        "violations": violations,
        "normalized": {
            "analysis_regime": probe["analysis_regime"],
            "probe_family": probe["probe_family"],
            "held_fixed": sorted(probe["held_fixed"]),
        },
    }
