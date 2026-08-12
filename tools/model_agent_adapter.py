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
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


TOKEN_FIELDS = ("input", "cached_input", "output", "reasoning", "cache_write")
COST_FIELDS = TOKEN_FIELDS
NODE_IMAGE = "node@sha256:b21fe589dfbe5cc39365d0544b9be3f1f33f55f3c86c87a76ff65a02f8f5848e"
CLAUDE_IMAGE = "debian@sha256:7b140f374b289a7c2befc338f42ebe6441b7ea838a042bbd5acbfca6ec875818"


def _nullable(fields: Iterable[str]) -> Dict[str, None]:
    return {field: None for field in fields}


def _prompt(task_dir: Path) -> str:
    manifest = task_dir / "task.json"
    if not manifest.is_file():
        manifest = task_dir / "task_contract.json"
    task = json.loads(manifest.read_text(encoding="utf-8"))
    paths = [task["prompt_file"], task["answer_template_file"], *task["input_files"]]
    paths = list(dict.fromkeys(paths))
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


def _find_kimi_usage(session_id: Optional[str], home: Optional[Path] = None) -> Tuple[Dict[str, Any], Optional[str]]:
    if not session_id:
        return {}, None
    roots = list(((home or Path.home()) / ".kimi-code" / "sessions").glob("**/%s" % session_id))
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


def _kimi(command_output: str, home: Optional[Path] = None) -> Tuple[str, Dict[str, Any], Optional[str]]:
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
    usage, reported_model = _find_kimi_usage(session_id, home=home)
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


def _openai_compatible(command_output: str) -> Tuple[str, Dict[str, Any], Optional[str]]:
    try:
        result = json.loads(command_output)
    except json.JSONDecodeError:
        return "", {}, None
    choices = result.get("choices", []) if isinstance(result, dict) else []
    message = choices[0].get("message", {}) if choices and isinstance(choices[0], dict) else {}
    return str(message.get("content", "")), result, result.get("model")


def _run_openai_compatible(
    prompt: str,
    model: str,
    base_url: str,
    credential_value: str,
    timeout: int,
) -> Tuple[int, str, str, bool, float]:
    """Call an OpenAI-compatible endpoint without placing the credential in argv."""
    started = time.monotonic()
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Return exactly one JSON object and no commentary."},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": 4096,
        "temperature": 0.0,
        "response_format": {"type": "json_object"},
    }
    request = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": "Bearer " + credential_value, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            stdout = response.read().decode("utf-8", errors="replace")
        return 0, stdout, "", False, time.monotonic() - started
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[-2000:]
        return int(exc.code), "", "OpenAI-compatible HTTP %s: %s" % (exc.code, body), False, time.monotonic() - started
    except TimeoutError:
        return 1, "", "OpenAI-compatible request timed out", True, time.monotonic() - started
    except (urllib.error.URLError, OSError) as exc:
        return 1, "", "OpenAI-compatible transport error: %s" % exc, False, time.monotonic() - started


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


def _copy_required(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError("required runtime credential is unavailable: %s" % source.name)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _docker_base(task_dir: Path) -> List[str]:
    return [
        "docker", "run", "--rm", "--read-only", "--network", "bridge",
        "--cpus", "1", "--memory", "2g", "--pids-limit", "256",
        "--user", "%d:%d" % (os.getuid(), os.getgid()),
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--tmpfs", "/tmp:rw,noexec,nosuid,size=268435456",
        "--mount", "type=bind,src=%s,dst=/task,readonly" % task_dir,
        "--mount", "type=bind,src=/etc/ssl/certs,dst=/etc/ssl/certs,readonly",
        "--workdir", "/task",
    ]


def _container_command(
    agent: str,
    model: str,
    prompt: str,
    task_dir: Path,
    temporary: Path,
    claude_settings: Optional[str],
) -> Tuple[List[str], Optional[Path], str]:
    base = _docker_base(task_dir)
    if agent == "codex":
        executable = shutil.which("codex")
        if not executable:
            raise FileNotFoundError("codex executable is unavailable")
        script = Path(executable).resolve()
        runtime = script.parents[3]
        state = temporary / "codex-state"
        _copy_required(Path.home() / ".codex" / "auth.json", state / "auth.json")
        command = base + [
            "--mount", "type=bind,src=%s,dst=/opt/node_modules,readonly" % runtime,
            "--mount", "type=bind,src=%s,dst=/state" % state,
            "--env", "CODEX_HOME=/state", NODE_IMAGE,
            "node", "/opt/node_modules/@openai/codex/bin/codex.js", "exec", "--ephemeral",
            "--skip-git-repo-check", "--ignore-user-config", "--ignore-rules",
            "-c", 'approval_policy="never"', "-s", "read-only", "-m", model, "--json", prompt,
        ]
        return command, None, NODE_IMAGE

    if agent == "kimi":
        executable = shutil.which("kimi")
        if not executable:
            raise FileNotFoundError("kimi executable is unavailable")
        script = Path(executable).resolve()
        runtime = script.parents[1]
        home = temporary / "kimi-home"
        source = Path.home() / ".kimi-code"
        _copy_required(source / "config.toml", home / ".kimi-code" / "config.toml")
        _copy_required(source / "credentials" / "kimi-code.json", home / ".kimi-code" / "credentials" / "kimi-code.json")
        _copy_required(source / "device_id", home / ".kimi-code" / "device_id")
        oauth = source / "oauth" / "kimi-code"
        if oauth.is_file():
            _copy_required(oauth, home / ".kimi-code" / "oauth" / "kimi-code")
        skills = temporary / "empty-skills"
        skills.mkdir()
        agent_file = temporary / "benchmark-direct.md"
        agent_file.write_text(
            "---\n"
            "name: benchmark-direct\n"
            "description: Answer one isolated benchmark task without tools.\n"
            "tools: []\n"
            "---\n"
            "Reason from the user-supplied task content only. Do not call tools. "
            "Return exactly the requested final JSON object without commentary or Markdown fences.\n",
            encoding="utf-8",
        )
        command = base + [
            "--mount", "type=bind,src=%s,dst=/opt/kimi,readonly" % runtime,
            "--mount", "type=bind,src=%s,dst=/state-home" % home,
            "--mount", "type=bind,src=%s,dst=/empty-skills,readonly" % skills,
            "--mount", "type=bind,src=%s,dst=/benchmark-direct.md,readonly" % agent_file,
            "--env", "HOME=/state-home", NODE_IMAGE,
            "node", "/opt/kimi/dist/main.mjs", "-m", model,
            "--skills-dir", "/empty-skills", "--agent-file", "/benchmark-direct.md",
            "-p", prompt, "--output-format", "stream-json",
        ]
        return command, home, NODE_IMAGE

    settings_value = claude_settings or os.environ.get("EVOLDO_CLAUDE_SETTINGS")
    if not settings_value:
        raise ValueError("containerized Claude requires --claude-settings or EVOLDO_CLAUDE_SETTINGS")
    executable = shutil.which("claude")
    if not executable:
        raise FileNotFoundError("claude executable is unavailable")
    state = temporary / "claude-state"
    _copy_required(Path(settings_value).expanduser().resolve(), state / "settings.json")
    (state / "home").mkdir()
    command = base + [
        "--mount", "type=bind,src=%s,dst=/opt/claude,readonly" % Path(executable).resolve(),
        "--mount", "type=bind,src=%s,dst=/state" % state,
        "--env", "HOME=/state/home", CLAUDE_IMAGE,
        "/opt/claude", "-p", "--model", model, "--effort", "medium", "--safe-mode",
        "--bare", "--disable-slash-commands", "--tools", "", "--no-session-persistence",
        "--prompt-suggestions", "false", "--output-format", "json",
        "--settings", "/state/settings.json", prompt,
    ]
    return command, None, CLAUDE_IMAGE


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


def _normalize_openai_compatible(
    model: str,
    raw: Dict[str, Any],
    reported: Optional[str],
    telemetry: Dict[str, Any],
) -> None:
    usage = raw.get("usage", {}) if isinstance(raw, dict) else {}
    if isinstance(usage, dict) and usage:
        prompt_total = usage.get("prompt_tokens")
        completion_total = usage.get("completion_tokens")
        prompt_details = usage.get("prompt_tokens_details", {}) or {}
        completion_details = usage.get("completion_tokens_details", {}) or {}
        cached = prompt_details.get("cached_tokens", 0)
        reasoning = completion_details.get("reasoning_tokens")
        telemetry["token_breakdown"] = {
            "input": max(float(prompt_total) - float(cached), 0.0) if prompt_total is not None else None,
            "cached_input": float(cached) if cached is not None else None,
            "output": (
                max(float(completion_total) - float(reasoning), 0.0)
                if completion_total is not None and reasoning is not None
                else float(completion_total) if completion_total is not None else None
            ),
            "reasoning": float(reasoning) if reasoning is not None else None,
            "cache_write": None,
        }
        # OpenAI-compatible responses do not expose cache-write accounting, so
        # even a reported reasoning-token field is still a partial measurement.
        telemetry["token_measurement_status"] = "partial"
        telemetry["provider_usage_raw"] = usage
    telemetry["provider_reported_model_id"] = reported
    if reported:
        telemetry["model_identity_status"] = "attested" if reported == model else "mismatch"
    telemetry["provider_response_id"] = raw.get("id") if isinstance(raw, dict) else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent", choices=("codex", "kimi", "claude", "openai-compatible"), required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--claude-settings")
    parser.add_argument("--base-url", default=os.environ.get("EVOLDO_OPENAI_BASE_URL", "https://api.siliconflow.cn/v1"))
    parser.add_argument("--api-key-env", default="EVOLDO_OPENAI_API_KEY")
    parser.add_argument("--containerized", action="store_true")
    parser.add_argument("--timeout", type=int, default=None)
    args = parser.parse_args()

    task_dir = Path(os.environ["EVOLDO_TASK_DIR"]).resolve()
    prompt = _prompt(task_dir)
    timeout = args.timeout or max(1, int(os.environ.get("EVOLDO_TIMEOUT_SECONDS", "300")) - 15)
    container_image = None
    with tempfile.TemporaryDirectory(prefix="evoldo-adapter-") as temporary_value:
        temporary = Path(temporary_value)
        kimi_home = None
        if args.agent == "openai-compatible":
            if args.containerized:
                raise ValueError("openai-compatible adapter does not use a provider CLI container")
            credential_value = os.environ.get(args.api_key_env)
            if not credential_value:
                raise ValueError("OpenAI-compatible credential environment variable is unavailable")
            return_code, stdout, stderr, timed_out, wall = _run_openai_compatible(
                prompt, args.model, args.base_url, credential_value, timeout
            )
            command = []
        elif args.containerized:
            command, kimi_home, container_image = _container_command(
                args.agent, args.model, prompt, task_dir, temporary, args.claude_settings
            )
        elif args.agent == "codex":
            command = [
                "codex", "exec", "--ephemeral", "--skip-git-repo-check", "--ignore-user-config",
                "--ignore-rules", "-c", 'approval_policy="never"', "-s", "read-only",
                "-m", args.model, "--json", prompt,
            ]
        elif args.agent == "kimi":
            command = [
                "kimi", "-m", args.model, "--skills-dir", str(temporary),
                "-p", prompt, "--output-format", "stream-json",
            ]
        else:
            command = [
                "claude", "-p", "--model", args.model, "--effort", "medium", "--safe-mode",
                "--tools", "", "--no-session-persistence", "--prompt-suggestions", "false",
                "--output-format", "json",
            ]
            settings_value = args.claude_settings or os.environ.get("EVOLDO_CLAUDE_SETTINGS")
            if settings_value:
                command.extend(("--settings", settings_value))
            command.append(prompt)
        if args.agent != "openai-compatible":
            return_code, stdout, stderr, timed_out, wall = _run(command, task_dir, timeout)
        telemetry = _telemetry_base(args.model, wall)
        if args.agent == "codex":
            final, raw, _thread = _codex(stdout)
            _normalize_codex(args.model, raw, telemetry)
        elif args.agent == "kimi":
            final, raw, reported = _kimi(stdout, home=kimi_home)
            _normalize_kimi(args.model, raw, reported, telemetry)
        elif args.agent == "claude":
            final, raw, reported = _claude(stdout)
            _normalize_claude(args.model, raw, reported, telemetry)
        else:
            final, raw, reported = _openai_compatible(stdout)
            _normalize_openai_compatible(args.model, raw, reported, telemetry)

    sys.stdout.write(stdout)
    sys.stderr.write(stderr)
    telemetry["execution_isolation"] = "docker_task_only" if args.containerized else "host_cli"
    telemetry["container_image"] = container_image

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

    observed_tokens = [value for key, value in telemetry["token_breakdown"].items()
                       if key != "cache_write" and isinstance(value, (int, float))]
    terminal_tokens = sum(observed_tokens) if observed_tokens else None
    terminal_status = {
        "ok": "completed", "model_incomplete": "model_incomplete", "format_fail": "format_fail",
        "provider_timeout": "infra_fail", "provider_infra_fail": "infra_fail",
    }[status]
    telemetry["milestones"] = {
        "first_feasible_seconds": round(wall, 6) if status == "ok" else None,
        "terminal_seconds": round(wall, 6),
        "first_feasible_tokens": terminal_tokens if status == "ok" else None,
        "terminal_tokens": terminal_tokens,
        "terminal_tokens_status": telemetry["token_measurement_status"],
        "terminal_status": terminal_status,
    }

    Path(os.environ["EVOLDO_TELEMETRY_PATH"]).write_text(json.dumps(telemetry, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    outcome_path = Path(os.environ.get("EVOLDO_OUTCOME_PATH", task_dir / "outcome.json"))
    outcome_path.write_text(json.dumps({
        "schema_version": "1.0", "status": status, "reason": reason,
        "provider_return_code": return_code, "timed_out": timed_out,
        "execution_isolation": telemetry["execution_isolation"],
        "container_image": container_image,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0 if status == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
