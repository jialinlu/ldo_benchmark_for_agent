#!/usr/bin/env python3
"""Merge disjoint EvoLDO experiment shards without copying rollout artifacts."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

from evoldo_bench.errors import ContractError
from evoldo_bench.utils import dump_json, sha256_file, utc_timestamp


IDENTITY_FIELDS = (
    "schema_version", "model_id", "mode", "rollouts_per_task", "base_seed",
    "seed_semantics", "pairing_modes",
)


def merge_shards(output_root: Path, shard_roots: Iterable[Path]) -> Dict[str, Any]:
    output_root = output_root.resolve()
    manifests: List[tuple[Path, Path, Dict[str, Any]]] = []
    for shard_root in shard_roots:
        root = shard_root.resolve()
        try:
            relative = root.relative_to(output_root)
        except ValueError as exc:
            raise ContractError("every shard must be inside the merged output root") from exc
        path = root / "experiment_manifest.json"
        if not path.is_file():
            raise ContractError("shard manifest is missing: %s" % path)
        manifests.append((root, relative, json.loads(path.read_text(encoding="utf-8"))))
    if not manifests:
        raise ContractError("at least one shard is required")

    baseline = manifests[0][2]
    for _root, _relative, manifest in manifests[1:]:
        for field in IDENTITY_FIELDS:
            if manifest.get(field) != baseline.get(field):
                raise ContractError("shard %s mismatch" % field)
        if manifest.get("context_snapshot") != baseline.get("context_snapshot"):
            raise ContractError("shard context snapshot mismatch")

    rows = []
    seen = set()
    shard_records = []
    for root, relative, manifest in manifests:
        for original in manifest.get("rows", []):
            row = dict(original)
            key = (row.get("task_id"), row.get("rollout"), row.get("seed"))
            if key in seen:
                raise ContractError("duplicate rollout across shards: %r" % (key,))
            seen.add(key)
            for field in ("telemetry_file", "score_file"):
                if row.get(field):
                    artifact = (root / row[field]).resolve()
                    try:
                        artifact.relative_to(root)
                    except ValueError as exc:
                        raise ContractError("shard artifact escapes its root") from exc
                    if not artifact.is_file():
                        raise ContractError("shard artifact is missing: %s" % artifact)
                    row[field] = (relative / row[field]).as_posix()
            rows.append(row)
        shard_records.append({
            "path": relative.as_posix(),
            "manifest_sha256": sha256_file(root / "experiment_manifest.json"),
            "task_count": manifest.get("task_count"),
            "run_count": manifest.get("run_count"),
        })

    rows.sort(key=lambda row: (str(row["task_id"]), int(row["rollout"]), int(row["seed"])))
    expected_rollouts = int(baseline["rollouts_per_task"])
    task_ids = {str(row["task_id"]) for row in rows}
    if len(rows) != len(task_ids) * expected_rollouts:
        raise ContractError("merged rollout matrix is incomplete")

    merged = {field: baseline[field] for field in IDENTITY_FIELDS}
    merged.update({
        "created_at": utc_timestamp(),
        "task_count": len(task_ids),
        "run_count": len(rows),
        "context_snapshot": baseline["context_snapshot"],
        "merge": {"shard_count": len(manifests), "shards": shard_records},
        "rows": rows,
    })
    dump_json(output_root / "experiment_manifest.json", merged)
    return merged


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("shards", type=Path, nargs="+")
    args = parser.parse_args()
    merged = merge_shards(args.output, args.shards)
    print(json.dumps({
        "output": str(args.output / "experiment_manifest.json"),
        "shards": merged["merge"]["shard_count"],
        "tasks": merged["task_count"],
        "runs": merged["run_count"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
