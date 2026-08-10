# Task package format

Every public reasoning task and SKY130 design-closure task has a task_examples/Harbor-style wrapper while retaining the native EvoLDO contracts.

```text
TASK_ID/
├── task.toml
├── instruction.md
├── environment/
│   ├── Dockerfile
│   └── starter/
├── tests/
│   ├── Dockerfile
│   ├── test.sh
│   └── verifier assets
├── solution/
│   ├── solve.sh
│   └── public development reference artifact
└── package_manifest.json
```

For reasoning tasks the submitted artifact is `/app/answer.json`. The starter contains the task contract, answer template, and declared inputs. The separate verifier implements the deterministic public-development oracle and emits `reward.json` plus CTRF-compatible results.

For closure tasks the submitted artifact is `/app/circuit.spi`. The verifier runs the existing candidate policy and fresh-evidence SKY130/ngspice flow. SKY130 models remain an external hash-pinned runtime dependency; they are not copied into a task package.

`tests/` and `solution/` are public development/source assets and are never copied by `build_runtime_bundle`. A sealed exam must keep both verifier material and solutions outside the agent mount entirely. `package_manifest.json` binds all package files except itself, and the reasoning registry binds that package digest.

Regenerate all wrappers with:

```bash
python3 tools/generate_dev_tasks.py
python3 tools/generate_task_packages.py
```
