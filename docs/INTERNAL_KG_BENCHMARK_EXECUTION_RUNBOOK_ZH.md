# EvoLDO-Bench 内部服务器 KG-off / KG-on 评分执行手册

版本：1.0

适用 benchmark：EvoLDO-Bench v0.7

目标读者：负责在不可联网内部服务器上执行模型评测的内部 agent

原则：逐关执行；任何 STOP 条件出现时停止，不猜测、不跳过、不覆盖原始结果

## 1. 最终要完成什么

对同一个内部模型执行严格配对的两组实验：

| 处理 | benchmark mode | 模型可见输入 |
|---|---|---|
| KG-off | `direct_reasoning` | 公开 task 文件 |
| KG-on | `knowledge_assisted` | 同一批 task 文件，加逐题冻结的 `kg_retrieval.json` |

正式单模型矩阵为：

```text
27 tasks × 2 treatments × 3 rollouts = 162 capability rollouts
```

基础设施重试不替换、删除或隐藏原始尝试；它们进入运营开销统计，但不额外增加能力分母。

实验最终至少交付：

```text
experiment_declaration.md
environment/
kg_discovery_k20/
kg_formal_k12_a/
kg_formal_k12_b_reviewed/
model_kg_off/
model_kg_on/
reports/kg_off.json
reports/kg_off.md
reports/kg_on.json
reports/kg_on.md
reports/kg_pair_comparison.json
SHA256SUMS
execution_log.md
```

## 2. 不要把“挂载 KG”理解错

本 benchmark 中，模型不能自主调用 MCP，也没有 KG 工具权限。正确流程是：

1. benchmark runner 在任何模型启动前调用只读 KG；
2. 每题生成一份冻结的 `kg_retrieval.json`；
3. 专家审核检索内容并生成 relevance manifest；
4. 正式 KG-on 直接导入审核后的 freeze；
5. 每个 rollout 看到同一道题的同一份检索文件；
6. 正式模型推理期间不再连接 KG。

这是为了确保测到的差异来自“是否增加同一份 KG 知识”，而不是来自模型临时决定调用次数、
网络抖动、KG 数据变化或隐藏工具行为。

为了充分利用 KG，本手册给 KG 预取阶段较宽松的独立预算：

- discovery 候选池：`top_k=20`；
- 正式模型上下文：推荐 `top_k=12`；
- 单次 KG 请求 timeout：300 秒；
- 瞬时连接失败最多 3 次尝试；
- 重试退避 10 秒；
- 每题返回知识正文总量上限 32,000 字符；
- KG 时间不占模型的 420 秒原生答题预算。

不能为了“充分利用”而让模型动态搜索，也不能把 top-k 调到 20 后看模型得分再决定正式 K。
正式 K 必须在运行模型前声明。本手册默认 `FORMAL_TOP_K=12`。

## 3. 角色和权限

内部 agent 可以：

- 在评测负责人自己的可写目录安装和运行 benchmark；
- 调用内部模型 API；
- 调用已经验收的只读 KG sidecar；
- 写入评测输出、日志和报告；
- 读取 benchmark 的 oracle 进行 runner 侧评分。

内部 agent 不可以：

- 修改领导 KG 仓库或部署目录；
- 修改 benchmark task、oracle、answer template 或 registry；
- 把 oracle、参考答案或历史模型答案提供给答题模型；
- 把 benchmark 题目或专家标签写回 KG；
- 在正式实验中启用 Web、browser、shell、MCP 或其他模型工具；
- 删除失败 rollout；
- 在同一输出目录覆盖重跑；
- 为 KG-on 单独增加模型思考预算、输出预算或答题时限；
- 在看到模型分数后改变 top-k、query、检索方法或知识正文。

代码读权限不等于 KG 数据快照权限。正式 KG-on 还必须具备已验收的 snapshot manifest、
只读 sidecar 和 reviewed freeze。缺少任何一个都只能做 smoke test，不能发布正式结论。

## 4. 一次性路径准备

所有路径必须是实施者自己的可写绝对路径。不要使用领导仓库作为运行目录。

先填写以下变量。尖括号内容必须替换；不能原样执行：

```bash
export WRITABLE_ROOT=<实施者的可写绝对根目录>
export BENCH_ROOT="$WRITABLE_ROOT/ldo_benchmark_for_agent"
export EVAL_ROOT="$WRITABLE_ROOT/evoldo_eval/<模型短名>_<日期>"
export BENCH_VENV="$WRITABLE_ROOT/venvs/evoldo-bench-v07"
export MODEL_BASE_URL=http://<内部模型网关主机>:<端口>/v1
export MODEL_ID='<内部 API 接受的精确模型 ID>'
export MODEL_API_KEY_ENV=EVOLDO_INTERNAL_MODEL_API_KEY
export KG_CONFIG="$WRITABLE_ROOT/kg_benchmark_release/config/mcp_kg_config.json"
export KG_SNAPSHOT="$WRITABLE_ROOT/kg_benchmark_release/snapshot/kg_snapshot_manifest.json"
export KG_RELEVANCE="$WRITABLE_ROOT/kg_benchmark_release/review/kg_relevance_manifest.json"
export FORMAL_TOP_K=12
export BASE_SEED=2026
export ROLLOUTS=3
```

检查变量：

```bash
set -u
test -d "$BENCH_ROOT"
test -r "$BENCH_ROOT/benchmarks/ldo_v07/registry.jsonl"
test -n "$EVAL_ROOT"
test -n "$MODEL_BASE_URL"
test -n "$MODEL_ID"
test "$FORMAL_TOP_K" -eq 12
test "$ROLLOUTS" -eq 3
```

模型密钥必须由人工在受控环境中注入。只检查它存在，不打印：

```bash
test -n "${EVOLDO_INTERNAL_MODEL_API_KEY:-}"
```

STOP 条件：

- 路径仍含 `<实施者>`、`<端口>` 等占位符；
- 模型密钥不存在；
- `BENCH_ROOT` 指向领导 KG 仓库；
- `EVAL_ROOT` 已存在且非空；
- 模型 ID 只是昵称，不能映射到 provider 返回的真实 ID。

创建输出目录：

```bash
mkdir -p "$EVAL_ROOT/environment" "$EVAL_ROOT/logs" "$EVAL_ROOT/reports"
```

任何正式 treatment 的输出子目录都不要预先放文件。runner 要求输出不存在或为空。

## 5. 固化 benchmark 软件

### 5.1 记录源码身份

如果交付物是 Git 仓库：

```bash
git -C "$BENCH_ROOT" rev-parse HEAD \
  > "$EVAL_ROOT/environment/benchmark_git_revision.txt"
git -C "$BENCH_ROOT" status --porcelain \
  > "$EVAL_ROOT/environment/benchmark_git_status.txt"
```

如果 `benchmark_git_status.txt` 非空，必须确认这些正是经过审核的 KG 适配改动，并把完整目录
作为 release 归档后再运行。不能让内部 agent临时修改代码。

生成本次实际使用源码的内容清单：

```bash
cd "$BENCH_ROOT"
find src tools schemas benchmarks/ldo_v07 docs \
  -type f -print0 | sort -z | xargs -0 sha256sum \
  > "$EVAL_ROOT/environment/benchmark_files.sha256"
```

### 5.2 创建离线虚拟环境

```bash
python3 -m venv "$BENCH_VENV"
"$BENCH_VENV/bin/python" -m pip install \
  --no-deps --no-build-isolation -e "$BENCH_ROOT"
```

确认加载的是指定路径：

```bash
"$BENCH_VENV/bin/python" -c \
  'import evoldo_bench, pathlib; print(pathlib.Path(evoldo_bench.__file__).resolve())' \
  > "$EVAL_ROOT/environment/imported_evoldo_bench_path.txt"
```

输出路径必须位于 `$BENCH_ROOT/src/evoldo_bench`，否则 STOP。

记录软件环境：

```bash
"$BENCH_VENV/bin/python" --version \
  > "$EVAL_ROOT/environment/python_version.txt"
"$BENCH_VENV/bin/python" -m pip freeze \
  > "$EVAL_ROOT/environment/python_freeze.txt"
uname -a > "$EVAL_ROOT/environment/uname.txt"
```

## 6. Benchmark 原生自检

以下命令全部必须退出 0：

```bash
cd "$BENCH_ROOT"

"$BENCH_VENV/bin/python" -m evoldo_bench.cli list --json \
  > "$EVAL_ROOT/logs/task_inventory.json"

"$BENCH_VENV/bin/python" -m evoldo_bench.cli validate \
  --registry benchmarks/ldo_v07/registry.jsonl \
  > "$EVAL_ROOT/logs/validate.json"

"$BENCH_VENV/bin/python" -m evoldo_bench.cli audit \
  --output "$EVAL_ROOT/logs/audit.json"

PYTHONPATH=src "$BENCH_VENV/bin/python" -m unittest discover -s tests -v \
  > "$EVAL_ROOT/logs/unittest.stdout.log" \
  2> "$EVAL_ROOT/logs/unittest.stderr.log"

PYTHONPATH=src "$BENCH_VENV/bin/python" tools/run_self_check.py \
  > "$EVAL_ROOT/logs/self_check.json"
```

必须核对：

- inventory 为 27 道 v0.7 reasoning task；
- validate `passed=true`；
- registry row_count=27；
- audit `passed=true`；
- unit tests 无失败；
- self-check `passed=true` 且 reference score=100。

任一失败都 STOP。不要改题目或 oracle 来让测试通过。

## 7. 固化模型配置

### 7.1 推荐内部 OpenAI-compatible 适配器

内部模型通常使用 OpenAI-compatible API。本手册后续命令使用：

```text
tools/model_agent_adapter.py --agent openai-compatible
```

正式推荐初始预算：

- 外层每题 timeout：使用 task 原生 420 秒；
- adapter 内层会保留约 15 秒清理时间；
- `max-output-tokens=16384`；
- temperature=0；
- provider seed 由 rollout seed 提供；
- tools 为空；
- Web Search 禁止。

如果内部模型不接受 `temperature`，统一改成 `--omit-temperature`。如果支持固定 thinking budget，
可以在 smoke test 阶段选择例如 `--thinking-budget 32768`，但 KG-off 和 KG-on 必须逐字一致。
不能一个 treatment 开 thinking，另一个 treatment 关闭。

输出 token 上限不足并出现 `finish_reason=length` 时，不允许只补跑单题；必须提高上限后把两组
正式 treatment 全部作为一个新的预算版本重跑。

### 7.2 单题模型连通性 smoke test

smoke 输出不能复用为正式成绩：

```bash
cd "$BENCH_ROOT"

"$BENCH_VENV/bin/python" -m evoldo_bench.cli experiment \
  --tasks-root benchmarks/ldo_v07/tasks \
  --oracle-root benchmarks/ldo_v07/dev_reference/oracles \
  --output "$EVAL_ROOT/model_smoke_direct" \
  --model-id "$MODEL_ID" \
  --mode direct_reasoning \
  --rollouts 1 \
  --base-seed "$BASE_SEED" \
  --task-id v07-foundation-01-feedback-trace \
  --paired-modes direct_reasoning,knowledge_assisted \
  -- \
  "$BENCH_VENV/bin/python" "$BENCH_ROOT/tools/model_agent_adapter.py" \
  --agent openai-compatible \
  --model "$MODEL_ID" \
  --base-url "$MODEL_BASE_URL" \
  --api-key-env "$MODEL_API_KEY_ENV" \
  --max-output-tokens 16384 \
  --temperature 0
```

检查：

```bash
"$BENCH_VENV/bin/python" -m json.tool \
  "$EVAL_ROOT/model_smoke_direct/experiment_manifest.json" \
  > "$EVAL_ROOT/logs/model_smoke_manifest.pretty.json"
```

必须确认：

- run_count=1；
- 没有 provider/runner timeout；
- provider-reported model ID 与申请的模型一致；
- `requested_model_parameters` 完整；
- `tool_calls=0`；
- 没有 Web/tool policy failure；
- 回答产生可评分结果。

若 temperature 或 thinking 参数被 API 拒绝，只允许在 smoke 阶段调整。调整完成后，把最终完整
adapter 参数写入 `experiment_declaration.md`，此后不得改变。

### 7.3 其他原生 adapter

如果内部服务器使用 CLI agent，可把后续命令的 adapter 尾部替换为：

```text
Codex:  --agent codex --model <exact-id> --containerized
Kimi:   --agent kimi --model <exact-id> --containerized
Claude: --agent claude --model <exact-id> --containerized --claude-settings <只读设置文件>
```

只有 Docker 镜像、CLI 版本、认证文件和断网条件全部验收后才能用 containerized 路线。
一次正式配对实验只能选择一种 adapter 路线。

## 8. 写实验声明，先声明后跑分

在 `experiment_declaration.md` 中至少写明：

```text
benchmark source SHA/revision:
task registry SHA:
oracle store SHA:
model requested ID:
provider-reported ID from smoke:
model endpoint identity:
adapter type and absolute path:
temperature or omit-temperature:
thinking mode/budget:
max output tokens:
task timeout:
rollouts: 3
base seed: 2026
paired modes: direct_reasoning,knowledge_assisted
KG snapshot ID/SHA:
KG retrieval method:
KG discovery top-k: 20
KG formal top-k: 12
KG request timeout: 300
KG attempts/backoff: 3/10s
KG text cap: 32000 chars
execution order:
reserved server window:
operator:
```

然后记录 registry SHA：

```bash
sha256sum "$BENCH_ROOT/benchmarks/ldo_v07/registry.jsonl" \
  > "$EVAL_ROOT/environment/registry.sha256"
```

不要把 API key 写进声明、命令历史、日志或配置文件。

## 9. KG sidecar 验收

### 9.1 文件验收

```bash
test -r "$KG_CONFIG"
test -r "$KG_SNAPSHOT"
"$BENCH_VENV/bin/python" -m json.tool "$KG_CONFIG" \
  > "$EVAL_ROOT/logs/mcp_kg_config.pretty.json"
"$BENCH_VENV/bin/python" -m json.tool "$KG_SNAPSHOT" \
  > "$EVAL_ROOT/logs/kg_snapshot_manifest.pretty.json"
```

MCP 配置正式推荐值：

```json
{
  "schema_version": "1.0",
  "transport": "sse",
  "endpoint": "http://127.0.0.1:8702/sse",
  "tool_name": "benchmark_retrieve",
  "retrieval_method": "lucene_fulltext",
  "query_profile": "title_capabilities_scenario_v1",
  "protocol_version": "2024-11-05",
  "request_timeout_seconds": 300,
  "max_response_bytes": 2097152,
  "max_entry_text_chars": 12000,
  "max_total_text_chars": 32000,
  "max_retrieval_attempts": 3,
  "retry_backoff_seconds": 10,
  "allow_non_loopback": false,
  "headers_from_env": {}
}
```

不要在该 JSON 中写 API key、password 或 token。

### 9.2 服务验收

根据 KG 开发规范检查：

- `/health` snapshot ID/SHA 与 manifest 一致；
- `tools/list` 只有 `benchmark_retrieve`；
- 隐藏写工具调用被拒绝；
- Neo4j 是独立只读 snapshot；
- service source archive、upstream revision 和 dump SHA 已记录；
- 污染审计通过；
- deterministic gate 通过；
- 没有修改或重启领导生产服务。

缺少 snapshot manifest、dump identity、污染报告或只读证明时 STOP。

## 10. 生成 K=20 discovery 检索池

该阶段不启动模型：

```bash
cd "$BENCH_ROOT"

"$BENCH_VENV/bin/python" -m evoldo_bench.cli kg-preflight \
  --tasks-root benchmarks/ldo_v07/tasks \
  --output "$EVAL_ROOT/kg_discovery_k20" \
  --knowledge-mcp-config "$KG_CONFIG" \
  --knowledge-snapshot-manifest "$KG_SNAPSHOT" \
  --knowledge-top-k 20 \
  > "$EVAL_ROOT/logs/kg_discovery_k20.stdout.json" \
  2> "$EVAL_ROOT/logs/kg_discovery_k20.stderr.log"
```

最长理论等待不能按普通命令 timeout 粗暴杀掉：27 题 × 每题最多 3 次 × 每次 300 秒，另加退避。
实际本地 Lucene 应远小于该上限。执行期间可以监控进程和日志，但不能修改输出文件。

完成后检查：

```bash
"$BENCH_VENV/bin/python" -m json.tool \
  "$EVAL_ROOT/kg_discovery_k20/knowledge_freeze_manifest.json" \
  > "$EVAL_ROOT/logs/kg_discovery_k20_manifest.pretty.json"
```

必须满足：

- task_count=27；
- top_k=20；
- backend=`external_mcp_sse`；
- snapshot ID/SHA 正确；
- 每题都有 raw response 和 normalized retrieval；
- query profile=`title_capabilities_scenario_v1`；
- 不包含 catalogs、oracle 或答案；
- 没有模型进程；
- 所有瞬时重试均在 manifest 中留下 attempt count。

若 preflight 最终失败：保留失败目录和日志，不在原目录继续写；处理基础设施原因后，使用新的
`kg_discovery_k20_retry_N` 空目录完整重跑。

## 11. 专家相关性标注

把 `kg_discovery_k20/tasks/<task_id>/kg_retrieval.json` 交给两名模拟电路专家独立审阅。
不能把模型答案或模型得分交给专家。

专家判断“该知识是否是解决此题有帮助的通用先验”，然后仲裁分歧。最终 relevance manifest：

```json
{
  "schema_version": "1.0",
  "source_snapshot_sha256": "<与 KG snapshot 完全相同>",
  "tasks": {
    "<task-id-1>": ["<relevant-stable-id>"],
    "<task-id-2>": []
  }
}
```

要求：

- 27 个正式 task ID 全部出现；
- 没有相关项的题写 `[]`，不能省略；
- ID 必须来自同一 snapshot 的 K=20 pool；
- 不复用 benchmark clean-room KG oracle 中的 ID；
- manifest 不进入模型 prompt；
- 另存标注人、时间、规则版本和仲裁记录。

内部 agent 只能检查格式和覆盖率，不能替代专家决定知识是否相关。

## 12. 生成并复核正式 K=12 freeze

### 12.1 第一次正式 preflight

```bash
test -r "$KG_RELEVANCE"

cd "$BENCH_ROOT"
"$BENCH_VENV/bin/python" -m evoldo_bench.cli kg-preflight \
  --tasks-root benchmarks/ldo_v07/tasks \
  --output "$EVAL_ROOT/kg_formal_k12_a" \
  --knowledge-mcp-config "$KG_CONFIG" \
  --knowledge-snapshot-manifest "$KG_SNAPSHOT" \
  --knowledge-relevance-manifest "$KG_RELEVANCE" \
  --knowledge-top-k "$FORMAL_TOP_K" \
  > "$EVAL_ROOT/logs/kg_formal_k12_a.stdout.json" \
  2> "$EVAL_ROOT/logs/kg_formal_k12_a.stderr.log"
```

### 12.2 第二次独立确定性复核

必须使用新的空目录：

```bash
"$BENCH_VENV/bin/python" -m evoldo_bench.cli kg-preflight \
  --tasks-root benchmarks/ldo_v07/tasks \
  --output "$EVAL_ROOT/kg_formal_k12_b_reviewed" \
  --knowledge-mcp-config "$KG_CONFIG" \
  --knowledge-snapshot-manifest "$KG_SNAPSHOT" \
  --knowledge-relevance-manifest "$KG_RELEVANCE" \
  --knowledge-top-k "$FORMAL_TOP_K" \
  > "$EVAL_ROOT/logs/kg_formal_k12_b.stdout.json" \
  2> "$EVAL_ROOT/logs/kg_formal_k12_b.stderr.log"
```

逐题比较两次 `retrieval_sha256`。必须全部相同。`created_at` 和请求耗时可以不同，不比较整个
freeze manifest 的文件 SHA：

```bash
"$BENCH_VENV/bin/python" - "$EVAL_ROOT/kg_formal_k12_a" \
  "$EVAL_ROOT/kg_formal_k12_b_reviewed" <<'PY'
import json, pathlib, sys

def rows(root):
    value = json.loads((pathlib.Path(root) / "knowledge_freeze_manifest.json").read_text())
    return {row["task_id"]: row["retrieval_sha256"] for row in value["rows"]}

left, right = rows(sys.argv[1]), rows(sys.argv[2])
if left != right:
    missing = sorted(set(left) ^ set(right))
    changed = sorted(key for key in set(left) & set(right) if left[key] != right[key])
    raise SystemExit("KG retrieval is not deterministic; missing=%r changed=%r" % (missing, changed))
print("PASS: 27 task retrieval hashes are identical")
PY
```

正式模型实验只使用 `kg_formal_k12_b_reviewed`。不要再查询一次 KG 代替它。

## 13. 执行原生 KG-off 基线

预留不受其他重负载任务干扰的窗口。该 runner 当前顺序执行 81 个 rollout，不要并发启动另一组
模型实验。

```bash
cd "$BENCH_ROOT"

"$BENCH_VENV/bin/python" -m evoldo_bench.cli experiment \
  --tasks-root benchmarks/ldo_v07/tasks \
  --oracle-root benchmarks/ldo_v07/dev_reference/oracles \
  --output "$EVAL_ROOT/model_kg_off" \
  --model-id "$MODEL_ID" \
  --mode direct_reasoning \
  --rollouts "$ROLLOUTS" \
  --base-seed "$BASE_SEED" \
  --paired-modes direct_reasoning,knowledge_assisted \
  -- \
  "$BENCH_VENV/bin/python" "$BENCH_ROOT/tools/model_agent_adapter.py" \
  --agent openai-compatible \
  --model "$MODEL_ID" \
  --base-url "$MODEL_BASE_URL" \
  --api-key-env "$MODEL_API_KEY_ENV" \
  --max-output-tokens 16384 \
  --temperature 0 \
  > "$EVAL_ROOT/logs/model_kg_off.stdout.json" \
  2> "$EVAL_ROOT/logs/model_kg_off.stderr.log"
```

不要在命令中加 KG 配置。KG-off 不应该创建 `frozen_knowledge`。

完成后先检查 manifest，不要马上删日志：

```bash
"$BENCH_VENV/bin/python" -m json.tool \
  "$EVAL_ROOT/model_kg_off/experiment_manifest.json" \
  > "$EVAL_ROOT/logs/model_kg_off_manifest.pretty.json"
```

要求：

- task_count=27；
- run_count=81；
- mode=`direct_reasoning`；
- rollouts_per_task=3；
- base_seed=2026；
- pairing_modes 同时包含 direct 和 knowledge；
- knowledge_freeze=null；
- 每行 tool_calls=0；
- provider-reported ID 不 mismatch。

模型答错、拒答、格式错误和 policy failure 是能力结果，不得人工重跑。只有 provider、gateway、
runner timeout、模型身份异常等基础设施状态进入恢复流程。

## 14. 执行 KG-on

KG-on 使用与 KG-off 完全相同的模型命令和模型预算，唯一 intended difference 是冻结知识上下文：

```bash
cd "$BENCH_ROOT"

"$BENCH_VENV/bin/python" -m evoldo_bench.cli experiment \
  --tasks-root benchmarks/ldo_v07/tasks \
  --oracle-root benchmarks/ldo_v07/dev_reference/oracles \
  --output "$EVAL_ROOT/model_kg_on" \
  --model-id "$MODEL_ID" \
  --mode knowledge_assisted \
  --rollouts "$ROLLOUTS" \
  --base-seed "$BASE_SEED" \
  --paired-modes direct_reasoning,knowledge_assisted \
  --knowledge-freeze-dir "$EVAL_ROOT/kg_formal_k12_b_reviewed" \
  --knowledge-top-k "$FORMAL_TOP_K" \
  -- \
  "$BENCH_VENV/bin/python" "$BENCH_ROOT/tools/model_agent_adapter.py" \
  --agent openai-compatible \
  --model "$MODEL_ID" \
  --base-url "$MODEL_BASE_URL" \
  --api-key-env "$MODEL_API_KEY_ENV" \
  --max-output-tokens 16384 \
  --temperature 0 \
  > "$EVAL_ROOT/logs/model_kg_on.stdout.json" \
  2> "$EVAL_ROOT/logs/model_kg_on.stderr.log"
```

该命令正式推理期间不会连接 MCP。导入时会重新验证：

- task 集合；
- config 和 snapshot manifest SHA；
- snapshot ID/SHA；
- query profile、query SHA、method 和 top-k；
- raw response 与 normalized retrieval 的逐字段关系；
- retrieval/raw 文件 SHA；
- returned IDs；
- relevance manifest SHA 和逐题覆盖；
- 重新计算的 recall@k/precision@k；
- symlink。

完成后要求：

- task_count=27；
- run_count=81；
- mode=`knowledge_assisted`；
- knowledge_freeze backend=`external_mcp_sse`；
- imported_from_preflight=true；
- top_k=12；
- 每个 rollout 的模型工具调用仍为 0；
- 同一道题三个 rollout 的 knowledge context SHA 相同。

## 15. 只恢复基础设施失败

### 15.1 判断是否需要恢复

如果 manifest `capability_complete=true`，不运行 recovery。

如果为 false，分别对 KG-off 或 KG-on 创建新的 recovery 输出目录。第一次恢复示例：

```bash
"$BENCH_VENV/bin/python" -m evoldo_bench.cli recover-experiment \
  --source "$EVAL_ROOT/model_kg_off" \
  --output "$EVAL_ROOT/model_kg_off_recovered" \
  --tasks-root "$BENCH_ROOT/benchmarks/ldo_v07/tasks" \
  --oracle-root "$BENCH_ROOT/benchmarks/ldo_v07/dev_reference/oracles" \
  --max-infrastructure-retries 5 \
  --retry-backoff-seconds 10 \
  -- \
  "$BENCH_VENV/bin/python" "$BENCH_ROOT/tools/model_agent_adapter.py" \
  --agent openai-compatible \
  --model "$MODEL_ID" \
  --base-url "$MODEL_BASE_URL" \
  --api-key-env "$MODEL_API_KEY_ENV" \
  --max-output-tokens 16384 \
  --temperature 0
```

KG-on 同理，只替换 source/output。recovery 会复制并验证 frozen knowledge，不会重新访问 KG。

若 recovery 进程中断，使用同一个 recovery output，并增加 `--resume`；不要重新执行首次恢复命令。

禁止恢复：

- 普通答错；
- model_incomplete；
- format_fail；
- policy_fail；
- 已产生可评分但低分的回答。

若出现 `output_budget_exhausted`，STOP。它不是可在旧 treatment 内恢复的基础设施失败。

后续报告和比较必须使用 capability complete 的最终目录：没有 recovery 就用原始目录，有 recovery
就用 recovered 目录。把实际路径记录为 `ACTIVE_KG_OFF` 和 `ACTIVE_KG_ON`：

```bash
export ACTIVE_KG_OFF="$EVAL_ROOT/model_kg_off"
export ACTIVE_KG_ON="$EVAL_ROOT/model_kg_on"
```

如发生恢复，人工把对应变量改为 recovered 路径。

## 16. 生成单组评分报告

```bash
"$BENCH_VENV/bin/python" -m evoldo_bench.cli experiment-report \
  "$ACTIVE_KG_OFF" \
  --output "$EVAL_ROOT/reports/kg_off.json" \
  --markdown "$EVAL_ROOT/reports/kg_off.md" \
  > "$EVAL_ROOT/logs/kg_off_report.stdout.json"

"$BENCH_VENV/bin/python" -m evoldo_bench.cli experiment-report \
  "$ACTIVE_KG_ON" \
  --output "$EVAL_ROOT/reports/kg_on.json" \
  --markdown "$EVAL_ROOT/reports/kg_on.md" \
  > "$EVAL_ROOT/logs/kg_on_report.stdout.json"
```

如果仍有未解决基础设施行，命令会拒绝生成 capability report。这是正确行为，不要绕过。

## 17. 生成严格配对比较

baseline manifest 必须放在第一个参数：

```bash
"$BENCH_VENV/bin/python" -m evoldo_bench.cli compare-treatments \
  "$ACTIVE_KG_OFF/experiment_manifest.json" \
  "$ACTIVE_KG_ON/experiment_manifest.json" \
  > "$EVAL_ROOT/reports/kg_pair_comparison.json"
```

必须确认顶层：

```text
passed = true
baseline_mode = direct_reasoning
paired_rows = 81
modes = [direct_reasoning, knowledge_assisted]
violations = []
```

若 `passed=false`，不能自行解释 lift。根据 violation 修复：

| violation | 含义 | 处理 |
|---|---|---|
| MODEL_MISMATCH | 两组 model_id 不同 | 两组重新按同一模型运行 |
| MODEL_PARAMETER_MISMATCH | temperature/thinking/output timeout 等不同 | 冻结统一配置后两组重跑 |
| ROLLOUT_MATRIX_MISMATCH | 题目、rollout 或 seed 不一致 | 两组完整矩阵重跑 |
| CONTROL_MISMATCH | task/oracle/budget/hash 漂移 | 恢复同一 benchmark release 后重跑 |
| UNRESOLVED_INFRASTRUCTURE | 仍有基础设施失败 | 只走 recovery |

比较报告重点读取：

- mean score delta；
- improvement rate；
- harm rate；
- benefit_expected / neutral_expected / override_resistant 分层；
- terminal token delta；
- model wall-time delta；
- retrieval recall@12 / precision@12；
- KG materialization time。

KG materialization time 是预取运营成本，不是模型 wall-time。不要把 discovery K=20 和两次确定性
preflight 的时间算进单次在线推理延迟；可以另列为“评测准备成本”。

## 18. 最终一致性审计

逐项打勾：

- [ ] benchmark 自检全部退出 0；
- [ ] 27 道题且 registry hash 已记录；
- [ ] 精确 model ID 和 provider-reported ID 已记录；
- [ ] 两组 adapter 命令除 mode/KG 参数外完全相同；
- [ ] 两组都是 3 rollout、base seed 2026；
- [ ] 两组模型 timeout 和 output/reasoning budget 相同；
- [ ] 模型没有 Web、browser、shell、MCP 或其他工具；
- [ ] KG snapshot、sidecar 和污染报告均验收；
- [ ] K=20 discovery 在模型运行前完成；
- [ ] 相关性标签覆盖 27 题；
- [ ] 两次正式 K=12 retrieval SHA 逐题一致；
- [ ] KG-on 导入 reviewed freeze，推理时没有重新查询 KG；
- [ ] 每组 capability complete；
- [ ] 恢复只针对基础设施失败；
- [ ] compare-treatments passed=true 且 violations=[]；
- [ ] 原始失败尝试和日志全部保留；
- [ ] 未修改领导仓库或生产服务；
- [ ] 最终 SHA256SUMS 已生成。

生成交付清单：

```bash
cd "$EVAL_ROOT"
find environment logs reports \
  kg_discovery_k20 kg_formal_k12_a kg_formal_k12_b_reviewed \
  -type f -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS
```

模型实验目录通常较大；如果也要封存，在 SHA256SUMS 命令中追加 `$ACTIVE_KG_OFF` 和
`$ACTIVE_KG_ON` 对应的相对目录名。

## 19. 预计时间与资源

单线程最坏上界不要当作正常耗时，但要用于调度窗口：

```text
KG discovery: 27 × 3 attempts × 300s + backoff
KG formal A:  27 × 3 attempts × 300s + backoff
KG formal B:  27 × 3 attempts × 300s + backoff
模型 KG-off: 81 × 420s outer ceiling
模型 KG-on:  81 × 420s outer ceiling
```

正常本地 Lucene 检索应远快于 timeout。不要因为 timeout 设置充分就人为 sleep，也不要并发请求
压垮 KG。模型两组建议在同一保留窗口顺序执行，期间停止无关重负载任务并记录系统异常。

## 20. 必须停止并上报的情况

出现以下任一情况，内部 agent 立即停止后续阶段，在 `execution_log.md` 记录命令、时间、退出码和
最后 200 行错误日志：

- benchmark validate/audit/test/self-check 失败；
- 领导仓库需要写权限才能继续；
- 无法取得可验证的 KG snapshot identity；
- KG sidecar 暴露写工具；
- 污染审计或确定性测试失败；
- discovery/reviewed freeze 任务数不是 27；
- 两次正式 K=12 retrieval SHA 不一致；
- relevance manifest 缺题或绑定其他 snapshot；
- provider-reported model ID mismatch；
- 模型工具调用非零；
- 两组模型参数不一致；
- output budget exhausted；
- recovery 次数耗尽；
- compare-treatments `passed=false`；
- 任何人要求删除失败样本或只挑最好 rollout。

上报时不要提供 API key。不要自行降低验收门槛。

## 21. 内部 agent 最终回复模板

内部 agent 完成后必须按以下结构回复：

```text
1. 状态：COMPLETE / BLOCKED
2. benchmark revision 和文件清单 SHA：
3. model requested/provider-reported ID：
4. 冻结模型参数：
5. KG snapshot ID/SHA：
6. KG sidecar revision/upstream revision：
7. discovery K=20：task_count、耗时、重试数：
8. formal K=12：两次逐题 SHA 是否一致：
9. relevance：覆盖题数、专家审核文件 SHA：
10. KG-off：run_count、状态分布、是否 recovery：
11. KG-on：run_count、状态分布、是否 recovery：
12. compare-treatments：passed、violations：
13. 核心分数：off、on、delta、improvement rate、harm rate：
14. 三类 knowledge expectation 的 delta/harm：
15. token/time/KG retrieval 指标：
16. 输出目录绝对路径：
17. SHA256SUMS 路径：
18. 未修改领导仓库和服务的确认：
19. 所有执行命令及退出码：
20. 已知限制或阻塞：
```

不能只回复“跑完了”“效果提升了”或发送截图。正式结论必须以 JSON manifest、配对验证和哈希
为依据。
