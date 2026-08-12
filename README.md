# EvoLDO-Bench v0.7.0

EvoLDO-Bench 是面向 LDO 与模拟电路设计自动化的可审计诊断基准。v0.7 首先测试纯模型能力，并把“同一模型不挂知识库 / 挂冻结知识库”作为严格配对处理；所有答题模型均禁止使用 Web Search、浏览器、远程检索和未声明工具。

## v0.7 核心

纯模型核心包含 27 个 clean-room task，均采用 Windows Desktop `task_examples` demo 的目录结构。题目不是选择题：模型要提交结构化工程工件，完成数值计算、证据分类、约束核算、操作排序、停止规则和 claim boundary。评分采用连续数值、映射逐项、多标签逐记录、集合 F1 和序列对齐等部分分；局部字段/记录错误不会吞掉其他可验证维度，无法归属的答卷外壳错误才整题为 0，关键物理结论错误仍触发 49 分上限。

| 部署层级 | 数量 | 能力边界 |
|---|---:|---|
| T0 foundation | 4 | 基础反馈、headroom、约束与失败归因 |
| T1 local advice | 5 | 已有架构的局部诊断和单旋钮建议 |
| T2 bounded workflow | 8 | sizing、迁移、系统预算和 OA 操作规划 |
| T3 multi-constraint closure | 7 | 多角、多工件、硬门槛和 EDA 失败栈 |
| T4 end-to-end planning | 3 | 既有架构建议、sizing 账本准入与跨 source/OA/netlist/sim/qualification 闭环 |

另保留 6 个 SKY130/ngspice 真实设计闭环 task；后续工具能力评测使用同一 Sky130 revision、ngspice 和可信侧 verifier。Virtuoso/SKILL 使用 IC618 VM scratch 流程，不能把私有 PDK 或现有 library 带入公开任务。

## KG-off / KG-on

每个纯模型 task 都可在两种模式运行：

- `direct_reasoning`：只给 task 文件；
- `knowledge_assisted`：额外给确定性 TF-IDF 从 clean-room LDO KG 中生成的只读 `kg_retrieval.json`。

两种处理固定同一模型、task hash、answer contract、seed 和预算。报告给出逐题 score delta、KG harm rate、检索 recall@k 和 token overhead，并把题目分为 `benefit_expected`、`neutral_expected`、`override_resistant`。最后一类专门检查模型是否会让通用先验压过当前 hash-bound 证据。

v0.7 的正式单模型矩阵是 `27 tasks × 2 treatments × 3 independent rollouts = 162` 个能力 rollout；基础设施重试另计运营开销，不进入能力分母。若只评纯模型、不研究 KG，可单独报告 81 个 KG-off rollout，但不能把它与完整 KG 配对结果混称。

## 严格无 Web Search

禁止不只是一句提示词：schema 3.0 要求 `model_web_search=forbidden`、`allowed_tools=[]` 和 `max_tool_calls=0`；Codex 显式关闭 web/browser/computer/shell，Kimi 使用 `tools: []`，Claude 使用空 tools 与空 MCP，兼容 API 请求不注册 tools。运行日志一旦出现任何工具调用，整次 rollout 标为 `policy_fail`。

## 运行与检查

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .

evoldo-bench list --json
evoldo-bench validate --registry benchmarks/ldo_v07/registry.jsonl
python3 -m unittest discover -s tests -v
python3 tools/run_self_check.py
```

一次正式模型实验默认运行三个新会话；兼容 API 还显式传入三个不同 provider seed。模型完成、拒答、无法完成和格式失败均记录 terminal time 和可获得的 input/cache/output/reasoning token。网关、provider/runner timeout、模型身份、框架错误和供应商明确报告的输出预算截断不算模型失败；前四类用相同 task/rollout/seed 重试，预算截断则重开一个统一且单独标记的充分预算处理。所有失败尝试仍计入运营 token 与时间。每行结果同时绑定 prompt、task contract、全部公开 input、answer contract 与 oracle hash，case 内容变化后不能误配旧成绩。

完整规范见 [v0.7 benchmark 说明](docs/BENCHMARK_V07.md) 和 [task package 格式](docs/TASK_PACKAGE_FORMAT.md)。本仓库是公开 development benchmark；正式排名还需要隐藏同构变体与独立模拟专家复核。
