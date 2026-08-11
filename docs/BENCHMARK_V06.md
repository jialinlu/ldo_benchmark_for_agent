# EvoLDO-Bench v0.6.1 说明

## 1. 目标与边界

v0.6.1 面向两个近期落地场景：对既有 LDO 架构提出可执行优化建议，以及在固定架构上完成 sizing。纯模型题用于识别模型自身的模拟设计能力；工具题只测同一模型在受控工具处理下的增益，不把 agent 框架能力混入纯模型分数。

公开开发集使用 SKY130 与 ngspice。EDA 集使用 Cadence Virtuoso IC618、OpenAccess/SKILL 和 Spectre，但不包含任何私有 PDK、账号或密码。公开 fixture 的结果不构成硅后性能声明。

## 2. 任务构成

### Pure Model Core：48 题

八个 suite 各六题：

1. 三个 atomic case，诊断单一关键能力；
2. 两个 coupled case，要求处理相互冲突的指标或机制；
3. 一个 existing-architecture optimization capstone，优先判断应局部调整、停止还是改变架构。

八个 suite 为 structure、trend、diagnosis、sizing、migration、system impact、design closure、architecture choice。每题只给完成决策所需的证据，六个客观问题分别覆盖结论、机制、下一步动作、claim boundary、定量或反事实挑战、证据归因。前五题的全部选项均围绕同一 case，不再从同 suite 的其他题拼接不同单位或不同候选名。选项顺序由 task-id 固定随机化，避免答案字母模式。

### Metamorphic companions：8 题

每个 pure suite 选择一个父题，实施内部节点双射改名、证据行倒序与选项重排。物理结论保持不变，用于测表示不变性；companion 不重复计入 core 主分。

### Tool Sizing：6 题

六题分别与六个 pure sizing case 共享 lineage。模型得到有 30 次预算的 `sizer_tool.py`，每次从固定 SKY130 model section 启动全新的 ngspice 进程，保存 candidate、测量与 ledger。正式评分同时要求：

- 答卷语义/候选满足外部 oracle；
- PDK revision 与 model-entry SHA256 匹配；
- 新鲜 ngspice 运行成功并通过 VOUT/IQ 基础硬门槛；
- 任何 `INFRA` 错误均重试，不计模型 0 分。

该 public-development verifier 是最小物理 gate。sealed 版本应增加隐藏 PVT、load transient、stability 和候选 Pareto gate。

### EDA Tool：6+1 题

六个主任务依次测：受控故障归因、只读 OA/SKILL audit、单属性局部写回、真实可见 schematic wire materialization、fresh Spectre measurement、bounded mini closure。另有一个 read-only audit 改名 companion。

正式 verifier 在独立 `/tmp/evoldo-<nonce>` 目录启动 IC618 `-nograph -nocdsinit`。写任务必须 save、close、reopen、readback；连接任务必须同时存在逻辑 net 与可见 wire figure，只有 `dbCreateNet` 不算完成；仿真任务必须生成 fresh run log。已有 VM library 和其他 Virtuoso session 明确不在操作范围内。

## 3. 分数

每个任务满分 100。六问题 pure case 的权重为 16/16/12/12/24/20：

- q1–q4 分别测结论、机制、下一步动作和 claim boundary；
- q5 是场景内定量或反事实挑战，选项按完整推导、合理但漏约束、表面趋势、证据矛盾给 100%/55%/20%/0 等级分；
- q6 要求选出最短决定性证据链，使用集合 F1 计分，选对一部分可得部分分，多选无关证据会降低 precision；
- q1/q2 只有零信用（物理结论完全相反）时才视为关键失败，总分最高 49；部分正确答案保留连续得分，不再被统一压到 49 分。

grader 在每个 check 中同时输出 `weight`、`credit_fraction` 和 `earned`，可直接汇总六个评分维度。建议报告以下互不替代的维度：

| 指标 | 统计集合 |
|---|---|
| Pure Model Core | 48 个 canonical pure tasks |
| Existing Architecture Optimization | 8 个 pure capstones |
| Pure Sizing | 6 个 pure sizing tasks |
| Metamorphic Consistency | 8 对 parent/companion 的一致率与分差 |
| Tool Sizing | 6 个 live-verified sizing tasks |
| EDA Tool | 6 个 primary EDA tasks；companion 单列 |
| Tool Lift | paired tool score − paired pure score |
| Tool Harm | tool score低于 pure score的 pair 比例 |

总体值使用 family macro，避免 companion 或 paired treatment 重复放大家族权重；只看 48 个 canonical core 时，同时报告 task mean 与 suite macro。必须同时给三次 rollout 的均值、标准差、Pass@1 与 95% Wilson 区间，不能只报最好一次。

v0.6.1 不再使用四个二元检查形成的粗分档。一个标准 pure case 在合法答案空间中可形成 500 个以上的最终分值；这只是分辨率下限，不代表难度已经由理论格点证明，正式发布前仍需用独立模型试跑、逐题同分率和天花板率做经验校准。

## 4. 独立性和 token 口径

每模型每题运行三次，rollout seed 为 `base_seed + rollout_index`。每次使用新进程、新 bundle、新 scratch、新工具 ledger；禁止将先前答卷、摘要或人工反馈带入下一次。若 provider 不承诺 seed 确定性，应明确写为 scheduling identifier。

每次 attempt 记录 provider 返回的 input、cached-input、output、reasoning、cache-write token。记录 `first_feasible` 与 `terminal` 的时间/token；terminal 包括成功完成、明确拒答、模型不完整和超时。不可获得的字段为 `null`。基础设施失败 attempt 的 token/cost 保留在 operational effort 中，但恢复后只用有效 attempt 计算能力分。

推荐效率指标包括 tokens/score-point、tokens/pass、score-points/million-tokens、tool calls、wall time、费用，以及 token 测量覆盖率。

## 5. 失败归因

先执行只读 preflight，再开始模型作答。故障分类顺序为：

1. provider/gateway/runner、SSH、license、PDK、ngspice/Spectre executable、模型文件缺失：`INFRA_INVALID`；
2. 可修复的 benchmark contract、deck、parser 或 bridge 错误：修框架、递增 task revision、重新跑受影响答卷；
3. 模型输出格式、推理、候选、SKILL 执行或硬 gate 失败：模型失败。

同一 rollout 的基础设施重试必须保持 task package hash、model id、prompt、seed policy 和预算不变。若 task revision 改变，则原分数全部失效，重新开始三次独立 rollout。v0.6.1 的 task revision 为 2，v0.6.0 答卷不能与之混算。

## 6. 可复现性

`benchmarks/ldo_v06/registry.jsonl` 固定每个 task.toml 与完整 package hash；`manifest.json` 固定任务集合；`public_pdk_manifest.json` 固定 SKY130 revision、model-entry hash 与已验证 ngspice 版本。生成器是 `tools/generate_v06_tasks.py`。

提交前最低验证：

```bash
python3 tools/generate_v06_tasks.py
evoldo-bench validate --registry benchmarks/ldo_v06/registry.jsonl
python3 -m unittest discover -s tests -v
python3 tools/run_self_check.py
```

对工具参考解还需运行 `evoldo-bench verify-live`。无 live backend 的 CI 只能验证结构与静态契约，不能宣称 EDA/tool-sizing 能力分有效。
