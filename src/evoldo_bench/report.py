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
        token_efficiency = report.get("token_efficiency", {})
        avg_cost = effort.get("avg_total_cost_usd")
        avg_output = effort.get("avg_output_tokens")
        lines.extend([
            "- Pass@1: **%.1f%%** (95%% CI %.1f%%–%.1f%%)" % (100.0 * report["pass_at_1"], 100.0 * interval[0], 100.0 * interval[1]),
            "- Spec score: **%.1f%%**" % (100.0 * report.get("spec_score", 0.0)),
            "- Average effort: %.1f steps, %.1f tool calls, %.1f min, %s" % (
                effort.get("avg_steps", 0.0), effort.get("avg_tool_calls", 0.0),
                effort.get("avg_wall_seconds", 0.0) / 60.0,
                "$%.2f" % avg_cost if avg_cost is not None else "cost unavailable",
            ),
            "- Token measurement: %d measured, %d partial, %d unavailable; average generated tokens: %s" % (
                effort.get("token_measurement", {}).get("measured_rollouts", 0),
                effort.get("token_measurement", {}).get("partial_rollouts", 0),
                effort.get("token_measurement", {}).get("unavailable_rollouts", 0),
                "%.1f" % avg_output if avg_output is not None else "unavailable",
            ),
            "- Tokens per score point: %s" % (
                "%.2f" % token_efficiency["tokens_per_score_point"]
                if token_efficiency.get("tokens_per_score_point") is not None else "unavailable"
            ),
        ])
        operational = report.get("operational_effort_all_attempts")
        if operational:
            lines.extend([
                "- Operational attempts: %d (%d infrastructure attempts); total observed tokens: %.0f; total observed cost: %s" % (
                    report.get("operational_attempt_count", 0),
                    report.get("infrastructure_attempt_count", 0),
                    operational.get("total_observed_tokens", 0.0),
                    "$%.2f" % operational["total_observed_cost_usd"]
                    if operational.get("total_observed_cost_usd") is not None else "unavailable",
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
