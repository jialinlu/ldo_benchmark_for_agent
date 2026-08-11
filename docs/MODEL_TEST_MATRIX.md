# Model test matrix

This is the retained v0.5 pre-run inventory frozen on 2026-08-10. Access probes are infrastructure checks,
not benchmark scores. New v0.6 runs use the 69-task matrix in `BENCHMARK_V06.md`; this document preserves
model-access provenance only.

The selected first run is GPT-5.6-sol, Kimi K3, DeepSeek V4 Pro, and DeepSeek V4 Flash. Its pre-run policy
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

The machine-readable inventory is [`benchmarks/model_matrix.json`](../benchmarks/model_matrix.json). It deliberately contains no credentials, credential paths, or private configuration values.

## Token policy

Every scheduled attempt retains provider-reported input, cache-read, cache-write, output, reasoning, cost, and wall time when available. This includes valid answers, model-declared inability, refusal, malformed output, timeout, policy failure, and interrupted generation. Missing telemetry is `unavailable`, never numeric zero. Provider-specific raw usage is retained alongside normalized fields because tokenizers and hidden-reasoning accounting differ.

Model failures score zero. A provider failure before inference, interrupted provider stream, outer runner
timeout, or reported-model mismatch is an infrastructure event. Those attempts are excluded from the
capability denominator only after a same-row retry replaces them, while all attempts appear in the
operational-efficiency report. A capability report is blocked if any infrastructure row is unresolved.

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

Each direct-reasoning invocation runs inside a fresh, read-only Docker container with one runtime task bundle
mounted at `/task`, a minimal ephemeral authentication state, no repository/oracle/solution mount, one CPU,
2 GiB memory, a 256-process limit, all Linux capabilities dropped, and a pinned base-image digest. Docker
bridge networking remains enabled solely because the four provider CLIs require network access; this is an
explicit limitation of the public-development treatment.
