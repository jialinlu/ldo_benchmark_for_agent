# EvoLDO v0.6.1 task store

This generated directory contains 69 public-development task packages: 48 pure-model core cases, eight
metamorphic companions, six paired SKY130/ngspice sizing treatments, six IC618/SKILL primary tasks, and
one EDA companion. Every task uses the `task_examples` layout (`task.toml`, `instruction.md`, separate
`environment/starter`, `tests`, and `solution`). Regenerate with `python3 tools/generate_v06_tasks.py`.

`registry.jsonl` hashes the complete package and `dev_reference/oracles` is never copied into an agent
runtime bundle. Tool-task answer grading is only semantic; an official tool score additionally requires
`evoldo-bench verify-live`, whose infrastructure-invalid result must be retried rather than scored zero.
Pure reasoning tasks use six dimensions with ordered-choice partial credit and evidence-set F1 scoring.
See `docs/BENCHMARK_V06.md` for the protocol and score definitions.
