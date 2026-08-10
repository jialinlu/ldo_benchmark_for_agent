# Security, isolation, and contamination

## Threat model

The benchmark must defend against accidental or deliberate access to:

- hidden task variants and family lineage;
- golden answers, deterministic oracles, rubrics, and judge prompts;
- reference decks and reference measurements;
- other models' outputs and prior score reports;
- a knowledge snapshot containing the same task or answer;
- private PDK and company assets not authorized for the agent.

## What the current audit enforces

`evoldo-bench audit` checks:

- duplicate task IDs through discovery;
- one split per family;
- forbidden oracle/golden/rubric paths in public task directories;
- expected oracle presence and task/family identity for the selected oracle store;
- high lexical similarity across different families as a warning-level guardrail.

Runtime bundling hashes every copied file and records `oracle_included=false`.

Public development task directories may also contain separate `tests/` and `solution/` source trees in
the task_examples-compatible layout. Those trees are forbidden runtime paths and are never copied into
the agent bundle. A sealed exam keeps equivalent verifier and solution material outside the checkout and
agent mount rather than relying only on path filtering.

Controlled experiments additionally freeze context snapshots, bind task and answer-contract hashes, and
normalize the tool ledger. Calls without a ledger, rejected probe contracts, and budget overruns are policy
failures. This detects declared-protocol violations; only an operating-system sandbox can prevent a hostile
agent from bypassing the gateway.

## What it does not enforce

The reference runner is not a kernel sandbox. It cannot stop a hostile process from reading arbitrary host
paths, opening the network, inspecting process state, or invoking undeclared tools. Lexical similarity is
also not proof that two circuits are semantically independent.

A sealed exam therefore requires:

1. a fresh container, VM, or remote worker per rollout;
2. read-only mount of the runtime bundle and approved skill snapshot only;
3. no repository checkout in the agent namespace;
4. no network unless the treatment explicitly defines a separately scored network mode;
5. a tool allowlist and tool-call ledger;
6. external private oracle storage visible only to the grader;
7. canary files and forbidden-path audit;
8. immutable task, skill, tool, model, simulator, and judge hashes;
9. destruction or sealing of scratch storage after final outputs are collected.

## Contamination policy

- Benchmark results never write directly into the knowledge store.
- Training and benchmark family lineages are disjoint.
- Canonical, metamorphic, counterexample, regime, and difficulty variants stay together.
- Near-duplicate graph and text scans run before release.
- Any detected hidden-material access makes the rollout `INVALID_CONTAMINATED`, not merely low scoring.
- Public development tasks cannot be reused as evidence of sealed generalization.

## Public development oracle warning

`benchmarks/ldo_original/dev_reference/oracles` is intentionally public so contributors can validate the
runner and grader. An agent with access to the full checkout can read it. Such a run is not isolated and
must not be called an exam. Build a runtime bundle and use an external private store for real evaluation.
