# Original LDO public development set

This directory contains 12 independently authored task families with 36 public development instances.
Each family includes canonical, metamorphic, and counterexample variants.

- `dev/tasks/`: material allowed in a runtime bundle.
- `dev_reference/oracles/`: public development grader fixtures; never copied into a runtime bundle.
- `registry.jsonl`: task identity, lineage, suite, level, variant, split, and manifest hash.

The public oracles are for infrastructure development and unit tests. They do not provide a hidden exam.
Formal validation/test/sealed tasks and oracles must be stored outside this repository.

Regenerate deterministic public assets with:

```bash
python tools/generate_dev_tasks.py
```

Then run:

```bash
python -m unittest discover -s tests -v
python tools/run_self_check.py
evoldo-bench audit
```

The material is CC BY 4.0 unless stated otherwise. See `BENCHMARK_LICENSE.md` at repository root.
