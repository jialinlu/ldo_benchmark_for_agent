# EvoLDO-Bench v0.7.0 说明

## 1. 目标

v0.7 回答两个部署问题：

1. 不同模型以及同一模型 4B/9B/27B/35B/122B/397B 等尺寸，在模拟设计自动化流程中分别能可靠完成到哪一层；
2. 同一模型接入冻结模拟设计知识库后，在哪些任务上获得真实增益，代价是多少，是否出现先验覆盖当前证据的负增益。

重点落地场景是已有 LDO 架构优化建议和 sizing：既包括模型纯推理，也为后续 sizing tool、SKY130/ngspice 与 Virtuoso/SKILL 处理保留严格配对接口。

## 2. 构造原则

27 个公开 development case 均由 LDO 工程工作流中的失效类型 clean-room 合成，不复制私有 PDK、已有项目答卷或外部 benchmark 题面。T0/T1 保留必要自包含背景；T2–T4 给出使答案唯一所必需的定义和政策，但不直接给根因或正确操作链，让模型从日志、状态、hash、约束和候选历史恢复中间推理。controlled vocab 的排列经过确定性打乱；集合词表必须包含场景内干扰项，避免 answer-by-position 和“全选即满分”。

公开 case 用于框架开发，不是 sealed exam。正式评测应另造隐藏同构变体，且 public 与 hidden 不共享具体数值、标识符或表面模板。

## 3. 能力矩阵

能力域包括 structure、trend、diagnosis、sizing、migration、system impact、design closure、architecture choice 和 EDA tool reasoning。关键诊断点包括：

- connectivity/CDF → DC OP → cascode/headroom → pass regulation → zero-state startup → STB → quick/full qualification；
- 已有架构建议的当前证据、先验和 controlled experiment 边界；
- exact legal parameter inventory、role-aware sizing reduction、搜索结果解释、callback-aware materialization 和 fresh final；
- multi-corner hard gates、metric-specific worst corner、banked scope 与 artifact consistency；
- Virtuoso OA logical net / visible wire、CDF/netlist、save-close-reopen-readback 和故障分层。

部署层级不等于单题难度标签，而是可落地能力边界。报告必须按 tier 单列均分和通过率，不能只给一个总分。

## 4. 评分

每题 0–100，reference answer 为 100。评分由可复算 deterministic checks 构成：

- 数值误差在 full/zero tolerance 间线性给分；
- 单标签记录分类按正确 key 比例给分，多标签记录按逐记录集合 F1 给分；
- evidence/action 集合用 F1；
- 操作链用 longest-common-subsequence precision/recall F1；
- 关键物理结论错误可把最终分限制到 49。

评分将“答卷不可识别”和“局部字段答错”分开处理。JSON 外壳缺失、必填字段缺失、task ID 错配等使答卷无法安全归属的错误，整次 rollout 记为 `format_fail` 和 0 分；某个已归属字段的类型、受控值或记录成员不合法时，只由引用该字段/记录的 deterministic check 处理，非法部分不获分，其他可验证维度仍保留得分。严格 schema 校验接口仍会拒绝这类字段，评分接口的局部容错不能被解释为 contract-valid。这样既惩罚模型格式错误，也不会让一个局部 JSON 形状错误吞掉整题其他工程判断。

除 family-macro 总分外，报告 suite、level、deployment tier、scoring dimension、Pass@1、三个 rollout 的均值/标准差及 Wilson 区间。正式评测中，一个 tier 的开发准入 gate 为该 tier 三次 rollout 合并后 `mean score >= 70` 且 `Pass@1 >= 2/3`；任一未解决基础设施失败会阻断判定。该 gate 用于筛选“最小候选模型”，仍须通过隐藏同构题和模拟设计专家复核，不能仅按排行榜名次部署。一次 rollout 的校准报告可以显示同一 gate，但必须标注为非正式诊断，不能声称达到可靠性门槛。

## 5. KG 配对协议

KG-off 与 KG-on 必须固定：provider-reported model、任务和 answer-contract hash、rollout/seed、temperature/thinking configuration、timeout 和输出 token 上限。KG-on 的唯一差异是本地冻结检索快照。

任务分三类：

- `benefit_expected`：通用工作流知识应帮助恢复缺失的设计规则；
- `neutral_expected`：纯计算或信息完整任务不应因 KG 明显变化；
- `override_resistant`：当前测量与通用先验冲突时，KG 不得诱导模型越权。

配对报告输出 mean score lift、improvement/harm rate、按三类分组 lift、recall@k、terminal-token delta 和 wall-time delta。KG-on 分数升高但 override-resistant harm 增加，不视为成功。

## 6. 独立性、token 与基础设施

正式结果每模型每处理三次。每次使用新 provider session、空历史、独立 rollout 目录和不同 seed；兼容 API 的 seed 会实际进入 provider 请求，不只用作目录编号。不复用回答、scratch 或 tool ledger。temperature、thinking mode、thinking budget 和输出上限属于模型配置，必须冻结并披露；KG-off/on 对应 rollout 使用相同配置和 seed。

所有终态记录 input、cached input、output、reasoning、cache write、terminal tokens、wall time 和费用；供应商缺字段时为 `null`，不能写 0。每个结果绑定 task manifest、task contract、prompt、全部 input、answer contract 和 oracle hash；runner 同时记录 Git commit、dirty 状态和不泄露内容的 worktree digest。模型自己答错、拒答、无法完成、在足够预算下仍格式失败均进入能力分母；HTTP/网关/登录/runner/框架/模型身份错误修复后用原配置重跑。供应商明确报告的输出预算截断记为 `output_budget_exhausted`，要求重新冻结一个统一且单独标记的充分预算处理，不能把加预算的单题答案拼回旧处理。原失败尝试仍进入运营成本报告。provider output timeout 是冻结的模型参数，重试或配对时不得暗改；若校准证明某模型在统一 timeout 下稳定无法返回，则报告为服务可用性/时延边界，不把它伪装成能力 0 分，也不与改变 timeout 后的结果混排。

完整 KG-off/KG-on 正式矩阵为每模型 `27 × 2 × 3 = 162` 个能力 rollout。若只回答“纯模型不挂 KG 能做什么”，可先运行 `27 × 3 = 81` 个 KG-off rollout；一次 rollout 的开发校准只用于检验题目区分度，不能发布为正式排行榜。

## 7. 无 Web Search 与工具隔离

纯模型两种处理均不注册任何工具。Codex、Kimi、Claude 和兼容 API 的适配器分别执行机器级关闭，日志若观察到任意 tool call 则 `policy_fail`。KG 是 runner 预先生成的固定文件，不是模型的搜索工具。

## 8. 校准准入

首轮校准用 DeepSeek V4 Flash 与 MiniMax M2.5 做跨家族对比，用 Qwen 3.5 4B/9B/27B/35B-A3B/122B-A10B/397B-A17B 做同家族尺寸曲线。只有满足以下条件才冻结 v0.7：

- 基础层不会把弱模型全部压成 0；
- T2–T4 随尺寸呈有意义的能力分化，且强弱模型总分不再密集同分；
- 没有一个 task、长度或格式失败主导排名；
- KG 指标能区分受益、无影响和错误覆盖；
- 两位模拟设计工程师复核物理唯一性和 scoring points。

## 9. 外部方法参考边界

设计过程中参考了[公众号文章](https://mp.weixin.qq.com/s/i4H7Qn13uEhT8mCdRNlvVg)及其链接的 [Razavi-Bench 仓库](https://github.com/Arcadia-1/razavi-bench)对“答卷与评分分离、保存原始输出、三 rollout、双裁判/人工复核、基础层与挑战层分开报告、内容与 rubric hash 固化”的方法讨论。外部仓库明确限制其题面、图片、golden、rubric 与输出被纳入第三方 benchmark；EvoLDO 不复制、改写或迁移这些材料，只采用通用评测工程原则。EvoLDO 的 case 来源、数值、标识符、评分点与实现均独立生成。
