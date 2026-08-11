# v0.6 task-family authoring guide

## Required family structure

Each pure suite contains three atomic cases, two coupled cases, and one existing-architecture optimization
capstone. One selected parent per suite also has a metamorphic companion. Parent and companion share
`family_id`/`lineage_id` and remain in one split. Tool-sizing treatments share lineage with the matching
pure-sizing task but retain a separate score dimension.

## Authoring workflow

1. Write the physical claim as a falsifiable sentence.
2. State analysis regime and held-fixed variables.
3. Identify the smallest structural or evidence change that should alter the conclusion.
4. Define controlled vocabulary with plausible distractors.
5. Write deterministic checks for conclusion, evidence, mechanism tags, actions, and forbidden actions.
   Controlled selection fields use exact-set checks unless the rubric also defines an explicit false-positive
   penalty; unpenalized `set_contains` checks are not allowed for scored multiple-choice vocabularies.
6. Confirm weights sum to 100 and mark physically fatal checks as critical.
7. Generate all assets with `tools/generate_v06_tasks.py` in the demo-task layout.
8. Run unit tests, `tools/run_self_check.py`, and contamination audit.
9. Obtain two analog-engineer reviews for any numeric or design-closure task.
10. Record source provenance and originality review before moving a family into a sealed split.

Use [`BENCHMARK_V06.md`](BENCHMARK_V06.md) for the frozen coverage, scoring, independence, and live-tool gates.

## Rules for numeric tasks

- Units must be explicit.
- A trend claim needs low/base/high or equivalent evidence.
- Causal attribution requires held-fixed conditions.
- Non-monotonic behavior must retain the turning point, not be reduced to one local slope.
- Numeric goldens must have a reproducible analytic or simulator evidence record.
- Simulator version, model hash, deck hash, corner, temperature, load, and measurement expression must be
  bound in the private oracle metadata.

## Rules for LDO design tasks

A design task must separate eligibility from performance. Recommended eligibility gates are:

```text
simulator completed
functional operating point
cold start
shutdown/restart when required
stability hard gates
forbidden-device audit
evidence hash integrity
```

Only eligible candidates enter performance ranking. `INFRA_FAIL`, `MEAS_FAIL`, and `PARSE_FAIL` are not
`CIRCUIT_FAIL` and must not become negative sizing examples.

## Copyright and PDK policy

Do not copy, redraw, paraphrase, parameter-shift, or derive tasks from external benchmark materials without
explicit permission. Do not commit private PDK model files, private device names, OA databases, company
testbenches, or screenshots containing confidential identifiers. A public task may describe a generic
physical situation, but every prompt, circuit, fixture, oracle, and rubric must be independently authored.
