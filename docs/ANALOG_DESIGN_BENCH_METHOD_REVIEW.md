# Public Analog Design Bench method review and EvoLDO-Bench response

Reviewed on 2026-08-03:

- public website: https://analog-design-bench.tokenzhang.com/
- public preview repository: https://github.com/Arcadia-1/analog-design-bench

## What was publicly observable

The website describes original, long-horizon analog block-design tasks verified by open simulation. Its
public leaderboard separates Pass@1 from partial spec score and reports effort per task: output tokens,
steps, tool calls, elapsed minutes, estimated cost, token/cost breakdowns, cache share, rollout count, and
confidence intervals. Its score-versus-effort view makes the desired direction explicit: higher score at
lower effort. It also includes a benchmark-data training canary.

At review time, the linked public repository described itself as an initial preview scaffold; it did not
publish the task suite, evaluation protocol, implementation, or baseline artifacts. Therefore this project
did not infer, reproduce, translate, parameter-shift, or copy any hidden task or implementation detail.

## Ideas adopted at the method level

EvoLDO-Bench independently implements the following general benchmark practices:

1. **Pass@1 and partial spec score are separate.** A hard pass exposes design success; spec score preserves
   useful partial progress.
2. **Score is paired with effort.** Tokens, cache, steps, calls, time, and cost prevent a longer trajectory
   from looking automatically better.
3. **Uncertainty is visible.** Pass@1 includes a 95% interval and every treatment supports repeated runs.
4. **The upper-left frontier matters.** Static reports mark cost/spec-score Pareto candidates.
5. **Simulation verifies evidence, not rhetoric.** Tool failures remain infrastructure failures, and an LDO
   conclusion requires a relevant controlled probe.
6. **Canaries and contamination controls are release requirements.** Public development data is not a
   sealed exam.

## What remains deliberately different

EvoLDO-Bench is LDO-specific and resolves capabilities that a single block-level success rate can hide:
loop sign, operating point, startup/restart, stability measurement validity, noise/PSRR/system propagation,
process migration intent, coupled sizing, stale evidence, forbidden ideal devices, and private-site closure.
It also measures the causal lift of a distilled skill and simulator treatment for weak/offline agents.

The public corpus is dominated by controlled reasoning and evidence cases, while transistor-level open-PDK
closure is an adapter-backed next empirical stage. No PDK or silicon performance claim is made by the
analytic fixture or by the public development score.

## Clean-room rule

External benchmark pages may inform evaluation methodology. Their prompts, circuits, figures, netlists,
measurement decks, model outputs, hidden variants, rubrics, and result rows may not become EvoLDO-Bench
content without explicit compatible permission and provenance review. New LDO families must be authored
from the physical claim and independently reviewed, not paraphrased from another benchmark.
