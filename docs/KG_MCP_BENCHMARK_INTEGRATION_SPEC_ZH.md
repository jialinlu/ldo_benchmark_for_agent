# EvoLDO-Bench × 内部 KG/MCP 接入开发规范

版本：1.0-draft

日期：2026-08-20

适用范围：EvoLDO-Bench v0.7.0、内部 Neo4j KG、SSE MCP 服务

目标读者：KG 服务开发者、benchmark 开发者、内部部署工程师、评测负责人、模拟电路专家

## 1. 文档目的

本文是 KG 侧实现、冻结、交付和验收的完整工程合同。它不是架构建议，也不是可选优化清单。凡标记为“必须”的要求，未满足时不得启动正式 KG-off/KG-on 模型实验。

本次评测要回答的唯一主问题是：

> 在模型、题目、seed、temperature、thinking、timeout 和输出预算全部保持不变时，给模型增加一份由内部 KG 产生的冻结通用知识上下文，模型在 EvoLDO-Bench 上的能力是否提高，是否产生错误覆盖，以及代价是多少？

KG 不作为模型可自主调用的工具。MCP 只由 benchmark runner 在模型启动前调用。模型实际看到的是只读 `context/kg_retrieval.json`，看不到 MCP endpoint、Neo4j 凭据、写工具或生产数据库。

## 2. 已实现的 benchmark 侧能力

benchmark 仓库已经完成以下功能：

1. 外部 KG MCP SSE 客户端；
2. `benchmark_retrieve` 唯一工具白名单；
3. MCP 配置严格校验；
4. KG 快照 manifest 严格校验；
5. 查询、快照、方法、top-k 和返回 ID 的强绑定；
6. 原始 MCP 响应与标准化检索文件同时保存；
7. 在任何模型调用前预先冻结全部题目的检索结果；
8. `kg-preflight` 无模型预检索流程；
9. 正式实验直接导入已审阅 preflight 目录，不再次访问 KG；
10. 外部 KG 专属 relevance manifest 和 recall@k/precision@k；
11. KG 上下文在基础设施重试时保持逐字节不变；
12. KG 检索耗时与模型推理耗时分开记录；
13. 模型侧继续保持 `max_tool_calls=0`、空 tools 和无 MCP 配置。

主要实现位置：

- `src/evoldo_bench/external_kg.py`
- `src/evoldo_bench/experiment.py`
- `src/evoldo_bench/knowledge.py`
- `src/evoldo_bench/recovery.py`
- `src/evoldo_bench/cli.py`
- `schemas/kg-mcp-config-v1.schema.json`
- `schemas/kg-snapshot-manifest-v1.schema.json`
- `schemas/kg-external-retrieval-v1.schema.json`
- `schemas/kg-relevance-manifest-v1.schema.json`
- `tests/test_external_kg.py`

## 3. 最终系统边界

```text
生产 KG / 持续注入管道
        |
        | 仅在冻结阶段复制；正式实验期间不连接生产库
        v
Neo4j dump + service source archive + qualification reports
        |
        | 恢复到独立 benchmark KG 实例
        v
只读 Neo4j snapshot instance
        |
        v
专用只读 MCP endpoint
  只暴露 benchmark_retrieve
        |
        | kg-preflight，每题一次固定检索
        v
reviewed_kg_freeze/
  tasks/<task_id>/kg_retrieval.json
  tasks/<task_id>/kg_mcp_raw_response.json
  knowledge_freeze_manifest.json
        |
        | 人工审阅、相关性标注、哈希复核
        v
正式 knowledge_assisted experiment
        |
        | 每个 rollout 复制同一个 kg_retrieval.json
        v
模型 prompt；模型无工具、无 KG 网络访问
```

### 3.1 明确禁止的架构

- 模型直接连接生产 Neo4j；
- 模型自主决定何时检索、检索次数或调用哪个 MCP tool；
- KG-off 使用一组模型参数而 KG-on 使用另一组参数；
- 正式模型实验过程中继续向 KG 注入数据；
- preflight 审阅一份结果，正式实验重新查询另一份结果；
- 用正则表达式解析现有 `search_concepts` 人类可读文本；
- 根据 `source_book` 猜测不存在的 URI；
- 把 benchmark 题面、答案、oracle 或专家标注写回 KG；
- 用正在运行的 Neo4j 物理文件散列冒充原子快照；
- 使用过期的 `migration_data/nodes.json` 或 `edges.json` 代替正式数据库快照。

### 3.2 权限边界：不得修改领导仓库

实施者只有领导 KG 代码的读权限，没有该仓库或原部署路径的写权限。本规范据此采用以下
强制边界：

- 不在领导仓库创建、修改、删除、格式化或提交任何文件；
- 不在领导服务目录创建虚拟环境、缓存、日志、PID、配置或测试产物；
- 不对领导仓库执行 `git checkout`、`git switch`、`git clean`、`git stash`、`git commit`；
- 不停止、重启或替换领导正在运行的 KG 服务；
- 不要求领导为本次 benchmark 合并代码；
- 所有适配代码、虚拟环境、配置、日志、快照和 systemd user unit 都放在实施者自己的可写目录；
- 上游仓库只作为只读、带 commit 身份的输入。

推荐目录边界如下：

```text
$KG_BENCH_WORK/                               # 实施者可写的绝对目录
├── upstream_archive/                         # 从只读仓库导出的固定 commit
├── sidecar_src/                              # 独立适配服务源码
├── venv/                                     # 独立 Python 环境
├── config/                                   # 无明文秘密的配置
├── snapshot/                                 # 经授权取得的 dump/manifest
├── runtime/                                  # 独立 Neo4j 或代理运行目录
├── logs/
└── releases/

<领导 KG 仓库>                               # 全程只读
<领导生产服务目录>                           # 全程只读，不作为运行目录
```

首选实现是“实施者目录中的固定上游副本 + 独立 benchmark sidecar”：先从领导仓库的某个
明确 commit 生成只读归档，再在自己的目录中建立独立适配工程。内部 agent 修改的是该副本或
sidecar，绝不是领导仓库。正式服务也从实施者自己的 release archive 启动。

参考操作，其中路径必须替换为内部实际绝对路径：

```bash
export UPSTREAM_KG_ROOT=<领导KG仓库的只读绝对路径>
export KG_BENCH_WORK=<实施者的可写绝对工作目录>
export KG_SNAPSHOT_ROOT="$KG_BENCH_WORK/snapshot"
export KG_RELEASE_ROOT="$KG_BENCH_WORK/releases/current"
export EVAL_ROOT="$KG_BENCH_WORK/evaluation"

test -d "$UPSTREAM_KG_ROOT/.git"
test -r "$UPSTREAM_KG_ROOT/services/kg_mcp.py"
mkdir -p "$KG_BENCH_WORK/upstream_archive" "$KG_BENCH_WORK/sidecar_src"

git -C "$UPSTREAM_KG_ROOT" rev-parse HEAD \
  > "$KG_BENCH_WORK/upstream_archive/upstream_revision.txt"
git -C "$UPSTREAM_KG_ROOT" archive --format=tar HEAD \
  > "$KG_BENCH_WORK/upstream_archive/leader-kg.tar"
sha256sum "$KG_BENCH_WORK/upstream_archive/leader-kg.tar" \
  > "$KG_BENCH_WORK/upstream_archive/leader-kg.tar.sha256"
tar -xf "$KG_BENCH_WORK/upstream_archive/leader-kg.tar" \
  -C "$KG_BENCH_WORK/sidecar_src"
```

如果内部策略不允许导出完整仓库，至少把经批准的只读查询模块和锁文件复制到自己的目录，
同时记录每个源文件的 SHA-256；但不能在运行时直接依赖一个会变化的领导工作目录。

代码读权限本身不足以完成正式实验。还必须另外获得以下至少一种经授权的数据访问方式：

1. 由 KG/运维负责人生成并放到实施者可读路径的 `neo4j.dump`；或
2. 可恢复到实施者独立实例的等价原子备份；或
3. 对已冻结只读实例的访问权，且负责人能提供与该实例严格对应的 dump SHA、计数和污染报告。

如果只有代码读权限和线上 MCP 查询权，却拿不到可验证 snapshot identity，本框架只能做
探索性连通测试，不能把结果标成正式 KG-on benchmark。此时内部 agent 必须报告权限阻塞，
不能伪造 snapshot manifest，也不能用运行中数据库目录的临时散列代替 dump。

## 4. KG 侧必须交付的功能

KG 侧必须增加一个只读工具：

```text
benchmark_retrieve
```

它是正式 benchmark 唯一允许调用的 MCP tool。现有 `search_concepts`、`semantic_search` 和 `get_node_info` 可以继续服务其他应用，但 benchmark 不直接调用它们。

### 4.1 Tool input schema

必须严格使用以下语义：

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["query", "method", "limit"],
  "properties": {
    "query": {
      "type": "string",
      "minLength": 1,
      "maxLength": 20000,
      "description": "由 benchmark 根据公开题面确定性生成的检索查询"
    },
    "method": {
      "type": "string",
      "enum": ["lucene_fulltext", "semantic_vector"]
    },
    "limit": {
      "type": "integer",
      "minimum": 1,
      "maximum": 20
    }
  }
}
```

第一阶段只要求正式支持 `lucene_fulltext`。如果 `semantic_vector` 尚未完成同快照对齐，必须返回明确错误，不得静默降级为全文检索。

### 4.2 benchmark 发送的 query

外部 MCP 正式路径唯一允许的 profile 是 `title_capabilities_scenario_v1`。query 是三个部分按一个换行连接：

```text
<task title>
<capability 1> <capability 2> ...
<case.scenario>
```

例如：

```text
Repair a misleading PSRR measurement
psrr measurement diagnosis controlled_experiment
A surprising PSRR improvement appears after a testbench edit. Determine whether it is circuit evidence and define the shortest valid repair.
```

query 不包含：

- answer template；
- answer contract；
- catalogs；
- 受控答案选项；
- oracle；
- relevant knowledge IDs；
- 参考答案。

KG 服务必须把 query 当作不可信普通文本，不能直接拼接进 Cypher，也不能把它作为未转义 Lucene 语句执行。

### 4.3 Tool output contract

返回正文必须是一个 JSON 对象。兼容当前 MCP SDK 的推荐写法：

```python
payload_text = json.dumps(
    payload,
    ensure_ascii=False,
    sort_keys=True,
    separators=(",", ":"),
)
return [types.TextContent(type="text", text=payload_text)]
```

如果当前 SDK 正确支持 `structuredContent`，可以同时提供；但 `content[0].text` 仍必须包含同一 JSON 对象，便于旧客户端兼容。不得返回 Markdown、解释性前缀或尾部日志。

完整输出结构：

```json
{
  "schema_version": "1.0",
  "source_snapshot_id": "kg-20260820-lucene-v1",
  "source_snapshot_sha256": "<neo4j.dump 的 64 位小写 SHA-256>",
  "retrieval_method": "lucene_fulltext",
  "query": "<原样返回收到的 query>",
  "query_sha256": "<query UTF-8 字节的 SHA-256>",
  "top_k": 4,
  "entries": [
    {
      "rank": 1,
      "stable_id": "<稳定知识 ID>",
      "title": "LDO Regulator Architecture",
      "text": "A Low Dropout regulator ...",
      "tags": ["power_management_ic", "ldo"],
      "source_class": "textbook",
      "source_name": "Chen_Power_Management_IC_Design",
      "source_uri": null,
      "retrieval_score": 14.85,
      "updated_at": "2026-05-14T11:54:56+08:00",
      "confidence": 0.9,
      "provenance": {
        "node_tier": "deep",
        "community_id": 10077,
        "edge_count": 50,
        "validation_status": "reviewed"
      }
    }
  ]
}
```

精确 JSON Schema 位于 `schemas/kg-external-retrieval-v1.schema.json`。KG 侧的 contract test 应使用该文件或生成等价校验。

### 4.4 字段要求

#### `source_snapshot_id`

- 由 KG 服务启动配置提供；
- 不能由客户端请求传入；
- 必须与部署目录中的快照 manifest 完全一致；
- 服务启动时缺失该值必须拒绝启动。

#### `source_snapshot_sha256`

- 必须等于正式 `neo4j.dump` 文件的 SHA-256；
- 不能是运行中 `.db` 文件列表的临时散列；
- 不能是 Git commit；
- 不能是 embedding 文件散列；
- 不能由客户端请求覆盖。

#### `query_sha256`

必须这样计算：

```python
hashlib.sha256(query.encode("utf-8")).hexdigest()
```

不能先 strip、lower、normalize 或修改换行。检索内部可以建立另一份规范化 query，但回传字段必须绑定收到的原始 query。

#### `stable_id`

当前 Neo4j 的 `Concept.name` 有唯一约束，因此推荐：

```python
stable_id = hashlib.sha256(raw_name.encode("utf-8")).hexdigest()
```

注意：

- 使用数据库中原始 `name`，不要先 `strip()`；
- snapshot ID 不进入 stable ID；
- 展示用 `title` 可以是 `raw_name.strip()`；
- 如果未来 KG 提供数据库外稳定 ID，应迁移到显式版本化的新 schema；
- 不能使用 Neo4j `elementId()` 作为跨 dump 的稳定 ID；
- 不能使用排序位置作为 ID。

名称前后空格节点不会导致 stable ID 不稳定。对数据库做批量 trim 反而可能引入碰撞，并改变快照，不属于本次接入任务。

#### `source_uri`

- 数据库有真实 DOI、URL 或文档 URI 时返回；
- 没有时返回 `null`；
- 严禁根据书名、作者或标题猜测 URI。

#### `source_class`

- 优先使用数据库 `source_type`；
- 缺失可以返回 `null`；
- benchmark 会规范化为 `unknown`；
- 不得把未知来源伪装成 `textbook` 或 `academic_paper`。

#### `updated_at`

- 有值时建议 ISO 8601；
- 没有时为 `null`；
- 不要用服务查询时间代替知识更新时间。

#### `confidence`

- 有数据库 certainty 时返回 `[0,1]` 数值；
- 没有时为 `null`；
- 不得用 retrieval score 代替 confidence。

## 5. KG 侧推荐代码结构

上游只读副本中的 `services/kg_mcp.py` 把查询结果格式化为文本。不要修改领导原文件，也不要
让 sidecar 用正则反向解析这些人类可读文本。应在实施者自己的 `sidecar_src` 中复用或移植
只读查询逻辑，把“查询原始数据”和“显示文本”分离。

允许的实现优先级：

1. 在自己的固定上游副本中导入已有底层 repository/query helper，并由 sidecar 直接获得结构化行；
2. 若底层 helper 与 MCP 文本渲染耦合，在自己的副本中重构，保留上游 commit 和 patch；
3. 若导入依赖不可控，sidecar 使用专用只读 Neo4j 账号执行本文规定的参数化查询；
4. 禁止解析线上 `search_concepts` 的文本输出拼装正式结果。

实施者可以在自己的目录中修改复制出来的 `services/kg_mcp.py`，但应把修改保存为独立 patch
或自己的 Git commit。所有 import path 必须解析到 `KG_BENCH_WORK` 下，启动前用
`python -c` 打印模块 `__file__` 并留档，防止误加载领导的可变工作目录。

推荐结构：

```python
async def _search_concepts_raw(query: str, limit: int) -> list[dict]:
    ...

async def _semantic_search_raw(query: str, limit: int) -> list[dict]:
    ...

async def _search_concepts(...):
    rows = await _search_concepts_raw(...)
    return render_human_text(rows)

async def _benchmark_retrieve(...):
    rows = (
        await _search_concepts_raw(...)
        if method == "lucene_fulltext"
        else await _semantic_search_raw(...)
    )
    return build_benchmark_payload(rows)
```

如果 sidecar 直接查询 Neo4j，建议把上面的 raw helper 放在独立文件，例如：

```text
sidecar_src/
├── kg_benchmark_sidecar/
│   ├── __init__.py
│   ├── config.py
│   ├── neo4j_readonly.py
│   ├── retrieval.py
│   ├── contract.py
│   └── server.py
├── tests/
├── requirements.lock
└── pyproject.toml
```

该结构完全位于实施者可写路径，不要求上游仓库增加 `benchmark_retrieve`。

### 5.1 全文检索实现要求

必须满足：

1. query 参数化进入 Cypher；
2. Lucene 特殊字符安全处理；
3. 不允许客户端注入任意 Lucene field query；
4. 固定索引名；
5. 固定 analyzer；
6. 固定排序；
7. score 相同时使用稳定 ID 或原始 name 做二级排序；
8. 一次查询返回完整元数据，避免 `top_k + 1` 次数据库请求；
9. 相同快照、query、method、limit 必须得到字节一致结果。

排序最低要求：

```text
ORDER BY score DESC, raw_name ASC
```

如果使用 Python 排序：

```python
rows.sort(key=lambda row: (-float(row["score"]), row["raw_name"]))
```

不要只按 score 排序，因为相同分数时 Neo4j 返回顺序未必构成公开合同。

### 5.2 Lucene query 安全规范

benchmark query 是自然语言，不是 Lucene 程序。服务侧应使用以下之一：

1. 官方 QueryParser escape；或
2. 固定 tokenizer 取词后构建受控 OR 查询。

禁止直接执行：

```python
CALL db.index.fulltext.queryNodes("conceptFullText", $raw_user_query)
```

如果当前实现必须接受 Lucene 语法供其他客户端使用，则 `benchmark_retrieve` 必须走独立的安全路径，不能复用“允许 Lucene 语法”的公开工具入口。

推荐 tokenizer 的原则：

- 英文 token 小写化仅用于检索；
- 保留模拟电路缩写：LDO、PSRR、STB、UGB、PMOS、NMOS、OA、CDF；
- 中文按当前 analyzer 处理；
- 去除 JSON/Cypher/Lucene 控制字符；
- 不改变回传的原始 query；
- tokenizer 版本写入 service source 和测试。

### 5.3 语义检索要求

只有同时满足以下条件，才能在 snapshot manifest 中声明支持 `semantic_vector`：

- embedding matrix 已冻结；
- embedding_names 已冻结；
- embedding model 目录已冻结；
- 三者均有 SHA-256；
- embedding_names 数量与 matrix 第一维一致；
- 每个 embedding name 能唯一映射到当前 Neo4j snapshot；
- 明确记录覆盖节点数和覆盖率；
- 未覆盖节点策略固定；
- cosine 实现和量化反量化规则固定；
- score 相同有稳定二级排序；
- 完全离线，不触发 Hugging Face 下载。

当前报告显示 embedding 只覆盖约 85.3% 的在线节点。因此第一阶段建议仅冻结 `lucene_fulltext`，不把 `semantic_vector` 混入同一正式处理。

## 6. MCP 只读隔离

仅在 `call_tool` 中增加 if 判断不够。正式交付必须有三层隔离。

### 6.1 专用 benchmark MCP endpoint

在实施者自己的 sidecar 工程中新增独立入口，例如：

```text
$KG_BENCH_WORK/sidecar_src/kg_benchmark_sidecar/server.py
```

不要向领导的 `services/` 目录写入 `kg_benchmark_daemon.py`。如果使用 systemd，优先创建
实施者自己的 user unit，或请运维把实施者 release 目录中的固定服务安装为独立 system unit；
unit 的 `WorkingDirectory`、日志和环境文件都不能指向领导的开发目录。

该 endpoint 的 `tools/list` 只返回：

```text
benchmark_retrieve
```

不要返回：

- `add_concept`
- `add_relation`
- `delete_relation`
- `build_derivation_chain`
- 任何条件写入工具
- 与 benchmark 无关的推理或推荐工具

即使客户端直接发送隐藏工具名，`tools/call` 也必须返回 MCP error。

### 6.2 数据库只读实例

正式 endpoint 必须连接恢复自 dump 的独立数据库，而不是生产数据库。优先使用 Neo4j 5.26 实际支持并验证过的数据库只读配置。配置名称必须以安装版本的本地文档和启动日志为准。

验收需要同时证明：

- benchmark 进程不能 CREATE；
- 不能 MERGE；
- 不能 SET；
- 不能 DELETE；
- 不能 DROP INDEX/CONSTRAINT；
- 查询仍可使用预建全文索引；
- 服务启动不会尝试更新 embedding/cache 到快照目录。

如果数据库目录本身不能完全只读挂载，可将日志、PID、临时文件和 query cache 指向独立可写目录，但 store 必须由 Neo4j 只读配置保护。实验前后重新核对 dump 身份和数据库计数。

### 6.3 Benchmark client allowlist

benchmark 侧已经强制：

```text
tool_name == benchmark_retrieve
```

配置写其他 tool 时会在任何网络请求之前失败。因此即使 KG endpoint 错误暴露写工具，benchmark runner 也不会调用它们。

## 7. 健康检查合同

建议正式 endpoint 的 `/health` 至少返回：

```json
{
  "status": "healthy",
  "service": "kg-benchmark-daemon",
  "read_only": true,
  "source_snapshot_id": "kg-20260820-lucene-v1",
  "source_snapshot_sha256": "<64 hex>",
  "service_code_revision": "<git commit>",
  "node_count": 681373,
  "relationship_count": 1234567,
  "supported_retrieval_methods": ["lucene_fulltext"],
  "tools": ["benchmark_retrieve"]
}
```

服务在以下任一情况必须 unhealthy 或拒绝启动：

- snapshot manifest 不存在；
- dump SHA 与配置不一致；
- 恢复后节点数不一致；
- 恢复后关系数不一致；
- service source revision 不一致；
- read-only 未生效；
- 全文索引不是 ONLINE；
- 声明 semantic 但 embedding artifact 缺失；
- MCP tools/list 出现写工具。

## 8. 正式快照制作

### 8.1 冻结窗口

1. 选定明确时间窗口；
2. 暂停所有 KG 注入、清洗、关系建议和后台更新任务；
3. 记录生产库节点数、关系数、索引状态；
4. 等待正在执行的事务结束；
5. 记录冻结负责人和时间。

### 8.2 Neo4j dump

必须使用与 Neo4j 5.26 匹配的 `neo4j-admin database dump`。示意命令：

```bash
neo4j stop
neo4j-admin database dump neo4j \
  --to-path="$KG_SNAPSHOT_ROOT" \
  --overwrite-destination=true
sha256sum "$KG_SNAPSHOT_ROOT/neo4j.dump"
```

具体 CLI 参数以内部安装的 `neo4j-admin database dump --help` 为准，并把实际命令保存进冻结报告。

不得用以下方式替代：

```bash
find data -name '*.db' -exec sha256sum ...
tar 正在运行的数据库目录
复制生产库一部分文件
```

### 8.3 恢复验证

必须在新目录恢复 dump：

```bash
neo4j-admin database load neo4j \
  --from-path="$KG_SNAPSHOT_ROOT" \
  --overwrite-destination=true
```

恢复后验证：

```cypher
MATCH (n:Concept) RETURN count(n);
MATCH ()-[r]->() RETURN count(r);
SHOW INDEXES;
SHOW CONSTRAINTS;
```

至少记录：

- Concept 节点数；
- 全部节点数；
- 全部关系数；
- 每种关系类型数量；
- Concept.name 唯一约束状态；
- conceptFullText 索引名称、类型、状态和 populationPercent；
- 空 name 数；
- 重复 name 数；
- source_type 分布；
- validation_status 分布。

### 8.4 Service source archive

正式服务代码必须来自实施者自己 sidecar 仓库中的干净 commit。以下命令只在
`KG_BENCH_WORK/sidecar_src` 执行，不在领导仓库执行：

```bash
cd "$KG_BENCH_WORK/sidecar_src"
git status --porcelain
# 必须无输出

git rev-parse HEAD
git archive --format=tar.gz \
  --output="$KG_BENCH_WORK/releases/kg-service-source.tar.gz" HEAD
sha256sum "$KG_BENCH_WORK/releases/kg-service-source.tar.gz"
```

不能只记录 commit 而继续运行 dirty worktree。不能 stash 后忘记恢复。正式 systemd/启动脚本
必须指向解包后的归档，而不是持续开发目录。还必须记录只读领导仓库的 upstream commit 和
最初导出 archive SHA；它们是来源信息，但顶层 `service_code.revision` 和
`service_code.archive_sha256` 绑定的是实际运行的 sidecar release。

### 8.5 snapshot SHA 的定义

本协议规定：

```text
snapshot_sha256 = SHA256(neo4j.dump 文件)
```

snapshot manifest 中 `artifacts[role=neo4j_dump].sha256` 必须与顶层 `snapshot_sha256` 完全相同。

同理，`artifacts[role=service_source].sha256` 必须与
`service_code.archive_sha256` 完全相同。否则 manifest 虽然同时列出了代码归档和代码元数据，
却不能证明二者指向同一份源码，benchmark 会拒绝该快照。

## 9. Snapshot manifest

精确 schema 位于 `schemas/kg-snapshot-manifest-v1.schema.json`。最小示例：

```json
{
  "schema_version": "1.0",
  "snapshot_id": "kg-20260820-lucene-v1",
  "snapshot_sha256": "<neo4j.dump sha256>",
  "created_at": "2026-08-20T10:00:00+08:00",
  "service_code": {
    "revision": "<实施者 sidecar 的 full git commit>",
    "archive_sha256": "<service tar.gz sha256>",
    "dirty": false,
    "upstream_revision": "<领导只读仓库的 full git commit>",
    "upstream_archive_sha256": "<最初导出的 leader-kg.tar sha256>"
  },
  "corpus": {
    "node_count": 681373,
    "relationship_count": 1234567
  },
  "supported_retrieval_methods": ["lucene_fulltext"],
  "artifacts": [
    {
      "role": "neo4j_dump",
      "name": "neo4j.dump",
      "sha256": "<same as snapshot_sha256>",
      "size_bytes": 9000000000
    },
    {
      "role": "service_source",
      "name": "kg-service-source.tar.gz",
      "sha256": "<same as service_code.archive_sha256>",
      "size_bytes": 1000000
    }
  ],
  "qualification": {
    "dump_restored_and_count_verified": true,
    "read_only_enforced": true,
    "contamination_audit_passed": true,
    "determinism_verified": true
  },
  "contamination_report_sha256": "<污染审计报告 sha256>"
}
```

如果支持 semantic，还必须增加 artifact roles：

```text
embedding_matrix
embedding_names
embedding_model
```

## 10. 污染审计

污染审计必须直接查询恢复后的正式 Neo4j snapshot，不能只 grep 代码仓库或旧 JSON 导出。

### 10.1 搜索字段

至少覆盖：

- `name`
- `aliases`
- `definition`
- `source_book`
- `properties` 序列化文本
- 论文 title/abstract 字段，如其不在 definition 中

### 10.2 搜索集合

必须包含：

1. `EvoLDO`、`EvoLDO-Bench`；
2. 全部 27 个完整 task ID；
3. 全部 27 条完整 scenario；
4. 具有辨识度的题目 title；
5. 受控答案标识符，包括下划线原始形式；
6. `answer_template`、`expected.json`、`relevant_knowledge_ids`、`oracle`；
7. 至少十条参考答案中特有的长组合短语。

示例标识符：

```text
measurement_contract_changed
no_circuit_claim
op_recovery_order
cross_stage_recovery
restore_same_ac_normalization
source_oa_hash_divergence
stop_if_pm_or_undershoot_or_iq_fails
```

注意：关键词命中不自动等于污染。审计报告需保存命中数量、稳定 ID、字段、短摘要和人工判断。但 task ID、完整 scenario、answer template 或参考答案长短语的直接命中通常是正式阻断。

### 10.3 审计报告

输出 `contamination_audit.json` 和人类可读 Markdown。JSON 至少包含：

```json
{
  "schema_version": "1.0",
  "snapshot_sha256": "<dump sha>",
  "fields_scanned": [],
  "patterns": [],
  "direct_identifier_hits": 0,
  "scenario_exact_hits": 0,
  "answer_phrase_hits": 0,
  "manual_review_open": 0,
  "passed": true
}
```

计算报告 SHA-256，并写入 snapshot manifest。

## 11. 确定性资格测试

### 11.1 单进程重复

对全部 27 个正式 query，每个执行十次，固定 method 和 limit。比较：

- 完整 JSON 字节；
- entry 顺序；
- stable ID；
- score；
- query SHA；
- snapshot ID/SHA。

要求同一 query 十次响应 payload 的 SHA-256 完全一致。

### 11.2 重启重复

1. 执行全部 27 个 query，保存响应；
2. 重启 MCP；
3. 再执行全部 query；
4. 比较字节；
5. 重启 Neo4j 和 MCP；
6. 第三次执行并比较。

三组必须一致。

### 11.3 并发重复

至少用 1、2、4 个并发 client 执行同一 query 集合。结果必须一致。延迟可以不同。

### 11.4 负面测试

必须覆盖：

- 空 query；
- 超长 query；
- limit=0；
- limit=21；
- 未知 method；
- extra argument；
- Lucene 特殊字符；
- Cypher 注入文本；
- 换行、制表符和 Unicode；
- JSON/Markdown 片段；
- “ignore previous instructions”等提示注入文本；
- 数据库不可用；
- 索引 unavailable；
- snapshot 环境变量缺失；
- 写工具调用。

所有错误必须是明确 MCP error 或 `isError=true`，不得返回伪造的空成功结果。

## 12. MCP 配置文件

benchmark 侧配置 schema：`schemas/kg-mcp-config-v1.schema.json`。

推荐正式配置：

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

正式服务最好与 benchmark runner 同机，使用 loopback。若必须跨主机：

- 设置 `allow_non_loopback=true`；
- 使用隔离内网；
- 使用 TLS 或受控反向代理；
- 凭据通过 `headers_from_env` 指定环境变量名；
- 配置文件不能包含秘密值；
- 禁止 endpoint URL 中携带 username、password、query 或 fragment。

配置采用严格字段白名单。`api_key`、`token`、`password` 等未声明字段即使服务能够识别，
benchmark 也会拒绝；鉴权值只能放在运行环境变量中，再由 `headers_from_env` 引用环境变量名。
外部 MCP 也不允许切换为 `full_public_task_v1`，避免把 catalogs、受控答案词表或更宽的题面材料
发送给知识服务。

内部正式 preflight 推荐给每题最多 300 秒、最多 3 次瞬时连接重试和 10 秒退避。重试只处理
连接、I/O 和 timeout；schema、snapshot、query 或 policy 错误立即失败，不能靠重试掩盖。
全部尝试仍使用完全相同的 query、method、top-k 和 snapshot。模型运行阶段不发生这些重试。

## 13. 离线交付目录

实施者在自己的可写目录中组装 release；其中 dump 可以由 KG/运维负责人只读交付：

```text
kg_benchmark_release_<id>/
├── README.md
├── SHA256SUMS
├── snapshot/
│   ├── neo4j.dump
│   ├── kg_snapshot_manifest.json
│   └── contamination_audit.json
├── service/
│   ├── kg-service-source.tar.gz
│   ├── leader-kg-upstream.tar
│   ├── upstream_revision.txt
│   ├── requirements.lock
│   ├── wheels/
│   ├── systemd/
│   └── config/
├── runtime/
│   ├── neo4j-community-5.26.0-unix.tar.gz
│   └── jdk-21-*.tar.gz
├── semantic/                 # 仅声明 semantic 时存在
│   ├── embeddings_int8.npy
│   ├── embedding_names.json
│   └── embedding_model.tar.gz
├── reports/
│   ├── dump_restore_verification.md
│   ├── determinism_report.json
│   ├── readonly_report.json
│   ├── contamination_audit.md
│   └── offline_smoke_test.md
└── examples/
    ├── mcp_initialize.json
    ├── tools_list.json
    ├── benchmark_retrieve_request.json
    └── benchmark_retrieve_response.json
```

### 13.1 SHA256SUMS

必须覆盖所有交付文件，路径相对 release 根目录，排序固定。接收方在解包后先执行完整核验。

### 13.2 Python 依赖

- 使用精确版本 lock；
- 提供与内部服务器 Python/架构匹配的 wheels；
- `pip install --no-index --find-links=...` 必须成功；
- 启动不能访问 PyPI 或 Hugging Face；
- semantic 模式的模型必须使用 `local_files_only=True`；
- 测试断网启动。

## 14. Benchmark preflight 流程

KG 侧交付后，benchmark 负责人创建 MCP config 和 snapshot manifest，先不运行模型：

```bash
PYTHONPATH=src python3 -m evoldo_bench.cli kg-preflight \
  --tasks-root benchmarks/ldo_v07/tasks \
  --output "$EVAL_ROOT/kg_preflight_discovery_k20" \
  --knowledge-mcp-config "$KG_RELEASE_ROOT/config/mcp_kg_config.json" \
  --knowledge-snapshot-manifest "$KG_RELEASE_ROOT/snapshot/kg_snapshot_manifest.json" \
  --knowledge-top-k 20
```

该命令必须在任何模型调用前完成 27 道题检索，并输出：

```text
kg_preflight_discovery_k20/
├── mcp_kg_config.json
├── kg_snapshot_manifest.json
├── knowledge_freeze_manifest.json
└── tasks/
    └── <task_id>/
        ├── kg_mcp_raw_response.json
        └── kg_retrieval.json
```

检查：

- task_count=27；
- 每题一个逻辑检索调用；
- snapshot ID/SHA 完全一致；
- query SHA 可复算；
- discovery top-k 固定为 20，用于构造专家相关性候选池；
- 没有重复 stable ID；
- raw response SHA 与 manifest 一致；
- normalized retrieval SHA 与 manifest 一致；
- 无模型进程启动。

## 15. 专家相关性标注

领导 KG 的 ID 空间与 benchmark 自带 clean-room KG 不同，不能复用 oracle 中的 `relevant_knowledge_ids`。

专家审阅 discovery K=20 检索池，生成：

```json
{
  "schema_version": "1.0",
  "source_snapshot_sha256": "<neo4j dump SHA>",
  "tasks": {
    "v07-foundation-01-feedback-trace": [
      "<relevant stable id 1>",
      "<relevant stable id 2>"
    ]
  }
}
```

建议标注规则：

- 只标“能够帮助解决该题所需通用知识”的条目；
- 不以模型最终是否答对作为相关性标准；
- 不把直接复述题面但无工程知识的条目标为相关；
- override-resistant 题中，通用先验可以相关，但必须注明不得覆盖当前测量；
- 两名专家独立标注，分歧仲裁；
- 保存标注人、时间、规则版本和分歧记录到旁路审计文件；
- relevance manifest 本身不进入模型 prompt。

每一道计划进入正式矩阵的题都必须在 `tasks` 中出现；确实没有相关条目时写空数组，不能省略。
使用 K=20 的候选池，是为了让正式 K 下的 recall@k 有一个比正式返回集更宽的相关性分母；
如果只标正式 K 返回的条目，recall@k 会被人为抬高。

得到 relevance manifest 后，以预先声明的正式 K 重新执行 preflight。初次内部实验推荐
`FORMAL_TOP_K=12`：它比默认 K=4 更充分利用 KG，同时仍受 32,000 字符总正文上限约束。
不得查看模型分数后再选择 K。

```bash
PYTHONPATH=src python3 -m evoldo_bench.cli kg-preflight \
  --tasks-root benchmarks/ldo_v07/tasks \
  --output "$EVAL_ROOT/kg_preflight_reviewed" \
  --knowledge-mcp-config "$KG_RELEASE_ROOT/config/mcp_kg_config.json" \
  --knowledge-snapshot-manifest "$KG_RELEASE_ROOT/snapshot/kg_snapshot_manifest.json" \
  --knowledge-relevance-manifest "$KG_RELEASE_ROOT/review/kg_relevance_manifest.json" \
  --knowledge-top-k 12
```

再用相同配置、相同 relevance manifest 和 K=12 生成第二个空输出目录。两次 K=12 preflight
的 retrieval SHA 必须逐题一致。discovery K=20 与正式 K=12 的 SHA 本来就不同，不能互相比。
正式实验只导入经过专家审核且通过重复确定性核对的 K=12 freeze。

## 16. 正式 KG-off/KG-on 实验

### 16.1 KG-off

```bash
PYTHONPATH=src python3 -m evoldo_bench.cli experiment \
  --tasks-root benchmarks/ldo_v07/tasks \
  --oracle-root benchmarks/ldo_v07/dev_reference/oracles \
  --output "$EVAL_ROOT/model_x_kg_off" \
  --model-id '<exact-model-id>' \
  --mode direct_reasoning \
  --rollouts 3 \
  --base-seed 2026 \
  --paired-modes direct_reasoning,knowledge_assisted \
  -- <agent-command-and-frozen-options>
```

### 16.2 KG-on

正式 KG-on 不再联系 MCP，直接导入专家审阅过的 freeze：

```bash
PYTHONPATH=src python3 -m evoldo_bench.cli experiment \
  --tasks-root benchmarks/ldo_v07/tasks \
  --oracle-root benchmarks/ldo_v07/dev_reference/oracles \
  --output "$EVAL_ROOT/model_x_kg_on" \
  --model-id '<exact-model-id>' \
  --mode knowledge_assisted \
  --rollouts 3 \
  --base-seed 2026 \
  --paired-modes direct_reasoning,knowledge_assisted \
  --knowledge-freeze-dir "$EVAL_ROOT/kg_preflight_reviewed" \
  --knowledge-top-k 12 \
  -- <same-agent-command-and-frozen-options>
```

导入时 benchmark 会重新验证：

- task 集合完全一致；
- MCP config SHA；
- snapshot manifest SHA；
- source snapshot ID/SHA；
- query profile；
- retrieval method；
- 每题 query SHA；
- 每题 retrieval 文件 SHA；
- raw response SHA；
- raw MCP payload 重新规范化后必须与 retrieval 文件逐字段一致；
- returned IDs；
- relevance manifest SHA、snapshot 绑定、逐题覆盖和重新计算后的 recall/precision；
- 不存在 symlink。

任意字段变化都会在模型调用前终止。

### 16.3 配对比较

```bash
PYTHONPATH=src python3 -m evoldo_bench.cli compare-treatments \
  "$EVAL_ROOT/model_x_kg_off/experiment_manifest.json" \
  "$EVAL_ROOT/model_x_kg_on/experiment_manifest.json"
```

报告包括：

- mean score lift；
- improvement rate；
- harm rate；
- 按 benefit/neutral/override-resistant 分组；
- token delta；
- model wall-time delta；
- KG materialization latency；
- recall@k；
- precision@k。

## 17. 模型实际可见内容

模型只能看到标准化的 `kg_retrieval.json`。不会看到：

- `kg_mcp_raw_response.json`；
- MCP endpoint；
- snapshot manifest 全文；
- relevance manifest；
- 污染报告；
- Neo4j 凭据；
- KG 写工具；
- oracle。

每个 rollout 使用同一题目的相同 retrieval 文件。不同 rollout 不能重新检索。

## 18. 错误分类

### 18.1 Preflight 错误

以下错误在模型启动前终止，不计模型能力失败：

- MCP 无法连接；
- initialize 失败；
- tool 不存在；
- JSON 不可解析；
- snapshot 不匹配；
- query/hash 不匹配；
- method/top-k 不匹配；
- entry schema 错误；
- 响应过大；
- 重复 ID；
- 返回 task_id/answer/oracle 等禁用字段；
- relevance manifest 绑定其他 snapshot。

这些属于 KG/benchmark 基础设施未就绪。修复后重新进行完整 preflight。

### 18.2 模型错误

只有在冻结上下文已成功进入 prompt 后，模型的错误答案、拒答、格式失败或错误覆盖才进入能力统计。

## 19. 性能和容量验收

至少报告：

- 单查询 P50/P95/P99；
- 27 题串行总时间；
- 1/2/4 并发吞吐；
- 最大响应字节数；
- 最大 entry text 长度；
- Neo4j heap；
- MCP RSS；
- timeout 数量；
- cache hit/miss，但 cache 不得影响结果；
- 服务冷启动时间；
- 重启后首次查询时间。

benchmark 默认限制：

```text
top_k <= 20
MCP response <= 2 MiB
single entry text <= 12,000 chars
all entry text <= 32,000 chars
request timeout <= 300 seconds；推荐 30 seconds
```

正式配置冻结后不能针对某一道题单独增加 top-k、timeout 或长度上限。

## 20. KG 侧单元测试清单

必须至少有：

1. tool schema 精确测试；
2. tools/list 只暴露 benchmark_retrieve；
3. 未知 tool 被拒绝；
4. 写 tool 被拒绝；
5. query SHA 正确；
6. snapshot ID/SHA 来自服务端配置；
7. stable ID 使用 raw name；
8. title strip 不改变 stable ID；
9. null source 不伪造；
10. stable tie-break；
11. limit 边界；
12. method 边界；
13. Lucene 特殊字符；
14. 中文/英文/混合 query；
15. 空结果返回 entries=[]；
16. 数据库异常返回 error；
17. 索引异常返回 error；
18. JSON 序列化确定性；
19. 重启确定性；
20. read-only 验证。

## 21. KG 侧集成测试清单

使用真实 snapshot：

1. `/health` 身份正确；
2. MCP initialize 成功；
3. tools/list 正确；
4. 代表性 LDO query 有结果；
5. 全部 27 个 benchmark query 可完成；
6. 无响应超过 benchmark 限制；
7. 27 题十次重复一致；
8. 服务重启后一致；
9. Neo4j 重启后一致；
10. 污染审计通过；
11. KG-off 模式不产生 MCP 日志；
12. 正式 experiment 导入 freeze 时不产生 MCP 日志；
13. 实验前后节点数、关系数不变；
14. 实验前后 snapshot manifest 不变。

## 22. 验收门槛

| Gate | 必须结果 |
|---|---|
| Service code clean | `dirty=false` |
| Neo4j dump | 可恢复、SHA 固定 |
| Node/relationship count | 恢复前后相等 |
| Read-only | 数据库与 MCP 双层通过 |
| tools/list | 只有 `benchmark_retrieve` |
| Response | 机器可解析 JSON |
| Snapshot binding | response 与 manifest 一致 |
| Query binding | 原文及 SHA 一致 |
| Determinism | 27 题、10 次、重启后字节一致 |
| Contamination | 无未处置直接污染命中 |
| Offline | 断网可启动和查询 |
| Preflight | 27/27 成功，无模型调用 |
| Expert review | 完成 relevance manifest |
| Freeze import | 所有哈希复核通过 |

任何一项失败，正式模型矩阵不得开始。

## 23. 内部 agent 的具体实施顺序

1. 验证领导仓库只能读，并记录绝对路径；
2. 记录领导仓库 upstream commit；
3. 用 `git archive` 把该 commit 导出到实施者可写目录并记录 SHA；
4. 在实施者目录创建独立 sidecar Git 仓库和虚拟环境；
5. 在自己的固定副本中复用或重构 raw query helper；
6. 实现 `benchmark_retrieve`；
7. 增加独立 benchmark daemon，所有路径均指向实施者目录；
8. 增加只读 tools/list 和 call_tool 双重白名单；
9. 增加 snapshot identity 启动配置；
10. 增加 `/health` 身份字段；
11. 增加 contract/negative/determinism tests；
12. 确认领导仓库没有产生任何写入或状态变化；
13. 清理并提交实施者 sidecar 代码，生成自己的 service source archive；
14. 向 KG/运维负责人申请原子 dump 或等价冻结数据访问，不自行操作生产服务；
15. 由有权限者暂停注入并生成 Neo4j dump，或交付已冻结 dump；
16. 在实施者独立 runtime 中恢复 benchmark instance；
17. 配置只读并验证；
18. 执行数据库级污染审计；
19. 生成绑定 sidecar release、upstream revision 和 dump 的 snapshot manifest；
20. 完成离线 release 目录和 SHA256SUMS；
21. 与 benchmark 负责人共同运行 `kg-preflight`；
22. 修复所有 P0/P1，修复只能发生在实施者 sidecar；
23. 专家标注 retrieval relevance；
24. 重新生成 reviewed freeze；
25. 书面批准后才启动模型实验。

## 24. KG 侧完成后必须返回的信息

内部 agent 最终回复必须包含：

- 领导只读仓库路径和 upstream commit；
- upstream archive SHA；
- 实施者 sidecar 代码 commit；
- source archive SHA；
- sidecar 修改文件列表；
- “未修改领导仓库、未重启领导服务”的确认；
- `benchmark_retrieve` input schema；
- 一份完整原始响应；
- tools/list 完整响应；
- health 完整响应；
- neo4j.dump SHA 和大小；
- 节点数、关系数；
- snapshot manifest；
- 污染报告 SHA；
- 确定性报告摘要；
- 只读测试摘要；
- 离线启动命令；
- 已知限制；
- 所有测试命令及退出码。

不得只回复“已完成”或只提供截图。

## 25. 实施中的重要判断

### 25.1 不清洗生产 KG

名称空格、长标题和乱码是数据质量问题，但不是这次 benchmark 接入的前置数据清洗任务。为了保持快照可审计，本轮通过原始 name 哈希、显示 title strip 和严格长度限制隔离这些问题。任何数据库清洗必须形成新 snapshot 和新 treatment。

### 25.2 第一阶段只使用 Lucene

语义索引未覆盖全部在线节点。先使用 Lucene 能缩小变量数量，回答“领导 KG 当前全文知识是否有帮助”。后续可以增加 `semantic_vector` 或固定 hybrid 处理，但必须独立命名、独立冻结、独立成图。

### 25.3 不把 KG 变成答案库

KG 只能提供通用设计先验。不得针对 27 道题补写定制条目，也不得把专家相关性标签或模型错误答案反馈回本轮 snapshot。否则测到的是题目记忆，不是知识增强能力。

### 25.4 不将内部知识正文公开

正式内部报告可以发布分数、lift、检索 ID、来源类别和统计指标，但如果教材或论文正文存在版权限制，公开报告不得附带完整 retrieval text、dump 或原始响应。公开与内部 artifact 必须分离。

---

满足本文全部 Gate 后，KG 侧才算完成“可用于严格配对 benchmark 的只读、冻结、可复现知识服务”，而不仅是“可以被某个聊天 agent 调用的 MCP 服务”。
