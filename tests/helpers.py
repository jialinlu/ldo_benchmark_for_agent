from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from evoldo_bench.utils import load_json


def reference_answer(task_dir: Path, oracle_path: Path) -> Dict[str, Any]:
    answer = load_json(task_dir / "answer_template.json")
    oracle = load_json(oracle_path)
    for check in oracle["checks"]:
        path = check["path"]
        if "." in path:
            continue
        if check["kind"] in {"exact", "boolean", "numeric_close"}:
            answer[path] = check["expected"]
        elif check["kind"] in {"set_contains", "set_equals"}:
            answer[path] = list(check["expected"])
        elif check["kind"] == "nonempty" and not answer.get(path):
            answer[path] = "present"
    answer["mechanism"] = "Reference development explanation based only on supplied evidence."
    answer["claim_boundary"] = "Limited to the supplied operating regime and held-fixed conditions."
    answer["confidence"] = 0.95
    return answer
