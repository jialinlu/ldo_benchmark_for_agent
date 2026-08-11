# v0.6.2 task package format

v0.6.2 只接受与 Windows Desktop `task_examples` demo 一致的顶层布局：

```text
<task-id>/
├── task.toml
├── instruction.md
├── environment/
│   ├── Dockerfile
│   └── starter/
│       ├── task_contract.json
│       ├── case.json
│       └── answer_template.json
├── tests/
│   ├── Dockerfile
│   ├── test.sh
│   ├── verify.py
│   └── expected.json
└── solution/
    ├── answer.json
    └── solve.sh
```

工具任务可在 `starter` 增加受预算约束的 tool wrapper/netlist，在 `solution` 增加 `candidate.json` 或 `solution.il`。禁止在顶层增加旧版 `task.json`、`prompt.md`、`package_manifest.json`；通用 runner 所需的详细契约放在 starter 内部。

`task.toml` 使用 schema 1.3，声明 artifact、task metadata、separate verifier 和 environment 资源限制。模型容器仅复制 `environment/starter` 到 `/app`，另复制 `instruction.md`；`tests`、`solution` 和 `dev_reference/oracles` 不可见。

`task_contract.json` 使用 EvoLDO schema 2.0，至少包含 task/family/lineage、suite、level、variant、eligible mode、budget、input files 和 evaluation role。`answer.json` 使用 schema 2.0：

```json
{
  "schema_version": "2.0",
  "task_id": "v06-...",
  "answers": {"q1": "A", "q2": "C", "q3": "B", "q4": "D", "q5": ["A", "D", "B", "C"], "q6": ["E1", "E4"]},
  "claim_boundary": "limited to supplied evidence",
  "confidence": 0.8
}
```

通用 `grade` 只计算语义分。`sizing_assisted` 和 `eda_assisted` 的正式分数必须再通过可信侧 `verify-live`；agent 自己写入的 ledger 不能替代 verifier 新鲜执行。
