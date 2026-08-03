# Original LDO public development set

This directory contains **40 independently authored task families and 120 public development instances**.
Each family has canonical, metamorphic, and decision-changing counterexample variants.

- `dev/tasks/`: material allowed in a runtime bundle.
- `dev_reference/oracles/`: public development grader fixtures; never copied into a runtime bundle.
- `registry.jsonl`: task identity, lineage, suite, level, variant, split, and manifest hash.

The suites cover structure, trend, diagnosis, sizing, migration, system impact, design closure, and
architecture choice across L1–L4. The public oracles exist for infrastructure development and do not make
this a hidden exam. Validation/test/sealed tasks and oracles must live outside the repository.

Regenerate and verify:

```bash
python tools/generate_dev_tasks.py
python -m unittest discover -s tests -v
python tools/run_self_check.py
evoldo-bench audit
```

The material is CC BY 4.0 unless stated otherwise. See `BENCHMARK_LICENSE.md` at repository root.
