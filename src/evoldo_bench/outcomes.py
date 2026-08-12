from __future__ import annotations

from typing import Any, Dict


INFRASTRUCTURE_STATUSES = frozenset({
    "controller_interrupted",
    "control_mismatch",
    "failed",
    "provider_infra_fail",
    "provider_timeout",
    "timeout",
    "model_identity_mismatch",
    "output_budget_exhausted",
})


def is_infrastructure_status(status: Any) -> bool:
    return str(status) in INFRASTRUCTURE_STATUSES


def classify_attempt(record: Dict[str, Any], telemetry: Dict[str, Any]) -> str:
    """Separate provider/runner/control failures from model-attributable outcomes."""
    if telemetry.get("model_identity_status") == "mismatch":
        return "infrastructure"
    adapter_status = (record.get("adapter_outcome") or {}).get("status")
    if adapter_status in {
        "provider_infra_fail", "provider_timeout", "output_budget_exhausted",
    }:
        return "infrastructure"
    if record.get("timed_out") is True:
        return "infrastructure"
    if is_infrastructure_status(record.get("status")):
        return "infrastructure"
    return "model"
