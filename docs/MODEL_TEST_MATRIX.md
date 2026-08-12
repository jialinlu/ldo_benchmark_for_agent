# Model test matrix

This document retains prior access provenance and the v0.7 calibration cohort. Access probes are
infrastructure checks, not benchmark scores. New runs use the 27-task pure-model matrix in
`BENCHMARK_V07.md`; prior v0.5/v0.6 entries remain historical evidence only.

The historical first run selected GPT-5.6-sol, Kimi K3, DeepSeek V4 Pro, and DeepSeek V4 Flash. Its pre-run policy
used base seed `20260810`, a 300-second timeout, three new sessions per task, and zero automatic retries.
After framework and gateway failures were diagnosed, the benchmark owner authorized the versioned recovery
policy below. This provenance is retained rather than rewriting the original policy. A model-attributable
failure remains in the score denominator as zero. A provider, gateway, runner, or model-identity failure is
retried with the same task, rollout, and seed until a model-attributable outcome is obtained. Every attempt
remains visible; successful retries do not erase the failed attempt's tokens, cost, or wall time. Retries
are scheduled round-robin, one attempt per unresolved row per pass, so one persistently unhealthy task
cannot consume its full retry allowance before other rows are attempted.

## Core cohort

| Agent | Model | Status | Formal runs |
|---|---|---|---:|
| Codex 0.146.0 | GPT-5.6-sol | Ready | v0.6: 69 tasks × three independent rollouts |
| Kimi Code 0.34.0 | K3 | Ready | Same matrix |
| Claude Code 2.1.223 | Claude Fable 5 | Blocked: provider returned 503 before inference | Start only after a fresh access qualification |
| Claude Code 2.1.223 | Claude Opus 5 | Blocked: provider returned 503 before inference | Start only after a fresh access qualification |
| Claude Code 2.1.223 | DeepSeek V4 Pro | Ready through the separately selected DeepSeek profile | Same matrix |

Supplemental candidates are DeepSeek V4 Flash and DeepSeek Reasoner. Both completed access probes. The Reasoner probe also reported an auxiliary Flash usage entry, so the formal adapter must disable prompt suggestions and sum every provider-reported model usage entry. Claude Opus 4.6 and Sonnet 4.6 are discovered but are not currently scheduled.

## v0.7 discrimination cohort

The one-rollout development calibration uses DeepSeek V4 Flash and MiniMax M2.5 across families, plus
Qwen3.5 4B/9B/27B/35B-A3B/122B-A10B/397B-A17B for the within-family deployment curve. This calibration
is not a formal leaderboard: the release policy still requires three independent sessions and seeds per
task/treatment. Model names, provider-reported identity, temperature, reasoning/thinking configuration,
output ceiling, token accounting status, and no-Web policy are recorded for every rollout.

The machine-readable inventory is [`benchmarks/model_matrix.json`](../benchmarks/model_matrix.json). It deliberately contains no credentials, credential paths, or private configuration values.

## Token policy

Every scheduled attempt retains provider-reported input, cache-read, cache-write, output, reasoning, cost, and wall time when available. This includes valid answers, model-declared inability, refusal, malformed output, timeout, policy failure, and interrupted generation. Missing telemetry is `unavailable`, never numeric zero. Provider-specific raw usage is retained alongside normalized fields because tokenizers and hidden-reasoning accounting differ.

Model failures score zero. A provider failure before inference, interrupted provider stream, outer runner
timeout, or reported-model mismatch is an infrastructure event. Those attempts are excluded from the
capability denominator only after a same-row retry replaces them, while all attempts appear in the
operational-efficiency report. A capability report is blocked if any infrastructure row is unresolved.

An explicit provider `finish_reason=length` is `output_budget_exhausted`, not a model-format zero. It
requires a new, uniformly frozen sufficient output ceiling (or a separately labelled budget treatment);
the truncated attempt remains in operational token/time accounting and is never silently mixed into a
different model configuration.

`numeric_results` is optional, unscored supporting JSON. It may contain nested values of any JSON type.
This contract was corrected in v0.5.0 after the original runner incorrectly required every value to be a
number. Existing answers rejected solely by that runner error are regraded verbatim; the model is not
queried again and the original answer hash remains auditable.

Recovery is explicit and resumable:

```bash
evoldo-bench recover-experiment --source runs/original/MODEL --output runs/recovered/MODEL \
  --max-infrastructure-retries 5 --timeout 300 -- \
  /absolute/path/to/model_adapter
```

The uniform direct-reasoning entry point is `tools/model_agent_adapter.py`. Formal invocations pass the
agent/model explicitly; Claude's DeepSeek profile is supplied at runtime and is never copied into this
repository. The adapter disables persistence/custom skills where each CLI supports it, serializes only
manifest-declared task files, and writes telemetry plus a structured outcome even when no answer is produced.

CLI-agent direct-reasoning invocations run inside a fresh, read-only Docker container with one runtime task
bundle mounted at `/task`, a minimal ephemeral authentication state, no repository/oracle/solution mount,
one CPU, 2 GiB memory, a 256-process limit, all Linux capabilities dropped, and a pinned base-image digest.
The OpenAI-compatible calibration adapter uses a host controller that serializes only the file-minimal bundle
into one provider request and registers no tools; this weaker host boundary is disclosed and is acceptable only
for public development calibration. Provider connectivity is never permission for model Web Search.
