from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Dict, Iterable, List, Mapping

from .errors import ContractError
from .utils import relative_hashes, sha256_text, utc_timestamp

REQUIRED_GATES = (
    "operating_point",
    "startup",
    "shutdown_restart",
    "stability",
    "psrr",
    "noise",
    "load_transient",
    "pvt",
    "forbidden_devices",
)
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")


def build_candidate_manifest(candidate_root: Path, candidate_id: str, parent_id: str = "none") -> Dict[str, Any]:
    if not candidate_root.is_dir():
        raise ContractError("candidate root is not a directory")
    files = relative_hashes(candidate_root)
    digest = sha256_text("\n".join("%s:%s" % item for item in sorted(files.items())))
    return {
        "schema_version": "1.0",
        "candidate_id": candidate_id,
        "parent_id": parent_id,
        "created_at": utc_timestamp(),
        "candidate_digest": digest,
        "files": files,
    }


def qualify_candidate(candidate: Mapping[str, Any], evidence: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    candidate_digest = candidate.get("candidate_digest")
    if not isinstance(candidate_digest, str):
        raise ContractError("candidate manifest requires candidate_digest")
    by_gate: Dict[str, List[Mapping[str, Any]]] = {gate: [] for gate in REQUIRED_GATES}
    stale = []
    unknown = []
    for item in evidence:
        gate = item.get("gate")
        if gate not in by_gate:
            unknown.append(str(gate))
            continue
        if item.get("candidate_digest") != candidate_digest:
            stale.append(str(gate))
            continue
        by_gate[str(gate)].append(item)
    gates: Dict[str, Any] = {}
    for gate, rows in by_gate.items():
        fresh = [
            row for row in rows
            if row.get("status") in {"PASS", "FAIL"}
            and isinstance(row.get("evidence_sha256"), str)
            and SHA256_RE.fullmatch(str(row.get("evidence_sha256")))
        ]
        if not fresh:
            status = "MISSING"
        elif any(row.get("status") == "FAIL" for row in fresh):
            status = "FAIL"
        else:
            status = "PASS"
        gates[gate] = {"status": status, "fresh_evidence_count": len(fresh)}
    passed = all(item["status"] == "PASS" for item in gates.values()) and not stale and not unknown
    return {
        "schema_version": "1.0",
        "candidate_id": candidate.get("candidate_id"),
        "candidate_digest": candidate_digest,
        "qualified": passed,
        "promotion_status": "QUALIFIED" if passed else "BLOCKED",
        "gates": gates,
        "stale_evidence_gates": sorted(stale),
        "unknown_gates": sorted(unknown),
        "hard_rule": "only fresh evidence bound to this candidate can promote it",
    }


def summarize_qualification_attempts(attempts: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    rows = list(attempts)
    first_qualified = next((index + 1 for index, row in enumerate(rows) if bool(row.get("qualified"))), None)
    wall_seconds = sum(float(row.get("wall_seconds", 0.0)) for row in rows[:first_qualified] if first_qualified is not None)
    gate_totals = []
    for row in rows:
        gates = row.get("gates", {})
        if gates:
            gate_totals.append(sum(1 for value in gates.values() if value.get("status") == "PASS") / len(gates))
    return {
        "schema_version": "1.0",
        "candidate_evaluations": len(rows),
        "evaluations_to_first_qualification": first_qualified,
        "wall_seconds_to_first_qualification": round(wall_seconds, 6) if first_qualified is not None else None,
        "mean_gate_robustness": round(sum(gate_totals) / len(gate_totals), 6) if gate_totals else 0.0,
        "qualified_candidates": sum(1 for row in rows if bool(row.get("qualified"))),
    }
