#!/usr/bin/env python3
"""Uniform direct-reasoning adapter for Codex, Kimi Code, and Claude Code.

The adapter serializes only files declared by the task manifest into one prompt, starts a new
non-persistent CLI session, writes ``answer.json``, and records telemetry/outcome on every exit path.
It is intended to run inside the per-rollout sandbox created by the evaluation orchestrator.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


TOKEN_FIELDS = ("input", "cached_input", "output", "reasoning", "cache_write")
COST_FIELDS = TOKEN_FIELDS


def _nullable(fields: Iterable[str]) -> Dict[str, None]:
    return {field: None for field in fields}


def _prompt(task_dir: Path) -> str:
    task = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
    paths = [task["prompt_file"], task["answer_template_file"], *task["input_files"]]
    sections = [
        "Solve the following EvoLDO public-development task.",
        "Use only the supplied file contents. Do not access other paths, prior runs, solutions, tests, or oracles.",
        "Return exactly one JSON object matching answer_template.json, without Markdown fences or commentary.",
    ]
    for value in paths:
        relative = Path(value)
        path = (task_dir / relative).resolve()
        path.relative_to(task_dir.resolve())
        sections.extend(("", "===== %s =====" % relative.as_posix(), path.read_text(encoding="utf-8", errors="replace")))
    return "\n".join(sections)


def _extract_json(text: str) -> Dict[str, Any]:
    stripped = text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", stripped, re.I | re.S)
    if fenced:
        stripped = fenced.group(1)
    decoder = json.JSONDecoder()
    try:
        value, end = decoder.raw_decode(stripped)
    except json.JSONDecodeError:
        value, end = None, 0
    if isinstance(value, dict) and not stripped[end:].strip():
        return value
    raise ValueError("model response does not contain exactly one JSON object")


def _run(command: List[str], cwd: Path, timeout: int) -> Tuple[int, str, str, bool, float]:
    started = time.monotonic()
    process = subprocess.Popen(
        command,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    timed_out = False
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        os.killpg(process.pid, signal.SIGINT)
        try:
            stdout, stderr = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            stdout, stderr = process.communicate()
    return process.returncode or 0, stdout, stderr, timed_out, time.monotonic() - started


def _codex(command_output: str) -> Tuple[str, Dict[str, Any], Optional[str]]:
    final = ""
    usage: Dict[str, Any] = {}
    thread_id = None
    for line in command_output.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "thread.started":
            thread_id = event.get("thread_id")
        item = event.get("item", {})
        if event.get("type") == "item.completed" and item.get("type") == "agent_message":
            final = str(item.get("text", ""))
        if event.get("type") == "turn.completed" and isinstance(event.get("usage"), dict):
            usage = event["usage"]
    return final, usage, thread_id


def _find_kimi_usage(session_id: Optional[str]) -> Tuple[Dict[str, Any], Optional[str]]:
    if not session_id:
        return {}, None
    roots = list((Path.home() / ".kimi-code" / "sessions").glob("**/%s" % session_id))
    if len(roots) != 1:
        return {}, None
    wire = roots[0] / "agents" / "main" / "wire.jsonl"
    totals: Dict[str, float] = {}
    reported_model = None
    if wire.is_file():
        for line in wire.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "llm.request":
                reported_model = event.get("modelAlias") or event.get("model")
            if event.get("type") == "usage.record" and event.get("usageScope") == "turn":
                for key, value in event.get("usage", {}).items():
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        totals[key] = totals.get(key, 0.0) + float(value)
    return totals, reported_model


def _kimi(command_output: str) -> Tuple[str, Dict[str, Any], Optional[str]]:
    final = ""
    session_id = None
    for line in command_output.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("role") == "assistant" and isinstance(event.get("content"), str):
            final = event["content"]
        if event.get("type") == "session.resume_hint":
            session_id = event.get("session_id")
    usage, reported_model = _find_kimi_usage(session_id)
    return final, usage, reported_model


def _claude(command_output: str) -> Tuple[str, Dict[str, Any], Optional[str]]:
    try:
        result = json.loads(command_output)
    except json.JSONDecodeError:
        return "", {}, None
    model_usage = result.get("modelUsage", {}) if isinstance(result, dict) else {}
    reported = None
    if isinstance(model_usage, dict) and model_usage:
        reported = ",".join(sorted(model_usage))
    return str(result.get("result", "")), result, reported


def _telemetry_base(model: str, wall: float) -> Dict[str, Any]:
    return {
        "schema_version": "1.0",
        "task_id": os.environ.get("EVOLDO_TASK_ID", "unknown"),
        "model_id": model,
        "mode": os.environ.get("EVOLDO_MODE", "direct_reasoning"),
        "rollout": int(os.environ.get("EVOLDO_ROLLOUT", "0")),
        "seed": int(os.environ.get("EVOLDO_SEED", "0")),
        "steps": 1,
        "tool_calls": 0,
        "wall_seconds": round(wall, 6),
        "token_breakdown": _nullable(TOKEN_FIELDS),
        "cost_breakdown_usd": _nullable(COST_FIELDS),
        "token_measurement_status": "unavailable",
        "cost_measurement_status": "unavailable",
        "provider_reported_model_id": None,
        "model_identity_status": "unavailable",
        "provider_total_cost_usd": None,
        "infra_status": "not_used",
    }


def _normalize_codex(model: str, raw: Dict[str, Any], telemetry: Dict[str, Any]) -> None:
    if not raw:
        return
    input_total = raw.get("input_tokens")
    cached = raw.get("cached_input_tokens", 0)
    output_total = raw.get("output_tokens")
    reasoning = raw.get("reasoning_output_tokens", 0)
    cache_write = raw.get("cache_write_input_tokens", 0)
    telemetry["token_breakdown"] = {
        "input": max(float(input_total) - float(cached), 0.0) if input_total is not None else None,
        "cached_input": float(cached),
        "output": max(float(output_total) - float(reasoning), 0.0) if output_total is not None else None,
        "reasoning": float(reasoning),
        "cache_write": float(cache_write),
    }
    telemetry["token_measurement_status"] = "measured"
    telemetry["provider_reported_model_id"] = model
    telemetry["model_identity_status"] = "requested_only"
    telemetry["provider_usage_raw"] = raw


def _normalize_kimi(model: str, raw: Dict[str, Any], reported: Optional[str], telemetry: Dict[str, Any]) -> None:
    if raw:
        telemetry["token_breakdown"] = {
            "input": raw.get("inputOther"),
            "cached_input": raw.get("inputCacheRead"),
            "output": raw.get("output"),
            "reasoning": None,
            "cache_write": raw.get("inputCacheCreation"),
        }
        telemetry["token_measurement_status"] = "partial"
        telemetry["provider_usage_raw"] = raw
    telemetry["provider_reported_model_id"] = reported
    if reported:
        telemetry["model_identity_status"] = "requested_only" if reported == model else "mismatch"


def _normalize_claude(model: str, raw: Dict[str, Any], reported: Optional[str], telemetry: Dict[str, Any]) -> None:
    model_usage = raw.get("modelUsage", {}) if isinstance(raw, dict) else {}
    if isinstance(model_usage, dict) and model_usage:
        totals = {key: 0.0 for key in ("inputTokens", "cacheReadInputTokens", "cacheCreationInputTokens", "outputTokens")}
        for usage in model_usage.values():
            if isinstance(usage, dict):
                for key in totals:
                    totals[key] += float(usage.get(key, 0) or 0)
        telemetry["token_breakdown"] = {
            "input": totals["inputTokens"],
            "cached_input": totals["cacheReadInputTokens"],
            "output": totals["outputTokens"],
            "reasoning": None,
            "cache_write": totals["cacheCreationInputTokens"],
        }
        telemetry["token_measurement_status"] = "partial"
    telemetry["provider_reported_model_id"] = reported
    if reported:
        telemetry["model_identity_status"] = "attested" if model in reported.split(",") else "mismatch"
    cost = raw.get("total_cost_usd") if isinstance(raw, dict) else None
    telemetry["provider_total_cost_usd"] = float(cost) if isinstance(cost, (int, float)) else None
    if telemetry["provider_total_cost_usd"] is not None:
        telemetry["cost_measurement_status"] = "partial"
    telemetry["provider_usage_raw"] = {
        "usage": raw.get("usage", {}), "modelUsage": model_usage,
        "terminal_reason": raw.get("terminal_reason"), "api_error_status": raw.get("api_error_status"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent", choices=("codex", "kimi", "claude"), required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--claude-settings")
    parser.add_argument("--timeout", type=int, default=None)
    args = parser.parse_args()

    task_dir = Path(os.environ["EVOLDO_TASK_DIR"]).resolve()
    prompt = _prompt(task_dir)
    timeout = args.timeout or max(1, int(os.environ.get("EVOLDO_TIMEOUT_SECONDS", "300")) - 15)
    with tempfile.TemporaryDirectory(prefix="evoldo-adapter-") as temporary:
        if args.agent == "codex":
            command = [
                "codex", "exec", "--ephemeral", "--skip-git-repo-check", "--ignore-user-config",
                "--ignore-rules", "-c", 'approval_policy="never"', "-s", "read-only",
                "-m", args.model, "--json", prompt,
            ]
        elif args.agent == "kimi":
            command = [
                "kimi", "-m", args.model, "--skills-dir", temporary,
                "-p", prompt, "--output-format", "stream-json",
            ]
        else:
            command = [
                "claude", "-p", "--model", args.model, "--effort", "medium", "--safe-mode",
                "--tools", "", "--no-session-persistence", "--prompt-suggestions", "false",
                "--output-format", "json",
            ]
            if args.claude_settings:
                command.extend(("--settings", args.claude_settings))
            command.append(prompt)
        return_code, stdout, stderr, timed_out, wall = _run(command, task_dir, timeout)

    sys.stdout.write(stdout)
    sys.stderr.write(stderr)
    telemetry = _telemetry_base(args.model, wall)
    if args.agent == "codex":
        final, raw, _thread = _codex(stdout)
        _normalize_codex(args.model, raw, telemetry)
    elif args.agent == "kimi":
        final, raw, reported = _kimi(stdout)
        _normalize_kimi(args.model, raw, reported, telemetry)
    else:
        final, raw, reported = _claude(stdout)
        _normalize_claude(args.model, raw, reported, telemetry)

    status = "ok"
    reason = None
    if timed_out:
        status, reason = "provider_timeout", "adapter inner timeout"
        telemetry["infra_status"] = "infra_fail"
    elif return_code != 0 or (isinstance(raw, dict) and raw.get("is_error")):
        status, reason = "provider_infra_fail", "provider CLI returned an error"
        telemetry["infra_status"] = "infra_fail"
    else:
        try:
            answer = _extract_json(final)
        except ValueError as exc:
            lower = final.lower()
            status = "model_incomplete" if any(value in lower for value in ("cannot", "unable", "无法", "不能完成")) else "format_fail"
            reason = str(exc)
        else:
            Path(os.environ["EVOLDO_ANSWER_PATH"]).write_text(json.dumps(answer, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            telemetry["infra_status"] = "ok"

    Path(os.environ["EVOLDO_TELEMETRY_PATH"]).write_text(json.dumps(telemetry, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    outcome_path = Path(os.environ.get("EVOLDO_OUTCOME_PATH", task_dir / "outcome.json"))
    outcome_path.write_text(json.dumps({
        "schema_version": "1.0", "status": status, "reason": reason,
        "provider_return_code": return_code, "timed_out": timed_out,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0 if status == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
