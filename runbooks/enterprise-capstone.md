# OmniSupport 企业级毕业项目运行手册

## 1. 你将得到什么

执行本手册后，本机不是只跑几个测试，而是得到一套可操作的客服 Copilot 产品：

- 240 条虚构但业务结构真实的 Northstar 工单；
- HTML、PDF、图片、WAV、MP4 原始资产；
- PostgreSQL、pgvector、MinIO、Iceberg、dbt、GraphRAG；
- Dagster 全链路资产图；
- RAG API、Tool API、Copilot Product API；
- 坐席工作台、证据引用、反馈、KPI、安全写动作和人工审批；
- OTel Collector 与 Phoenix trace；
- 统一的 data/index/prompt/graph/service release 绑定。

所有命令都在仓库根目录执行：

```bash
cd /path/to/omnisupport-copilot
```

> **只运行一个仓库副本。** Compose 中沿用课程统一容器名 `omni_*`。如果本机还保留
> `omnisupport-copilot-week07-real`、`omnisupport-copilot-week08-retrieval-rag`、
> `omnisupport-copilot-week10-controlled-agent` 等旧 worktree，不要同时在这些目录执行
> `docker compose up`。后启动的副本可能替换同名服务，表现为产品页面突然降级、release
> 变回 `dev-local`，但当前代码本身并没有改变。课堂和毕业项目统一从最新 `main` 的
> `omnisupport-copilot` 根目录启动。

## 2. 启动

```bash
cp infra/env/.env.example infra/env/.env.local

docker compose \
  --env-file infra/env/.env.local \
  -f infra/docker-compose.yml \
  up -d --build
```

等待服务健康：

```bash
docker compose \
  --env-file infra/env/.env.local \
  -f infra/docker-compose.yml \
  ps

curl -fsS http://localhost:8002/health
```

`/health` 的 `postgres`、`rag_api`、`tool_api` 都应为 `ok`。

## 3. 生成并灌入完整数据

```bash
docker compose \
  --profile capstone \
  --env-file infra/env/.env.local \
  -f infra/docker-compose.yml \
  run --rm capstone_bootstrap
```

这条命令真实执行：

1. 生成固定 seed 工单和文档 manifest；
2. 工单 contract validation、bronze ingest、silver upsert、checkpoint；
3. 文档上传 MinIO 并写 `raw_doc_asset/knowledge_doc`；
4. HTML/PDF/图片/音视频 parse、chunk、evidence gate；
5. embedding 与 pgvector index；
6. dbt staging/intermediate/marts/tests；
7. GraphRAG 派生层；
8. 激活 `capstone-v1.0.0` governed release。

运行产物写到被 Git 忽略的 `data/generated/` 和 `reports/capstone/`。重复执行是幂等的，不应把工单或原始事件翻倍。

一次全新环境的确定性基线是：

| 对象 | 当前发布数量 | 验收口径 |
|---|---:|---|
| Capstone 工单 | 240 | `tenant_id=northstar-demo` 且 `data_release_id=data-capstone-v1` |
| 原始知识资产 | 10 | 6 个 HTML + PDF + PNG + WAV + MP4，真实上传到 MinIO |
| 当前可检索 chunk | 91 | `data_release_id=data-capstone-v1` 且 embedding 非空 |
| GraphRAG 投影 | 16 entities / 14 edges / 2 communities | 由当前发布知识生成 |

重复 bootstrap 的正常结果是工单进入 duplicate/upsert 路径、索引显示 `embedded=0`、
`skipped=91`，而不是再新增 240 条工单或 91 个 chunk。旧课程实验遗留的文档或工单会被
重新标记到 `course-legacy` / `data-capstone-dev-stale`，不会混进当前产品发布。

## 4. 用 Dagster 真实物化同一条链

浏览器打开 <http://localhost:3000>，进入 Assets，筛选 group `week15_capstone`，可以看到：

```text
capstone_source_pack
  -> capstone_operational_data
      -> capstone_knowledge_index
          -> capstone_graph_projection
      -> capstone_analytics_marts
          -> capstone_product_release
```

课堂上可以从 UI 物化 `capstone_product_release` 及全部上游。命令行等价验收：

```bash
docker compose \
  --profile tools \
  --env-file infra/env/.env.local \
  -f infra/docker-compose.yml \
  run --rm devbox \
  dagster asset materialize -m pipelines.definitions --select '*capstone_product_release'
```

成功标志是 `RUN_SUCCESS`，不是只看到 asset 名称。

## 5. 一条命令做端到端验收

```bash
docker compose \
  --profile tools \
  --env-file infra/env/.env.local \
  -f infra/docker-compose.yml \
  run --rm devbox \
  python -m scripts.capstone.verify_e2e
```

验收器会走公共 HTTP API，实际执行：

- 坐席与管理员登录；
- 租户内工单读取；
- 建会话并做 Hybrid RAG；
- 校验命中 `workspace-api-webhook` 证据；
- 写一条有用反馈；
- 执行受治理 KPI 查询；
- 写内部备注；
- 发起 1 美元 service credit；
- 验证它先进入 HITL，再由管理员批准恢复；
- 到 Phoenix 校验 RAG、HITL wait、HITL resume 三条 trace。

通过时输出顶层字段：

```json
{"status": "pass"}
```

完整报告保存在 `reports/capstone/e2e-verification.json`。

## 6. 产品演示顺序

### 6.1 坐席登录

打开 <http://localhost:8010>：

```text
agent@northstar.demo
Agent@2026
```

选择 `Webhook delivery returns HTTP 404` 工单。这里显示的队列、优先级、组织、SLA 和时间线都来自 PostgreSQL。

### 6.2 证据问答

Retrieval mode 选择 `Hybrid RAG`，输入：

```text
What must happen before rotating a Workspace webhook signing secret?
```

检查：

- 回答下方出现 `doc:capstone:workspace-api-webhook`；
- 点击 Source 打开 evidence drawer；
- evidence 中有 `evidence_id`、source、section 和 score；
- 消息下方有 trace ID 与 feedback 按钮。

默认无模型密钥时，系统明确显示 evidence summary fallback。这是可复现模式，不是假装调用了模型。
此模式验证的是数据、检索、证据、权限、审计和工作流闭环；要验收生成质量，必须配置真实模型并运行 Week11 评测门禁。

### 6.3 受治理 KPI

进入 Operations：

1. 选择 `Ticket count` 与 `SLA breach count`；
2. 维度选择 `Product line`；
3. 点击 `Run governed query`；
4. 检查返回 `data-capstone-v1` 行、`audit_id` 和策略列表。

这里没有 Text-to-SQL。浏览器只能提交指标、维度、过滤器和日期，服务端从 metric registry 构造参数化 SQL。

### 6.4 普通动作与 HITL

回到工单页：

- `Add note`：应直接完成并出现在时间线。
- `Service credit`：应返回 `awaiting_approval`，不能直接写财务调整。

退出后使用管理员登录：

```text
admin@northstar.demo
Admin@2026
```

进入 Approvals，检查风险、金额、证据和 trace，点击 `Approve & resume`。批准后 `financial_adjustment` 才会落库。

### 6.5 工程证据

- Dagster：<http://localhost:3000>
- Phoenix：<http://localhost:6006>
- MinIO：<http://localhost:9001>，账号默认 `minioadmin / minioadmin`
- RAG OpenAPI：<http://localhost:8000/docs>
- Tool OpenAPI：<http://localhost:8001/docs>
- PostgreSQL：`localhost:15432 / omnisupport / omni / omnipass`

在 Phoenix 中用产品页面显示的 trace ID 搜索，应能看到 Product API、RAG 或 Tool/HITL 跨服务 span。

正常产品操作统一从 <http://localhost:8010> 进入。RAG/Tool 的 OpenAPI 页面可用于查看契约，但除健康检查和只读元数据外，业务接口默认要求 `X-Service-Token`、`X-Actor-ID`、`X-Actor-Role`、`X-Tenant-ID` 四个内部请求头，不能绕开 Product API 直接冒充用户或租户。

## 7. 本地可复现模式与真实模型模式

### 7.1 默认本地模式

```dotenv
LLM_PROVIDER=auto
LLM_MODEL=
EMBEDDING_MODEL=deterministic
```

用途是无外部账号也能验证完整数据工程和控制面。它不代表生产语义质量。

### 7.2 使用本机 Ollama 真实生成

```dotenv
LLM_PROVIDER=ollama
LLM_MODEL=qwen3:14b
LLM_BASE_URL=http://host.docker.internal:11434/v1
EMBEDDING_MODEL=deterministic
```

先在宿主机执行 `ollama list`，确认模型已安装。Compose 容器通过
`host.docker.internal` 调用宿主机 Ollama，不需要把模型装进容器。

### 7.3 切换云模型

| Provider | 必填配置 | 默认模型 | 默认 Base URL |
|---|---|---|---|
| Claude | `LLM_PROVIDER=anthropic`、`ANTHROPIC_API_KEY` | `claude-sonnet-4-6` | Anthropic SDK 默认 |
| GPT | `LLM_PROVIDER=openai`、`OPENAI_API_KEY` | `gpt-5-mini` | OpenAI SDK 默认 |
| DeepSeek | `LLM_PROVIDER=deepseek`、`DEEPSEEK_API_KEY` | `deepseek-v4-flash` | `https://api.deepseek.com` |
| 通义千问 | `LLM_PROVIDER=qwen`、`DASHSCOPE_API_KEY` | `qwen-plus` | 北京地域 OpenAI 兼容地址 |
| Kimi | `LLM_PROVIDER=kimi`、`KIMI_API_KEY` | `kimi-k2.5` | `https://api.moonshot.cn/v1` |

模型名和地址都可用 `LLM_MODEL`、`LLM_BASE_URL` 覆盖。密钥只放
`infra/env/.env.local` 或生产 Secret Manager，不提交到 Git。修改后重建 RAG 服务：

```bash
docker compose --env-file infra/env/.env.local -f infra/docker-compose.yml \
  up -d --build --force-recreate rag_api copilot_api copilot_console
```

健康检查必须显示真实 Provider，而不是 fallback：

```bash
curl -fsS http://localhost:8000/health | jq '.checks | {llm,llm_provider,llm_model}'
```

完整验收时强制要求真实 LLM，任何鉴权失败、超时或 fallback 都会让命令失败：

```bash
docker compose --profile tools --env-file infra/env/.env.local -f infra/docker-compose.yml \
  run --rm devbox python -m scripts.capstone.verify_e2e --require-llm
```

### 7.4 生成与 embedding 分开配置

```dotenv
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=...
OPENAI_API_KEY=...
EMBEDDING_MODEL=text-embedding-3-small
```

LLM 负责基于证据组织答案；embedding 负责召回，两者不是同一配置。切换
embedding 后必须使用新的 `CAPSTONE_INDEX_RELEASE_ID` 重新 bootstrap，不能用不同模型覆盖同一个 index release。切换生成模型也应发布新的
`CAPSTONE_PROMPT_RELEASE_ID` 和 `CAPSTONE_RELEASE_ID`，保留可回滚、可评测的版本边界。

生产环境还要完成 OIDC/SSO、secret manager、mTLS/workload identity、HA 存储、备份恢复、容量压测、WAF/限流、模型预算、内容安全、签名发布和灾备演练。Docker Compose 是工程闭环，不是高可用部署声明。

## 8. 数据检查

```bash
docker compose \
  --env-file infra/env/.env.local \
  -f infra/docker-compose.yml \
  exec -T postgres psql -U omni -d omnisupport -c "
    select tenant_id, data_release_id, count(*)
    from ticket_fact
    group by 1,2
    order by 1,2;"
```

预期 `northstar-demo / data-capstone-v1` 为 240 条。再检查多模态与证据：

```bash
docker compose \
  --env-file infra/env/.env.local \
  -f infra/docker-compose.yml \
  exec -T postgres psql -U omni -d omnisupport -c "
    select asset_type, count(*) from raw_doc_asset group by 1 order by 1;
    select count(*) as chunks, count(embedding) as indexed from knowledge_section;"
```

第二条 SQL 会同时看到课程历史发布。要精确核对当前产品，请使用：

```bash
docker compose \
  --env-file infra/env/.env.local \
  -f infra/docker-compose.yml \
  exec -T postgres psql -U omni -d omnisupport -c "
    select count(*) as current_assets
    from raw_doc_asset where release_id = 'data-capstone-v1';
    select count(*) as current_chunks, count(embedding) as indexed
    from knowledge_section where release_id = 'data-capstone-v1';"
```

预期分别为 `10` 和 `91 / 91`。`support_kpi_mart` 是按指标和维度展开的长表，不能把所有
`metric_name` 的 `ticket_count` 列直接相加；核对总工单时必须先限定
`metric_name='ticket_count'`，否则会把同一批工单按不同指标重复累计。

## 9. 故障定位

### bootstrap 失败

```bash
docker compose --env-file infra/env/.env.local -f infra/docker-compose.yml ps
docker compose --env-file infra/env/.env.local -f infra/docker-compose.yml logs --tail=200 postgres minio rag_api tool_api
```

### E2E 报 trace not found

先确认 Phoenix 和 OTel Collector 都在运行，然后立即重跑验收；Phoenix verifier 查询最近 100 条 trace。健康探针使用 `/live`，不会持续制造跨服务健康 trace。

### 产品健康检查突然变成 degraded 或 release 变成 dev-local

先确认容器挂载来源：

```bash
docker inspect omni_rag_api \
  --format '{{range .Mounts}}{{println .Source "->" .Destination}}{{end}}'
```

输出中的源码路径必须是当前最新 `omnisupport-copilot`。若指向旧 Week worktree，回到当前
仓库根目录强制重建产品服务：

```bash
docker compose \
  --profile tools \
  --env-file infra/env/.env.local \
  -f infra/docker-compose.yml \
  up -d --build --force-recreate rag_api tool_api copilot_api copilot_console dagster
```

### KPI 没数据

确认 bootstrap 的 dbt 阶段成功，并检查：

```bash
docker compose --profile tools --env-file infra/env/.env.local -f infra/docker-compose.yml \
  run --rm devbox bash -lc 'cd analytics && DBT_PROFILES_DIR=. dbt build'
```

### 清理

保留数据卷停止服务：

```bash
docker compose --env-file infra/env/.env.local -f infra/docker-compose.yml down
```

删除本地数据库、对象和所有实验状态：

```bash
docker compose --env-file infra/env/.env.local -f infra/docker-compose.yml down -v
```

`down -v` 不可恢复，只能在确认不需要本地实验数据时执行。
