# Contributing

Contributions are welcome when they preserve benchmark validity.

Before opening a change:

1. read `docs/AUTHORING_GUIDE.md` and `docs/SECURITY_AND_CONTAMINATION.md`;
2. keep all benchmark materials original and cite only methodology-level external references;
3. never commit private PDK, OA, model, testbench, or company data;
4. add or update deterministic tests;
5. regenerate public tasks and verify that a second generation produces no diff;
6. run `python -m unittest discover -s tests -v`, `python tools/run_self_check.py`, and
   `evoldo-bench audit`;
7. explain which physical fact changes in each counterexample.

New public families require analog-engineer review before they can be counted in a release milestone.
