# v0.7 task package format

每个 task 严格采用 Analog Arena / Windows Desktop `task_examples` demo 顶层布局：

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

模型 runtime 只复制 `environment/starter` 和 `instruction.md`。`tests`、`solution`、外部 oracle、其他 task 和历史答卷不可见。

`task_contract.json` 使用 schema 3.0，并声明部署层级、eligible treatments、预算和强制无 Web Search/无工具策略。`case.json` 包含合成场景、原始记录、受控词表及逐字段 answer contract；受控词表顺序是确定性打乱的，不能编码参考排序。

`answer.json` 使用统一外壳：

```json
{
  "schema_version": "3.0",
  "task_id": "v07-...",
  "artifact": {"task_specific_field": "CONTROLLED_VALUE"},
  "claim_boundary": "Only supplied current evidence is claimed.",
  "confidence": 0.8
}
```

题目特定字段由 `case.json.answer_contract.fields` 校验。主评分器和 task 内嵌 verifier 都支持连续数值、区间、逐键映射、多标签逐记录 F1、集合 F1、序列对齐和 exact/critical checks；oracle 权重必须合计 100。评分时，无法归属的外壳/必填字段/task-ID 错误整题为 0，已归属答卷中的局部非法字段或记录只在引用它的原子检查内失分；独立的严格 contract validator 仍会拒绝该答卷。集合字段的允许词表必须至少包含一个不属于 golden 的场景内干扰项，防止“全选即满分”。

KG-on 不改变 task package。runner 在每个 rollout 内从版本化 clean-room corpus 生成并冻结 `context/kg_retrieval.json`，记录 corpus/query hash、排序和 retrieval metrics。模型不能自行检索。
