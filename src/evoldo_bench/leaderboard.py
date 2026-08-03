from __future__ import annotations

import csv
import html
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping

from .utils import dump_json, utc_timestamp


def _entry(report: Mapping[str, Any]) -> Dict[str, Any]:
    effort = report.get("effort", {})
    ci = report.get("pass_at_1_ci95", [0.0, 0.0])
    return {
        "model_id": str(report.get("model_id", "unknown")),
        "mode": str(report.get("mode", "unspecified")),
        "pass_at_1": float(report.get("pass_at_1", report.get("task_pass_rate", 0.0))),
        "ci95_low": float(ci[0]),
        "ci95_high": float(ci[1]),
        "spec_score": float(report.get("spec_score", float(report.get("family_macro_score", 0.0)) / 100.0)),
        "family_macro_score": float(report.get("family_macro_score", 0.0)),
        "avg_output_tokens": float(effort.get("avg_output_tokens", 0.0)),
        "avg_steps": float(effort.get("avg_steps", 0.0)),
        "avg_tool_calls": float(effort.get("avg_tool_calls", 0.0)),
        "avg_wall_seconds": float(effort.get("avg_wall_seconds", 0.0)),
        "avg_cost_usd": float(effort.get("avg_total_cost_usd", 0.0)),
        "rollouts": int(report.get("rollout_count", effort.get("rollouts", 0))),
    }


def _pareto(entries: List[Dict[str, Any]], effort_key: str = "avg_cost_usd") -> None:
    for candidate in entries:
        candidate["pareto"] = not any(
            other is not candidate
            and other["spec_score"] >= candidate["spec_score"]
            and other[effort_key] <= candidate[effort_key]
            and (other["spec_score"] > candidate["spec_score"] or other[effort_key] < candidate[effort_key])
            for other in entries
        )


def build_leaderboard(reports: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    entries = [_entry(report) for report in reports]
    _pareto(entries)
    entries.sort(key=lambda row: (-row["pass_at_1"], -row["spec_score"], row["avg_cost_usd"], row["model_id"]))
    return {"schema_version": "1.0", "generated_at": utc_timestamp(), "entry_count": len(entries), "entries": entries}


def _render_svg(entries: List[Dict[str, Any]]) -> str:
    width, height, pad = 760, 360, 55
    max_effort = max([row["avg_cost_usd"] for row in entries] + [1.0])
    points = []
    for row in entries:
        x = pad + (width - 2 * pad) * row["avg_cost_usd"] / max_effort
        y = height - pad - (height - 2 * pad) * row["spec_score"]
        color = "#b91c1c" if row["pareto"] else "#64748b"
        label = html.escape(row["model_id"] + " / " + row["mode"])
        points.append('<circle cx="%.1f" cy="%.1f" r="6" fill="%s"><title>%s</title></circle>' % (x, y, color, label))
    return (
        '<svg role="img" aria-label="Spec score versus average cost; upper left is better" viewBox="0 0 %d %d">'
        '<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="#334155"/>'
        '<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="#334155"/>'
        '<text x="%d" y="%d">Average cost per rollout (USD)</text>'
        '<text x="8" y="20">Spec score</text>%s</svg>'
        % (width, height, pad, height-pad, width-pad, height-pad, pad, pad, pad, height-pad, width//2-80, height-10, "".join(points))
    )


def render_html(board: Mapping[str, Any]) -> str:
    entries = list(board["entries"])
    rows = []
    for index, row in enumerate(entries, 1):
        rows.append(
            "<tr><td>%d</td><td>%s</td><td>%s</td><td>%.1f%%</td><td>%.1f%%–%.1f%%</td>"
            "<td>%.1f%%</td><td>%.2f</td><td>%.0f</td><td>%.1f</td><td>%.1f</td><td>%s</td></tr>"
            % (
                index, html.escape(row["model_id"]), html.escape(row["mode"]), 100*row["pass_at_1"],
                100*row["ci95_low"], 100*row["ci95_high"], 100*row["spec_score"], row["avg_cost_usd"],
                row["avg_output_tokens"], row["avg_steps"], row["avg_wall_seconds"]/60.0,
                "yes" if row["pareto"] else "no",
            )
        )
    template = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>EvoLDO-Bench results</title><style>
body{font-family:system-ui,sans-serif;max-width:1100px;margin:2rem auto;padding:0 1rem;color:#0f172a}table{border-collapse:collapse;width:100%;font-size:.9rem}th,td{border-bottom:1px solid #cbd5e1;padding:.55rem;text-align:right}th:nth-child(2),td:nth-child(2),th:nth-child(3),td:nth-child(3){text-align:left}svg{width:100%;height:auto;background:#f8fafc;border:1px solid #cbd5e1}.note{background:#fef2f2;border-left:5px solid #b91c1c;padding:.8rem}code{background:#f1f5f9;padding:.1rem .25rem}</style></head><body>
<h1>EvoLDO-Bench result explorer</h1><p class="note">Public development results are not sealed EvoLDO-Exam scores. Upper-left is better; the red points are cost/spec-score Pareto candidates.</p>
<h2>Score versus effort</h2>__SVG__<h2>Result table</h2><table><thead><tr><th>#</th><th>Model</th><th>Treatment</th><th>Pass@1</th><th>95% CI</th><th>Spec score</th><th>USD</th><th>Output tokens</th><th>Steps</th><th>Minutes</th><th>Pareto</th></tr></thead><tbody>__ROWS__</tbody></table>
<p>Generated from replayable JSON scorecards. Capability vectors remain in the source reports and should accompany this summary.</p></body></html>"""
    return template.replace("__SVG__", _render_svg(entries)).replace("__ROWS__", "".join(rows))


def write_leaderboard(output_dir: Path, reports: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    board = build_leaderboard(reports)
    dump_json(output_dir / "leaderboard.json", board)
    (output_dir / "index.html").write_text(render_html(board), encoding="utf-8")
    fieldnames = list(board["entries"][0]) if board["entries"] else ["model_id", "mode"]
    with (output_dir / "leaderboard.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(board["entries"])
    return board
