# Detect a sign convention error in load-current reporting

You are evaluating one original LDO engineering case. Read `inputs/case.json`.

Return exactly one `answer.json` in this directory, following `answer_template.json`.

Rules:

1. Select `conclusion`, `analysis_regime`, and controlled array tokens only from the vocabulary in the case file.
2. State what is held fixed; do not infer a causal trend from a confounded sweep.
3. Use only supplied evidence. A simulator, license, parser, bench, measurement, and circuit failure are different classes.
4. `mechanism` and `claim_boundary` must be concise engineer-facing prose; hidden chain-of-thought is neither requested nor scored.
5. Do not use nodeset, forced initial conditions, ideal bias sources, or invented PDK data as a final circuit fix.
6. Do not access reference answers or oracles. Public development oracles are outside the runtime bundle and formal exams use a private store.
