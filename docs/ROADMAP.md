# Roadmap and acceptance gates

## Phase 0 — contracts and threat model: implemented in v0.1.0

Delivered:

- task, answer, oracle, score, and `AnalogProbeContract` schemas;
- Python 3.9 custom validators;
- family lineage and split rules;
- public-task/private-oracle architecture;
- error and contamination policy;
- dual licensing and clean-room statement.

Gate: 36 generated task contracts and 36 public development oracles validate in CI.

## Phase 1 — 12-family public MVP: implemented in v0.1.0

Delivered:

- 12 original families and 36 canonical/metamorphic/counterexample instances;
- direct command runner and file-minimal bundle;
- deterministic grading with critical caps;
- family-macro, suite, level, and variant aggregation;
- Markdown/JSON scorecards;
- public development self-check and tests.

Gate: reference development answers score 100, deliberate fatal conclusion errors are capped at 49,
collection audit passes, and task regeneration produces no diff.

## Phase 2 — skill and simulator treatments: next

Planned:

- immutable skill/context snapshots and hashes;
- model-adapter interface and three-rollout orchestration;
- enforced probe contract before tool calls;
- uniform simulator tool, no per-task routing;
- tool budget and policy grader;
- `skill_lift`, `simulation_lift`, `simulation_harm_rate`, and ineffective-probe rate;
- task families with analytic and open-simulator evidence.

Acceptance gate:

- paired runs hold model, task, seed, budget, and answer contract fixed;
- wrong regime, confounded intervention, invented deck, and unrelated probe are detected;
- unavailable simulator is `INFRA_FAIL`, not a circuit answer.

## Phase 3 — 40-family controlled pilot

Planned:

- expand to 40 families and 120–200 instances;
- add architecture choice and harder regime/difficulty variants;
- sealed test store and release manifest;
- two heterogeneous explanation judges;
- human calibration set with two analog engineers;
- baseline three model capability tiers with three rollouts.

Acceptance gate:

- stable strong/medium/weak separation;
- explanation judge meets frozen human-agreement thresholds;
- score is not driven by output length, tool-call count, or one easy suite.

## Phase 4 — hardware-backed design closure

Planned:

- public open-PDK simulator adapter after license and reproducibility selection;
- private site adapter for an approved EDA/PDK stack;
- immutable design candidate and qualification manifests;
- OP, startup, shutdown/restart, STB, PSRR, noise, transient, PVT, and forbidden-device gates;
- evaluations-to-qualification, wall time, robustness, and evidence scoring;
- cold-versus-assisted sizing comparison.

Acceptance gate:

- at least four design tasks expose distinct OP/startup/stability/measurement failures;
- only fresh qualification promotes a candidate;
- private PDK assets never enter the public repository or model context.

## Phase 5 — v1.0 and EvoLDO-Exam

Planned:

- 80 families and 240–400 instances covering L1–L4;
- L5 innovation remains experimental;
- frozen exam manifest, task/oracle hashes, judges, tools, budgets, and rollout policy;
- reproducibility and regression dashboard;
- license, originality, PDK, and human-expert sign-off.

Acceptance gate: contamination audit passes, every result is replayable, and the formal scorecard exposes
capability vectors rather than only a single leaderboard number.
