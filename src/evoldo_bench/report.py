from __future__ import annotations

from pathlib import Path
from typing import Any, Dict


def render_markdown(report: Dict[str, Any]) -> str:
    lines = [
        "# EvoLDO-Bench scorecard",
        "",
        "- Mode: `%s`" % report.get("mode", "unspecified"),
        "- Tasks: %s" % report.get("task_count", 0),
        "- Families: %s" % report.get("family_count", 0),
        "- Family-macro score: **%.2f**" % float(report.get("family_macro_score", 0.0)),
        "- Task pass rate: **%.1f%%**" % (100.0 * float(report.get("task_pass_rate", 0.0))),
    ]
    if "pass_at_1" in report:
        interval = report.get("pass_at_1_ci95", [0.0, 0.0])
        effort = report.get("effort", {})
        lines.extend([
            "- Pass@1: **%.1f%%** (95%% CI %.1f%%–%.1f%%)" % (100.0 * report["pass_at_1"], 100.0 * interval[0], 100.0 * interval[1]),
            "- Spec score: **%.1f%%**" % (100.0 * report.get("spec_score", 0.0)),
            "- Average effort: %.1f steps, %.1f tool calls, %.1f min, $%.2f" % (
                effort.get("avg_steps", 0.0), effort.get("avg_tool_calls", 0.0),
                effort.get("avg_wall_seconds", 0.0) / 60.0, effort.get("avg_total_cost_usd", 0.0),
            ),
        ])
    lines.extend([
        "",
        "## Capability suites",
        "",
        "| Suite | Count | Mean | Stddev | Min | Max |",
        "|---|---:|---:|---:|---:|---:|",
    ])
    for suite, values in sorted(report.get("by_suite", {}).items()):
        lines.append(
            "| %s | %d | %.2f | %.2f | %.2f | %.2f |"
            % (suite, values["count"], values["mean"], values["stddev"], values["min"], values["max"])
        )
    lines.extend(["", "## Levels", "", "| Level | Count | Mean |", "|---|---:|---:|"])
    for level, values in sorted(report.get("by_level", {}).items()):
        lines.append("| %s | %d | %.2f |" % (level, values["count"], values["mean"]))
    lines.extend(["", "## Interpretation", "", "Scores are deterministic and family-macro averaged. Public dev tasks are not a sealed exam.", ""])
    return "\n".join(lines)


def write_markdown(path: Path, report: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_markdown(report), encoding="utf-8")
