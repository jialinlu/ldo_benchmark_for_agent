#!/usr/bin/env python3
"""Write a schema-valid but intentionally non-expert answer.

This verifies runner integration only. It is not a benchmark solver and its score has no capability value.
"""
import json
import os
from pathlib import Path

root = Path(os.environ["EVOLDO_TASK_DIR"])
answer = json.loads((root / "answer_template.json").read_text(encoding="utf-8"))
case = json.loads((root / "inputs" / "case.json").read_text(encoding="utf-8"))
vocabulary = case["controlled_vocabulary"]
answer.update(
    {
        "conclusion": "insufficient_evidence",
        "analysis_regime": vocabulary["analysis_regime"][0],
        "mechanism": "This smoke agent does not perform analog reasoning.",
        "claim_boundary": "Runner integration only; not a capability claim.",
        "confidence": 0.0,
    }
)
Path(os.environ["EVOLDO_ANSWER_PATH"]).write_text(
    json.dumps(answer, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
