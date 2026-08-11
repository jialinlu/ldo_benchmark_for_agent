# EvoLDO-Bench v0.6

EvoLDO-Bench 是面向 LDO 与模拟电路设计的可审计模型基准。v0.6 先测纯模型能力，再用严格配对的 SKY130/ngspice sizing 与 Cadence Virtuoso IC618/SKILL 任务测工具增益；框架错误、网关错误、许可证和 PDK 不可用均记为 `INFRA_INVALID`，不得算作模型失败。

## v0.6 任务矩阵

| 分组 | 数量 | 目的 |
|---|---:|---|
| Pure Model Core | 48 | 8 个能力域 × 6 题；每域 3 atomic、2 coupled、1 existing-architecture optimization |
| Pure companions | 8 | 每能力域 1 个等价变换题，测表示鲁棒性 |
| Tool Sizing | 6 | 与 6 个纯 sizing 题配对，调用 SKY130/ngspice 探针 |
| EDA primary | 6 | failure triage、只读 OA audit、局部编辑、可见连线、Spectre 测量、mini closure |
| EDA companion | 1 | OA 对象改名与枚举顺序变化后的不变性 |

共 69 个 rollout 单元。每模型独立运行 3 次，共 207 次；三次使用独立会话、空白上下文和不同 rollout seed，不共享答案、scratch、缓存目录或工具 ledger。

能力域包括 structure、trend、diagnosis、sizing、migration、system impact、design closure、architecture choice。已有架构优化和 sizing 均能单独出分，不会被总体平均数掩盖。

## 任务格式

每个任务严格采用 Windows Desktop `task_examples` demo 的顶层结构：

```text
task-id/
├── task.toml
├── instruction.md
├── environment/
│   ├── Dockerfile
│   └── starter/
├── tests/
│   ├── Dockerfile
│   ├── test.sh
│   └── verify.py
└── solution/
    └── solve.sh
```

`tests`、`solution` 和外部 oracle 不进入模型 runtime bundle。完整规范见 [v0.6 benchmark 说明](docs/BENCHMARK_V06.md) 与 [任务包格式](docs/TASK_PACKAGE_FORMAT.md)。

## 快速检查

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .

evoldo-bench list --json
evoldo-bench validate --registry benchmarks/ldo_v06/registry.jsonl
python3 -m unittest discover -s tests -v
python3 tools/run_self_check.py
```

运行一个纯模型任务：

```bash
evoldo-bench run v06-diagnosis-01-ringing \
  --mode direct_reasoning --output runs/example -- \
  python3 /absolute/path/to/agent_adapter.py

evoldo-bench grade runs/example/app/answer.json \
  --output runs/example/score.json
```

验证 sizing 工具答卷：

```bash
evoldo-bench verify-live runs/sizing/app/answer.json \
  --app-root runs/sizing/app \
  --pdk-root "$SKY130_PDK_ROOT" \
  --ngspice "$NGSPICE"
```

验证 Virtuoso/SKILL 答卷：

```bash
evoldo-bench verify-live runs/eda/app/answer.json \
  --app-root runs/eda/app \
  --eda-ssh-target "$EVOLDO_EDA_SSH_TARGET"
```

正式 EDA 验证只在新建的远端 `/tmp/evoldo-<nonce>` scratch 中执行，使用 `-nocdsinit`，不触碰已有 library；save/close/reopen/readback 和新鲜 Spectre provenance 是硬门槛。

## 计分与 token

每题 0–100 分，关键结论或机制错误触发 49 分上限。报告至少分开给出 Pure Model Core、existing-architecture optimization、pure sizing、tool sizing、EDA tool、metamorphic consistency，以及 tool lift/harm。

每次成功、拒答、不完整或超时都保存 input、cached input、output、reasoning、cache write token；字段不可获得时必须为 `null`，不能填 0。还记录完成/确认无法完成时的 terminal token、terminal time，以及工具调用、wall time 与费用。基础设施重试单独计入运营成本，但不进入模型能力分母。

本仓库是 public development benchmark，不是 sealed exam。公开 oracle 用于框架开发；正式排名应冻结 hidden forms、模型版本、适配器、预算、工具版本、PDK hash 和三次 rollout 矩阵。
