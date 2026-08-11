# Roadmap and acceptance gates

This file separates **implemented infrastructure** from **empirical acceptance**. A command existing does
not prove model capability, expert agreement, or PDK performance.

## Phase 0 — contracts and threat model: implemented

Delivered task, answer, oracle, score, probe, telemetry, exam, candidate, and qualification contracts;
Python 3.9 validators; lineage/split rules; public-task/private-oracle architecture; contamination and
public-release security policy; dual licensing and clean-room statement.

Current gate: all 69 v0.6.1 task contracts and public development oracles validate in CI; 48 pure core,
eight pure companions, six live sizing, six live EDA, and one EDA companion are frozen in the registry.

## Phase 1 — public benchmark core: implemented

Delivered file-minimal bundles, timeout-bounded command execution, deterministic grading with critical
caps, family/suite/level/variant aggregation, Markdown/JSON reports, deterministic task generation, and
public self-checks.

Gate: synthesized public-reference answers score 100, deliberate fatal conclusions are capped at 49,
collection audit passes, and regeneration produces no diff.

## Phase 2 — skill and simulator treatments: infrastructure implemented

Delivered:

- immutable skill/context snapshots and hashes;
- command-model adapter and repeated-rollout orchestration;
- paired-treatment comparator for model/task/seed/budget/answer-contract equality;
- enforced `AnalogProbeContract`, task probe policy, tool ledger, and call budget;
- wrong-regime, confounded-intervention, invented-artifact, unrelated-probe, and measurement checks;
- uniform JSON simulator adapter, optional ngspice batch adapter, and analytic protocol fixture;
- `INFRA_FAIL` separation from circuit results;
- Pass@1 confidence intervals, spec score, effort/cost/cache metrics, lift, harm, and ineffective probes.

Remaining empirical gate: run direct/skill/simulation treatments with frozen real adapters and confirm that
results replay exactly. A host sandbox remains deployment infrastructure, not part of the Python runner.

## Phase 3 — v0.6.1 diagnostic pilot: corpus and release tooling implemented

Delivered:

- 48 pure core cases, eight metamorphic companions, six sizing treatments, and seven EDA tasks;
- six-dimension pure-case grading with scenario-local ordered-choice credit and evidence-set F1;
- architecture-choice and L4 development coverage;
- cryptographic freeze/verify manifest for sealed stores and treatment snapshots;
- two-judge calibration metrics and automatic human-review routing;
- static JSON/CSV/HTML score-versus-effort reporting.

External acceptance work still required:

- two analog engineers independently review/calibrate the numeric and closure set using
  [`ANALOG_EXPERT_REVIEW_GUIDE_ZH.md`](ANALOG_EXPERT_REVIEW_GUIDE_ZH.md);
- freeze heterogeneous judge model/prompt snapshots and meet accepted agreement/critical-recall gates;
- run at least three model capability tiers with at least three rollouts;
- verify strong/medium/weak separation and absence of length/call/suite dominance;
- author hidden families outside this public repository; public families cannot become a sealed exam by
  merely hiding their files.

## Phase 4 — public-PDK design closure: six-task development track implemented

Delivered:

- `SimulatorAdapter`, `NgspiceBatchAdapter`, and out-of-tree `SiteAdapter` boundaries;
- immutable candidate manifests;
- fresh-evidence gates for operating point, startup, shutdown/restart, stability, PSRR, noise, load
  transient, PVT, and forbidden devices;
- stale-evidence rejection;
- evaluations, wall time, and gate robustness to first qualified candidate.
- pinned/hash-checked SKY130 model acquisition without vendoring PDK assets;
- six independently authored transistor-level fault-injection tasks covering operating point, cold start,
  shutdown/restart, load transient, line/load regulation, and PVT/policy;
- rendered-deck execution, measurement/spec parsing, and explicit infrastructure/measurement/policy/circuit
  failure classes;
- a development reference replayed in open-source ngspice CI.

External acceptance work still required:

- implement each approved private-site adapter outside the public repository;
- compare cold and assisted sizing under the same candidate/qualification budget;
- add a portable ASAP7 execution job only after OSDI platform and license-notice review are closed;
- obtain independent PDK, simulator, originality, numeric-threshold, and analog-engineer sign-off.

Private PDK assets must never enter the public repository, model context, or public CI.

## Phase 5 — EvoLDO-Exam v1.0: planned

Planned:

- 80 families / 240–400 instances covering L1–L4; L5 remains experimental;
- genuinely hidden family lineages and private oracle store;
- frozen model, skill, tool, simulator, judge, budget, and rollout policy;
- reproducibility/regression dashboard and release canaries;
- formal license, originality, PDK, security, and human-expert sign-off.

Acceptance gate: every reported result is replayable, the contamination audit passes, no hidden lineage is
public or in training context, and the scorecard publishes capability vectors and effort rather than only
a rank.
