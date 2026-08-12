# EvoLDO-Exam release runbook

For executable commands and mandatory stop conditions, use
[`CONTROLLED_PILOT_RUNBOOK.md`](CONTROLLED_PILOT_RUNBOOK.md). This file is the short release checklist.

This runbook describes a future sealed release. The public development set is not an exam.

## 1. Freeze

- Freeze family list, split, task generator commit, task hashes, oracle hashes, schema versions, and budget.
- Freeze model adapters, skill snapshot, tool image, simulator/model hashes, grader, and judge versions.
- Record all items in `exam_manifest.json`; do not expose hidden task identifiers to the agent runtime.

## 2. Audit

- Run originality and third-party-license review.
- Run graph/text/parameter/evidence near-duplicate scans across train/dev/test lineages.
- Confirm no family crosses a split.
- Confirm hidden store is outside repository and runtime namespace.
- Insert canary files and test forbidden-path detection.

## 3. Calibrate

- Two analog engineers independently score the calibration set.
- Resolve disagreements and freeze adjudicated examples.
- Measure explanation-judge agreement and critical-error recall.
- Do not automate explanation scoring until the threshold is accepted and recorded.

## 4. Execute

- Start a clean sandbox per task and rollout.
- Mount only public runtime bundle, approved skill, and approved tool endpoints.
- Disable network unless a separate network treatment is explicitly declared.
- Run at least three rollouts with fixed seed policy and budgets.
- Collect final answer, permitted artifacts, tool ledger, stdout/stderr, and provenance.

## 5. Grade

- Run schema/policy gate first.
- Run deterministic facts and qualification gates.
- Route only explanation dimensions to calibrated judges.
- Send critical disagreement and sampled passes/failures to human audit.
- Aggregate at family level and publish capability vectors, variation, errors, cost, and lift.
- Generate the mandatory four-panel report from one frozen treatment: (1) capability score plus T0–T4/suite/dimension profile and three-rollout uncertainty; (2) capability versus measured per-task cost on a log axis with price snapshot, Pareto frontier, and any reference-model kill zone explicitly labeled as two-dimensional dominance; (3) capability versus latency with end-to-end P50/P95, time to first feasible output, capability wall time, and operational wall time; and (4) capability versus reliability with infrastructure/model/format/policy failure rates, output-budget exhaustion, rollout variance, and unresolved-infrastructure count.
- Do not mix output ceilings, reasoning modes, task sets, grader versions, or other treatments in one frontier. If provider billing is unavailable, label token-rate-derived cost as estimated and publish the rate snapshot and formula.

## 6. Release

- Publish release manifest and permitted sample tasks only.
- Keep hidden task/oracle content sealed.
- State simulator/PDK limitations and invalidated rollouts.
- Never label a public-dev score or fixture-backed private-site run as an Exam score.
