# Controlled pilot and sealed-exam runbook

This is the operational entry point for running EvoLDO-Bench. Follow the gates in order. Do not skip a
failed gate and do not relabel a public-development run as an exam.

## 0. Preflight

```bash
python -m pip install -e .
evoldo-bench validate
evoldo-bench audit
python -m unittest discover -s tests -v
python tools/run_self_check.py
python tools/audit_public_release.py
```

Required result: every command exits zero. If not, stop the release; fixing an infrastructure failure is
not model tuning.

## 1. Freeze the treatment inputs

Prepare:

- one immutable model adapter command and model identifier;
- one skill/context directory for the skill and simulation treatments;
- one approved tool wrapper/image for the simulation treatment;
- a fixed task list, rollout count, base seed, timeout, tool budget, and answer contract;
- a private oracle root outside the agent mount for a sealed run.

Never route tools per task from a hidden answer table. The same tool interface must be available to every
eligible task in that treatment.

## 2. Run direct, skill, and simulation treatments

```bash
evoldo-bench experiment --output runs/direct --model-id MODEL \
  --mode direct_reasoning --rollouts 3 --base-seed 2026 \
  --paired-modes direct_reasoning,agentic_skill,simulation_assisted -- \
  /absolute/path/to/model_adapter

evoldo-bench experiment --output runs/skill --model-id MODEL \
  --mode agentic_skill --rollouts 3 --base-seed 2026 \
  --paired-modes direct_reasoning,agentic_skill,simulation_assisted \
  --context-dir /absolute/path/to/frozen_skill -- \
  /absolute/path/to/model_adapter

evoldo-bench experiment --output runs/simulation --model-id MODEL \
  --mode simulation_assisted --rollouts 3 --base-seed 2026 \
  --paired-modes direct_reasoning,agentic_skill,simulation_assisted \
  --context-dir /absolute/path/to/frozen_skill -- \
  /absolute/path/to/model_adapter
```

The adapter must write the same `answer.json` contract in all modes. Detailed provider telemetry may be
written to `EVOLDO_TELEMETRY_PATH`. Any tool use must be recorded at `EVOLDO_TOOL_LEDGER_PATH`; undeclared
calls, rejected probes, and over-budget calls are policy failures.

Every scheduled rollout remains in the score denominator. A model timeout, refusal, declared inability,
malformed answer, missing answer, or policy failure receives a deterministic zero. Provider or runner
infrastructure failures follow the release's pre-frozen retry policy and remain visible in the operational
report. Missing token or cost telemetry is `unavailable`, never silently converted to numeric zero.

## 3. Prove the comparison is paired

```bash
evoldo-bench compare-treatments \
  runs/direct/experiment_manifest.json \
  runs/skill/experiment_manifest.json \
  runs/simulation/experiment_manifest.json
```

Required result: `passed=true`. A model, task, rollout, seed, budget, task hash, or answer-contract mismatch
invalidates causal lift. Different frozen context/tool snapshots are the intended treatment changes.

## 4. Enforce every simulator probe

Before a simulator call, write and validate an `AnalogProbeContract`:

```bash
evoldo-bench validate-probe probe.json --task-id TASK_ID \
  --available-artifact inputs/case.json
```

Do not run the tool if the gate reports wrong regime, unrelated probe, confounding, held-fixed violation,
invented artifact, or measurement mismatch. The approved gateway must return `INFRA_FAIL` for missing
executables, timeout, invalid output, or setup failure. It must not invent a circuit conclusion.

A normalized ledger entry contains the probe, tool status, evidence hash, and whether the final answer used
that evidence. The report computes ineffective-probe and policy-rejection rates.

## 5. Grade and publish score-versus-effort reports

```bash
evoldo-bench experiment-report runs/direct --output reports/direct.json --markdown reports/direct.md
evoldo-bench experiment-report runs/skill --output reports/skill.json --markdown reports/skill.md
evoldo-bench experiment-report runs/simulation --output reports/simulation.json --markdown reports/simulation.md

evoldo-bench paired-lift --direct reports/direct.json --skill reports/skill.json \
  --simulation reports/simulation.json

evoldo-bench leaderboard reports/direct.json reports/skill.json reports/simulation.json \
  --output-dir reports/leaderboard
```

Publish Pass@1 with its interval, spec score, family macro, suite/level vectors, critical errors, tokens,
cache, steps, calls, time, cost, lift, simulation harm, and ineffective probes. Do not publish only one rank.

## 6. Calibrate explanation judges before enabling them

Two analog engineers independently label an external calibration set and adjudicate disagreements. Run two
heterogeneous frozen judge snapshots, then:

```bash
evoldo-bench calibrate-judges human_records.json judge_records.json \
  --max-mae 10 --minimum-critical-recall 0.90 --minimum-label-agreement 0.80
```

Thresholds are release-policy decisions and must be frozen before looking at final test results. If either
judge fails, explanation automation remains disabled. For each scored explanation:

```bash
evoldo-bench combine-judges two_records.json --score-tolerance 10
```

`HUMAN_REVIEW` is mandatory on label, critical-error, or large score disagreement. Deterministic facts and
hard qualification gates never move to an LLM judge merely because prose scoring is convenient.

## 7. Freeze a sealed exam

Hidden families and oracles must be genuinely external and lineage-disjoint from public tasks.

```bash
evoldo-bench create-exam-canary --release-id RELEASE --output /sealed/tasks/CANARY.txt
evoldo-bench freeze-exam --tasks-root /sealed/tasks --oracle-root /sealed/oracles \
  --policy exam_policy.json --skill-root /sealed/skill --tool-root /sealed/tool \
  --release-id RELEASE --output /sealed/exam_manifest.json

evoldo-bench verify-exam /sealed/exam_manifest.json \
  --tasks-root /sealed/tasks --oracle-root /sealed/oracles \
  --skill-root /sealed/skill --tool-root /sealed/tool
evoldo-bench redact-exam-manifest /sealed/exam_manifest.json \
  --output exam_manifest.public.json
```

Mount tasks and approved snapshots read-only in the agent sandbox. Never mount oracles, judge-private
material, the repository checkout, prior outputs, or private PDK assets. Insert canaries and disable network
unless network access is an explicit separately reported treatment.

The full manifest contains hidden relative paths and policy contents and stays private. Publish only the
redacted commitment, which retains aggregate digests and file counts.

## 8. Run design closure

For every candidate:

```bash
evoldo-bench candidate-manifest /candidate/artifacts --candidate-id CANDIDATE \
  --output candidate.json
evoldo-bench qualify candidate.json qualification_evidence.json \
  --output qualification.json
```

Promotion requires fresh evidence bound to the exact candidate hash for:

1. operating point;
2. cold start;
3. shutdown/restart;
4. stability;
5. PSRR;
6. noise;
7. load transient;
8. PVT;
9. forbidden-device scan.

A missing, stale, failed, parse-invalid, measurement-invalid, or infrastructure-invalid gate blocks
promotion. It is never silently converted to zero performance. Summarize search efficiency with:

```bash
evoldo-bench closure-metrics qualification_attempts.json
```

Run cold and assisted sizing with the same initial candidate, parameter bounds, qualification plan,
evaluation budget, and tool policy.

## 9. Sign-off checklist

A formal result needs all of the following:

- originality and contamination review;
- public-release secret/private-asset audit;
- reproducible task generation and replay;
- paired-treatment control pass;
- model/skill/tool/simulator/judge hashes;
- two-engineer calibration and accepted thresholds;
- simulator/PDK license and reproducibility sign-off;
- fresh candidate qualification;
- capability and effort vectors;
- explicit limitations and invalid rollout counts.

If any item is absent, publish it as a development experiment with that limitation—not as EvoLDO-Exam.
