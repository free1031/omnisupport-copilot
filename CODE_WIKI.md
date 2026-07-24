# OmniSupport Copilot — Code Wiki

> 多模态企业支持知识层 + 工单联动 AI 系统（准生产级课程项目）
>
> 本文档由代码库静态分析生成，覆盖项目整体架构、主要模块职责、关键类与函数说明、依赖关系以及项目运行方式。

---

## 目录

1. [项目概述](#1-项目概述)
2. [整体架构（七层模型）](#2-整体架构七层模型)
3. [技术栈与选型](#3-技术栈与选型)
4. [仓库结构总览](#4-仓库结构总览)
5. [核心模块详解](#5-核心模块详解)
   - 5.1 [基础设施层 infra/](#51-基础设施层-infra)
   - 5.2 [服务层 services/](#52-服务层-services)
   - 5.3 [编排层 pipelines/](#53-编排层-pipelines)
   - 5.4 [湖仓层 pipelines/lakehouse/](#54-湖仓层-pipelineslakehouse)
   - 5.5 [分析层 analytics/](#55-分析层-analytics)
   - 5.6 [受控 Agent 层 agent/](#56-受控-agent-层-agent)
   - 5.7 [工具治理层 tools/](#57-工具治理层-tools)
   - 5.8 [契约层 contracts/](#58-契约层-contracts)
   - 5.9 [可观测层 observability/](#59-可观测层-observability)
   - 5.10 [评测层 evals/](#510-评测层-evals)
   - 5.11 [技能层 skills/](#511-技能层-skills)
6. [关键类与函数说明](#6-关键类与函数说明)
7. [数据模型与依赖关系](#7-数据模型与依赖关系)
8. [项目运行方式](#8-项目运行方式)
9. [测试体系](#9-测试体系)
10. [核心实施原则](#10-核心实施原则)

---

## 1. 项目概述

**OmniSupport Copilot** 是面向虚构企业 **Northstar Systems** 的准生产级多模态 AI 支持系统。它将企业支持文档（PDF/HTML/FAQ/视频/音频）转化为可检索、可引用、可审计的知识层，并与工单系统联动，提供：

- 文档问答（RAG）与证据引用（evidence anchor）
- 工单查询 / 创建 / 更新（受控工具调用）
- 指标查询（KPI mart，受控口径）
- 人工介入（HITL）checkpoint
- 审计追踪（action lineage）
- 回归评测与版本回滚

### 业务世界观

| 产品线 | 定位 | 典型数据 |
|--------|------|---------|
| Northstar Workspace | 企业协作 / 工单 / 自动化 SaaS | Help Center, FAQ, Release Notes, API 文档, 工单 |
| Northstar Edge Gateway | 边缘采集设备 / 网关硬件 | PDF 安装手册, 规格说明, 接线图, 故障排查视频 |
| Northstar Studio | 实施与监控产品 | 教学视频, 录屏教程, 错误码手册, 社区问答 |

### 核心实施原则

1. **Data-first** — 先数据层，再生成层
2. **Workflow-first** — 先稳定工作流，再复杂 Agent
3. **Evidence-first** — 所有回答必须带 `evidence_anchor` / `citation`
4. **Release-aware** — 所有服务预埋 `release_id`, `trace_id`
5. **Dual-scale** — Student Core Pack（本地可跑）+ Instructor Scale Pack（规模演示）

---

## 2. 整体架构（七层模型）

系统采用分层架构，每层职责清晰、可独立演进：

```
┌─────────────────────────────────────────────────────────────────┐
│  Delivery Layer    │ Release Manifest / Rollback / Audit         │
├─────────────────────────────────────────────────────────────────┤
│  Application Layer │ RAG API (8000) │ Tool API (8001) │ Agent    │
├─────────────────────────────────────────────────────────────────┤
│  Retrieval Layer   │ Hybrid Retrieve │ Rerank │ Citation         │
├─────────────────────────────────────────────────────────────────┤
│  Semantic Layer    │ dbt KPI Mart │ Metric Registry │ Tool View  │
├─────────────────────────────────────────────────────────────────┤
│  Lakehouse Layer   │ Iceberg Bronze/Silver/Gold │ Time Travel    │
├─────────────────────────────────────────────────────────────────┤
│  Ingestion Layer   │ Seed Manifest │ Parse/Normalize │ Chunk      │
├─────────────────────────────────────────────────────────────────┤
│  Source Layer       │ PDF / HTML / FAQ / Audio / Video / Tickets  │
└─────────────────────────────────────────────────────────────────┘
        横切：contracts / observability / evals / skills / tests
```

### 数据流主线

```
source → ingestion(landing/bronze) → parse_normalize(silver)
       → lakehouse(iceberg) → semantic(dbt marts)
       → indexing(pgvector) → retrieval(hybrid) → application(RAG/Tool)
       → delivery(release manifest + audit)
```

### 运行时拓扑

| 组件 | 端口 | 职责 |
|------|------|------|
| RAG API | 8000 | 检索增强生成服务 |
| Tool API | 8001 | 工单工具 + HITL + 审计 |
| Dagster | 3000 | 资产化编排 UI |
| MinIO | 9000/9001 | S3 兼容对象存储 |
| PostgreSQL+pgvector | 15432 | 结构化存储 + 向量检索 |
| Phoenix | 6006 | AI 可观测 + bad case replay |
| OTel Collector | 4317/4318 | 统一 trace 采集 |

---

## 3. 技术栈与选型

| 层 | 技术 | 选型理由 |
|----|------|---------|
| 对象存储 | MinIO | 本地可跑，S3 兼容，迁移成本低 |
| 结构化 + 向量检索 | PostgreSQL + pgvector | 单机可跑，兼具结构化与向量/FTS |
| 湖仓层 | Apache Iceberg (PyIceberg) | 快照、时间旅行、Schema Evolution |
| 编排层 | Dagster | 资产化编排，讲依赖/回填/血缘/DoD |
| 服务层 | FastAPI | 契约清晰、调试成本低 |
| 分析层 | dbt Core | staging/intermediate/marts 分层 + metric registry |
| 可观测 | OpenTelemetry + Phoenix | 预埋 trace_id/release_id，衔接 tracing 与 bad case replay |
| 契约层 | JSON Schema | 数据/工具/发布契约均可机读校验 |
| LLM | Anthropic Claude | 生成层，可选（留空走 fallback） |
| 嵌入 | Voyage AI / OpenAI / sentence-transformers | 多后端，离线有 deterministic fallback |
| 本地工具执行 | Docker devbox | 学员无需配置本地 Python |

**语言与版本**：Python >= 3.11，构建系统 setuptools。代码风格 Ruff（line-length=100, py311），测试 pytest（asyncio_mode=auto）。

---

## 4. 仓库结构总览

```
omnisupport-copilot/
├── infra/                      # Docker Compose + DB migrations + 环境变量
│   ├── docker-compose.yml      # 10 个服务编排
│   ├── migrations/             # 001_init.sql ~ 009_week11_evaluation_system.sql
│   ├── env/.env.example        # 环境变量模板
│   ├── dagster.Dockerfile
│   └── devbox.Dockerfile       # 无本地 Python 依赖的验证容器
├── services/
│   ├── rag_api/                # FastAPI RAG 服务 (port 8000)
│   │   └── app/                # main / retrieval / generator / routers / models / prompts
│   └── tool_api/               # FastAPI 工单工具 + HITL + 审计 (port 8001)
│       └── app/                # routers / skill_registry / kpi_query / tool_contract_registry
├── pipelines/                  # Dagster 资产化 pipeline
│   ├── definitions.py          # Dagster 入口（注册所有资产/作业/资源）
│   ├── ingestion/              # seed loader + 采集资产
│   ├── data_factory/           # Week06 资产编排/partition/backfill/checks/evidence
│   ├── parse_normalize/        # 文档解析 + 切片 + 证据链 + 质量门禁
│   ├── lakehouse/              # Iceberg Bronze/Silver/Gold
│   ├── indexing/               # 向量索引构建（embedder）
│   ├── chunker/                # 多种切片策略（code_ast/contextual/late_chunking/structure_aware）
│   ├── retrieve/               # hybrid / rerank
│   ├── query/                  # multi_hop / rewriter / router
│   ├── parse/                  # marker_pipeline / pdf_typer / table_extractor
│   ├── multimodal/             # clip_embed
│   ├── audio/                  # process
│   ├── video/                  # pipeline
│   ├── incremental/            # update
│   ├── quality/                # drift_detector / report
│   └── resources/              # config / minio / postgres / reports
├── analytics/                  # dbt Core 项目 + KPI mart + metric registry
│   ├── dbt_project.yml
│   ├── metric_registry_v1.yml
│   └── models/{staging,intermediate,marts}/
├── contracts/                  # JSON Schema 契约
│   ├── data/                   # doc/ticket/audio/video 资产契约
│   ├── tools/                  # 工具契约 schema + 6 个工具定义
│   ├── agent/                  # hitl_approval / action_lineage_event
│   ├── evals/                  # eval_dataset / eval_report
│   ├── observability/          # incident / slo_report
│   ├── release/                # index_manifest / release_manifest
│   ├── run_evidence/           # week06_run_evidence
│   ├── service/                # citation / rag_request/response / retrieval_debug
│   └── skills/                 # skill_pack
├── agent/                      # 受控 Agent 控制面
│   ├── copilot.py              # ControlledAgent 主编排
│   ├── hitl.py                 # HITL 策略 + checkpoint store
│   └── lineage.py              # Action lineage event 模型
├── tools/                      # 工具治理原语
│   ├── registry.py             # ToolContractRegistry
│   ├── idempotency.py          # 幂等键派生 + 存储
│   ├── fallback.py             # FallbackChain
│   └── badcase_to_eval.py      # bad case 转评测集
├── observability/              # Week12 可观测闭环
│   ├── runtime/                # OTel setup / spans / privacy
│   ├── otel/config.yaml        # Collector 配置
│   ├── slo/, alerts/, dashboards/
│   └── week12/                 # badcase / incident / slo / closure
├── evals/                      # 评测体系
│   ├── harness/eval_runner.py  # 回归评测执行器
│   ├── week11/                 # 6 指标 + judge 校准 + 回归门禁 + A/B
│   ├── sets/                   # golden 评测集
│   └── run_ragas.py
├── skills/                     # Agent Skill Pack（5 个）
├── tests/                      # contract / integration / eval_regression
├── demos/                      # e2e happy/hitl/fallback 演示
├── data/                       # seed_manifests / synthetic_generators / canonization / week07_media
├── docs/blueprints/            # 按周交付蓝图
├── runbooks/                   # 运维操作手册
├── reports/                    # 各周产物报告
└── pyproject.toml
```

---

## 5. 核心模块详解

### 5.1 基础设施层 infra/

#### docker-compose.yml

定义 10 个服务，启动顺序：`postgres → minio → minio_init → phoenix → otel_collector → rag_api / tool_api → dagster → ticket_simulator / devbox`。

关键设计：
- **postgres** 使用 `pgvector/pgvector:pg16` 镜像，挂载 `migrations/` 到 `docker-entrypoint-initdb.d` 实现首启自动建表。
- **minio_init** 自动创建 8 个 bucket：`omni-raw-{documents,audio,video,tickets}`、`omni-parsed`、`omni-indexes`、`omni-evals`、`omni-releases`、`omni-lakehouse`。
- **devbox**（profile=tools）挂载整个仓库到 `/workspace`，作为统一本地执行入口，免本地 Python 配置。
- **dagster** 命令 `dagster dev -h 0.0.0.0 -p 3000 -m pipelines.definitions`，加载 `pipelines/definitions.py`。

#### migrations/ 数据库迁移

| 文件 | 内容 |
|------|------|
| 001_init.sql | 扩展（uuid-ossp/vector/pg_trgm）、枚举类型、Bronze/Silver 表、审计日志、release manifest |
| 002_eval_tables.sql | 评测表 |
| 003_week08_index_rag.sql | 索引与 RAG 相关表 |
| 004_week07_parse_normalize.sql | 解析规范化字段 |
| 005_week07_multimodal_parse.sql | 多模态解析 |
| 006_week07_ppt_alignment.sql | PPT 对齐 |
| 007_week03_ticket_ingest_idempotency.sql | 工单采集幂等 |
| 008_week10_controlled_agent.sql | 受控 Agent 表 |
| 009_week11_evaluation_system.sql | 评测系统表 |

**核心表结构（001_init.sql）**：
- Bronze：`raw_doc_asset`、`raw_ticket_event`
- Silver 结构化：`customer_dim`、`ticket_fact`、`ticket_comment_fact`
- Silver 知识：`knowledge_doc`、`knowledge_section`（含 `vector(1536)` 嵌入列 + GIN FTS 索引）、`evidence_anchor`
- 治理：`audit_log`、`source_manifest`、`release_manifest`

---

### 5.2 服务层 services/

#### 5.2.1 RAG API（services/rag_api/，port 8000）

**入口** [main.py](services/rag_api/app/main.py)：FastAPI 应用，集成 CORS、请求 ID 中间件、全局异常处理、OTel instrumentation。

**路由模块** `app/routers/`：
- `health.py` — `/health` 健康检查
- `rag.py` — `POST /rag/answer` Week8 契约优先 RAG 端点（核心）
- `query.py` — `/api/v1/query` 基础查询端点（带连接池）
- `admin.py` — `/api/v1/admin` 管理端点

**核心子模块**：
- [retrieval.py](services/rag_api/app/retrieval.py) — 混合检索（向量+FTS+RRF+Rerank）
- [generator.py](services/rag_api/app/generator.py) — Claude API 调用 + 证据引用生成
- `context_pruning.py` — 检索上下文裁剪
- `audit.py` — RAG 审计日志写入
- `observability.py` — 遥测封装
- `config.py` — 配置（环境变量）
- `models/rag_models.py` — Pydantic 请求/响应模型
- `prompts/` — 文件化 prompt 模板（system_v1.md / answer_v1.md / no_answer_v1.md）+ manifest

**RAG 请求链路**（`POST /rag/answer`）：
```
请求 → 生成 trace_id → hybrid_retrieve(向量+FTS→RRF→Rerank)
     → generate_grounded_answer(Claude/fallback) → 构建 citations
     → write_rag_audit_log → 返回 RagAnswerResponse
```
全程使用 `traced_span` 产出 OpenInference 兼容 span（CHAIN/RETRIEVER/RERANKER/LLM/TOOL）。

#### 5.2.2 Tool API（services/tool_api/，port 8001）

**入口** [main.py](services/tool_api/app/main.py)：注册 5 个路由前缀。

**路由模块** `app/routers/`：
- `health.py` — 健康检查
- `tickets.py` — `/api/v1/tools/{get_ticket_status,create_ticket}` 工单工具
- `kpis.py` — `/api/v1/tools/query_support_kpis_v1` 受控 KPI 查询
- `skills.py` — `/api/v1/skills` Skill Pack 发现
- `tool_contracts.py` — `/api/v1/tool_contracts` 工具契约发现/导出（OpenAI/MCP 格式）

**核心子模块**：
- `kpi_query.py` — 受控 KPI 查询（只读 `agent_tool_input_view`，拒 raw SQL）
- `metric_registry.py` — 指标注册表加载
- `skill_registry.py` — Skill Pack 注册表
- `tool_contract_registry.py` — 工具契约注册表

**工单工具**（tickets.py）当前为 Week01 骨架：参数校验 + HITL 触发判断（`_should_trigger_hitl`：p1_critical 或 p2_high+security 触发）+ 占位响应，Week10 替换为真实 DB CRUD。

---

### 5.3 编排层 pipelines/

#### definitions.py — Dagster 入口

[definitions.py](pipelines/definitions.py) 注册所有资产、作业、资源：

```python
defs = Definitions(
    assets=all_assets,              # ingestion + parse + lakehouse + data_factory + indexing
    asset_checks=all_asset_checks,  # data_factory checks
    jobs=[ingest_all_job, week06_data_factory_job],
    resources=build_week06_resources(),
)
```

#### 5.3.1 ingestion/ — 数据采集

[assets.py](pipelines/ingestion/assets.py) 定义采集资产图：
- `seed_manifests` — 加载 `data/seed_manifests/*.json`，输出有效清单列表
- `raw_doc_assets` — document 类型 manifest → Bronze 层元数据
- `raw_ticket_events` — structured 类型 manifest → Bronze 层
- `ingest_all_job` — 全量采集作业

其他文件：`db.py`（asyncpg 连接池）、`seed_loader.py`、`ticket_ingest.py`（Week03 工单采集）、`doc_ingest.py`、`ingest_state.py`（幂等状态）、`replay_backfill.py`、`reporting.py`。

#### 5.3.2 parse_normalize/ — 文档解析与切片（Week07）

[run_parse.py](pipelines/parse_normalize/run_parse.py) 是核心 CLI 与 pipeline。`run_parse_pipeline()` 执行：

```
load_sources → parse_documents → chunk_sections → build_evidence_anchors
            → evaluate_quality_gate → 写 artifacts/reports
            → (非 dry-run) _persist_to_db 写 PostgreSQL
```

**关键特性**：
- 多解析器：`auto/idp/marker/docling/unstructured/pypdf/pypdf_baseline/ocr/media/fallback`
- `_ensure_week07_parse_schema()` 兼容旧本地卷（ADD COLUMN IF NOT EXISTS）
- 质量门禁 `evaluate_quality_gate` 决定 `week8_ready`
- 写入 `knowledge_doc`/`knowledge_section`/`evidence_anchor`/`document_parse_run`/`chunk_quality_sample`

子模块：`parser_adapter.py`、`chunking.py`、`evidence_anchor.py`、`quality_gate.py`、`raw_loader.py`、`models.py`、`reporting.py`。

#### 5.3.3 data_factory/ — 资产编排（Week06）

[assets.py](pipelines/data_factory/assets.py) 定义 9 个分区化资产，构成完整数据工厂链路：

```
week06_source_seed_manifests
  → week06_factory_manifest_gate（准入门禁）
  → week06_raw_ticket_events_partitioned（复用 Week03 采集）
  → week06_ticket_fact_partitioned（Silver 投递摘要）
week06_lakehouse_state（观测 Week04）
week06_support_kpi_mart（观测 Week05）
week06_backfill_plan（dry-run 回填计划）
  → week06_run_evidence_report（运行证据 + checks）
  → week06_data_factory_delivery_summary（交付摘要）
```

支持 daily partition、backfill dry-run、asset checks、run evidence（schema 校验）。其他：`asset_keys.py`、`backfill_plan.py`、`checks.py`、`evidence.py`、`jobs.py`、`partitions.py`、`resources.py`。

#### 5.3.4 其他 pipeline 子模块

- `chunker/` — 切片策略：`code_ast.py`、`contextual.py`、`late_chunking.py`、`structure_aware.py`
- `retrieve/` — `hybrid.py`、`rerank.py`
- `query/` — `multi_hop.py`、`rewriter.py`、`router.py`
- `parse/` — `marker_pipeline.py`、`pdf_typer.py`、`table_extractor.py`
- `multimodal/clip_embed.py`、`audio/process.py`、`video/pipeline.py`
- `incremental/update.py`、`quality/{drift_detector,report}.py`
- `resources/` — `config.py`（DataFactorySettings）、`minio.py`、`postgres.py`、`reports.py`

---

### 5.4 湖仓层 pipelines/lakehouse/

[catalog.py](pipelines/lakehouse/catalog.py) 提供 PyIceberg SQL Catalog 操作：
- `load_lakehouse_catalog()` — 加载 catalog（PostgreSQL 作为 catalog URI，MinIO 作为 warehouse）
- `ensure_lakehouse_bucket()` — 创建 S3 bucket
- `ensure_namespaces()` — 创建 bronze/silver namespace
- `ensure_core_tables()` — 创建 4 张核心表（raw_ticket_event/raw_doc_asset/ticket_fact/knowledge_doc）
- `smoke_check()` — 一键冒烟

其他：`iceberg_schemas.py`（Bronze/Silver/Gold schema 定义）、`materialize.py`（物化）、`demo_time_travel.py`、`demo_schema_evolution.py`、`inspect_metadata.py`、`perf_baseline.py`、`settings.py`（LakehouseSettings）。

[assets.py](pipelines/lakehouse/assets.py) 提供 Dagster 薄包装（`iceberg_bronze_tables`/`iceberg_silver_tables`/`iceberg_gold_views`），主路径仍是 devbox CLI。

---

### 5.5 分析层 analytics/

dbt Core 项目（[dbt_project.yml](analytics/dbt_project.yml)），profile `omnisupport_analytics`，三层模型：
- `models/staging/` — `stg_customers`、`stg_knowledge_docs`、`stg_ticket_comments`、`stg_tickets`（materialized: view）
- `models/intermediate/` — `int_support_cases`、`int_ticket_activity_daily`（view）
- `models/marts/` — `support_case_mart`、`support_kpi_mart`、`agent_tool_input_view`（table）

**metric_registry_v1.yml** — 指标注册表，受控 KPI 查询工具只能查此处定义的指标。`scripts/validate_metric_registry.py` 校验注册表。

**治理边界**：Agent 只能通过 `query_support_kpis_v1` 查询 `agent_tool_input_view`，拒 raw SQL、不暴露 PII、不绕过 registry。

---

### 5.6 受控 Agent 层 agent/

[copilot.py](agent/copilot.py) 定义 `ControlledAgent` — **确定性控制面，非 LLM wrapper**。`invoke()` 执行流程：

```
1. contract.validate（jsonschema 校验 input_schema）
2. permission.evaluate（actor_role ∈ allowed_roles?）
3. hitl.evaluate（HITLPolicy 评估 hitl_conditions）
   → required: 创建 checkpoint，返回 awaiting_approval
4. (resume_approved) → idempotency.check（幂等键缓存/冲突）
5. tool.execute（FallbackChain 或自定义 executor）
6. lineage.persist（记录 ActionLineageEvent）
```

全程 `traced_span` 产出 AGENT/CHAIN/TOOL span。`resume_approved()` 处理 HITL 审批后恢复执行。

[hitl.py](agent/hitl.py)：
- `HITLPolicy` — 解析工具契约中的 `hitl_conditions` 条件语言（支持 `==/!=/>=/<=/>/<` + `AND`），按 action 优先级（reject>require_approval>pause_and_notify）选取
- `HITLCheckpointStore` — 内存 checkpoint 存储（create/get/decide）
- `ApprovalRequest` / `HITLEvaluation` / `HITLMatch` 数据类

[lineage.py](agent/lineage.py)：
- `ActionLineageEvent` — 动作血缘事件（含 `ActionBindings`：data_snapshot_id/evidence_ids/prompt_release_id/model_version/skill_release_id）
- `build_action_lineage_event()` — 工厂函数
- `to_openlineage_event()` — 转 OpenLineage 格式

---

### 5.7 工具治理层 tools/

[registry.py](tools/registry.py) — `ToolContractRegistry`：
- 从 `contracts/tools/tools/*.json` 加载工具契约，用 `tool_contract_schema.json` 校验
- `ToolContract` dataclass（name/version/allowed_roles/idempotent/hitl_conditions/failure_codes）
- `openai_tool_exports()` — 导出 OpenAI function calling 格式
- `mcp_tool_exports()` — 导出 MCP 格式（含 readOnlyHint/destructiveHint/idempotentHint）

[idempotency.py](tools/idempotency.py)：
- `derive_idempotency_key()` — 从契约 `idempotency_key_fields` 派生稳定键
- `InMemoryIdempotencyStore` — 幂等缓存（同 key+同 args 返回缓存；同 key+不同 args 抛 `IdempotencyConflict`）
- `stable_digest()` / `stable_json()` — 稳定哈希

[fallback.py](tools/fallback.py) — `FallbackChain`：
- 按 steps 顺序尝试 primary/retry/cache/graceful
- 每步 `traced_span`，失败记录并继续
- 全失败抛 `FallbackExhausted`，或返回 `graceful_response`
- `FallbackResult.to_dict()` 含 `fallback_level` + `fallback_attempts`

`badcase_to_eval.py` — bad case 转评测集。

**已注册工具**（contracts/tools/tools/）：`create_ticket`、`get_ticket_status`、`knowledge_search`、`search_knowledge`、`query_support_kpis_v1`、`ticket_update`。

---

### 5.8 契约层 contracts/

全部为 JSON Schema，机读校验贯穿全链路：

| 子目录 | 契约 |
|--------|------|
| `data/` | audio_asset / doc_asset / video_asset / ticket / document_chunk / evidence_anchor / knowledge_section / parse_run / chunk_quality_sample |
| `tools/` | tool_contract_schema + 6 个工具定义 |
| `agent/` | hitl_approval / action_lineage_event |
| `service/` | citation / rag_request / rag_response / retrieval_debug |
| `release/` | index_manifest / release_manifest |
| `run_evidence/` | week06_run_evidence |
| `evals/` | eval_dataset / eval_report |
| `observability/` | incident / slo_report |
| `skills/` | skill_pack |

---

### 5.9 可观测层 observability/

[runtime/setup.py](observability/runtime/setup.py) — 进程级 OTel 配置：
- `TelemetryConfig` dataclass（service_name/release_id/environment/endpoint/project_name/enabled/sample_ratio）
- `configure_telemetry()` — 配置 TracerProvider（ParentBased+TraceIdRatioBased 采样，BatchSpanProcessor，OTLP HTTP exporter）
- `instrument_fastapi_app()` — FastAPI 自动 instrumentation
- `force_flush()` — 优雅关闭

[runtime/spans.py](observability/runtime/spans.py)：
- `traced_span()` contextmanager — OpenInference 兼容 span（`openinference.span.kind`），自动属性截断（max 19 attrs, 512 chars）、异常记录、状态设置
- `current_trace_id()` — 获取当前 trace_id
- `set_span_attributes()` — 有界属性写入

`runtime/privacy.py` — 隐私工具（hash_text/safe_preview）。`otel/config.yaml` — Collector 配置。`slo/`、`alerts/`、`dashboards/` — SLO/告警/仪表盘。`week12/` — badcase/incident/slo/closure 闭环。

---

### 5.10 评测层 evals/

[harness/eval_runner.py](evals/harness/eval_runner.py) — 回归评测执行器：
- `EvalCase` / `EvalResult` / `EvalRunSummary` 数据类
- `MetricsCalculator` — 规则版指标（faithfulness/answer_relevance/retrieval_precision）
- `RAGAPIClient` — 调用 RAG API
- `EvalRunner.run()` — 并发执行评测集（Semaphore），汇总报告，pass_rate>=0.8 为 PASS 门禁

[week11/metrics.py](evals/week11/metrics.py) — Week11 确定性 6 指标：
- `score_case()` — 计算单用例分数
- 指标：faithfulness、answer_relevance、context_precision、context_recall、answer_correctness、semantic_similarity（余弦）、safety_pass（PII/禁用短语/应拒答检测）
- `_failure_reasons()` — 门禁失败原因（含阈值比较）
- 支持 CJK bigram tokenization

其他：`week11/{ab_test,calibrate,dataset,models,regression,runner,business_slo}.py`、`run_ragas.py`、`check_regression.py`、`sets/`（golden 评测集）、`judges/`（J2 模板）。

---

### 5.11 技能层 skills/

5 个 Agent Skill Pack，每个含 `SKILL.md` + `scripts/` + `references/` + `assets/`：
- `data-contract-lint/` — 数据契约 lint
- `ingest-backfill-runbook/` — 采集回填 runbook
- `prompt-release/` — prompt 发布计划
- `rag-contract-check/` — RAG 响应契约检查
- `release-check/` — 发布证据检查

---

## 6. 关键类与函数说明

### RAG 检索（services/rag_api/app/retrieval.py）

| 名称 | 类型 | 说明 |
|------|------|------|
| `RetrievalResult` | dataclass | 检索结果（chunk_id/evidence_id/scores: vector/fts/rrf/rerank/final） |
| `QueryEmbedder` | class | 查询嵌入生成，复用 pipelines.indexing.embedder，不可用降级为零向量 |
| `vector_search()` | async fn | pgvector ANN 余弦相似度检索（`1 - (embedding <=> query)`），支持元数据过滤 |
| `fts_search()` | async fn | PostgreSQL FTS（`to_tsvector @@ plainto_tsquery` + `ts_rank_cd`） |
| `reciprocal_rank_fusion()` | fn | RRF 融合：`Σ 1/(k + rank)`，k=60 |
| `CrossEncoderReranker` | class | Cross-Encoder 精排（sentence-transformers，不可用跳过） |
| `hybrid_retrieve()` | async fn | 主检索接口：vector+FTS → RRF → rerank → min_score 过滤 |

### RAG 生成（services/rag_api/app/generator.py）

| 名称 | 类型 | 说明 |
|------|------|------|
| `generate_answer()` | async fn | Claude API 生成带引用答案，返回 (answer, citations, confidence) |
| `generate_grounded_answer()` | async fn | Week8 契约版：context_pruning → 置信度门禁 → Claude/fallback，返回 (answer, confidence, abstain_reason) |
| `_extract_citations()` | fn | 从答案 `[来源N]` 标记提取引用 |
| `render_evidence_prompt()` | fn | 渲染文件化 prompt 模板（system_v1.md + answer_v1.md） |

### 受控 Agent（agent/）

| 名称 | 位置 | 说明 |
|------|------|------|
| `ControlledAgent` | copilot.py | 确定性控制面编排器（invoke/resume_approved/_execute） |
| `HITLPolicy` | hitl.py | 评估 hitl_conditions 条件语言 |
| `HITLCheckpointStore` | hitl.py | 内存审批 checkpoint 存储 |
| `ActionLineageEvent` | lineage.py | 动作血缘事件，支持 OpenLineage 转换 |
| `build_action_lineage_event()` | lineage.py | 血缘事件工厂 |

### 工具治理（tools/）

| 名称 | 位置 | 说明 |
|------|------|------|
| `ToolContractRegistry` | registry.py | 工具契约加载/校验/导出（OpenAI/MCP） |
| `ToolContract` | registry.py | 工具契约 dataclass |
| `derive_idempotency_key()` | idempotency.py | 从契约字段派生幂等键 |
| `InMemoryIdempotencyStore` | idempotency.py | 幂等缓存（同 key+同 args 命中；冲突抛异常） |
| `FallbackChain` | fallback.py | 多级降级链（primary/retry/cache/graceful） |

### Pipeline 核心（pipelines/）

| 名称 | 位置 | 说明 |
|------|------|------|
| `run_parse_pipeline()` | parse_normalize/run_parse.py | Week07 解析主流程（load→parse→chunk→anchor→gate→persist） |
| `build_index()` | indexing/embedder.py | pgvector 索引构建（批量嵌入+写回+IVFFlat 索引+manifest） |
| `EmbeddingProvider` | indexing/embedder.py | 多后端嵌入（Voyage/OpenAI/local/deterministic） |
| `ensure_core_tables()` | lakehouse/catalog.py | PyIceberg 建表（4 张核心表） |
| `run_ingest()` | ingestion/ticket_ingest.py | Week03 工单采集（Week06 复用） |
| `DataFactorySettings` | resources/config.py | Week06 配置（from_env） |

### 可观测（observability/runtime/）

| 名称 | 位置 | 说明 |
|------|------|------|
| `configure_telemetry()` | setup.py | 配置 TracerProvider + OTLP exporter |
| `traced_span()` | spans.py | OpenInference 兼容 span contextmanager |
| `current_trace_id()` | spans.py | 获取当前 trace_id |
| `TelemetryConfig` | setup.py | 遥测配置 dataclass |

### 评测（evals/）

| 名称 | 位置 | 说明 |
|------|------|------|
| `EvalRunner` | harness/eval_runner.py | 回归评测执行器（并发+汇总+门禁） |
| `MetricsCalculator` | harness/eval_runner.py | 规则版指标计算 |
| `score_case()` | week11/metrics.py | Week11 6 指标评分 |

---

## 7. 数据模型与依赖关系

### 数据库分层模型

```
BRONZE (Raw Zone)
├── raw_doc_asset        ← 文档资产元数据（source_id PK, MinIO 存文件）
└── raw_ticket_event     ← 工单事件原始 JSONB

SILVER (规范化)
├── customer_dim         ← 客户维度（PII: contact_email）
├── ticket_fact          ← 工单事实（FK customer_dim, 含 SLA/优先级/状态）
├── ticket_comment_fact  ← 工单评论
├── knowledge_doc        ← 知识文档元数据（FK raw_doc_asset）
├── knowledge_section    ← 知识 chunk（vector(1536) + GIN FTS, FK knowledge_doc）
└── evidence_anchor      ← 证据锚点（FK knowledge_section, 支持音视频时间戳）

GOLD (服务消费)
├── support_kpi_mart     ← dbt KPI mart（analytics/）
├── agent_tool_input_view ← Agent 只读视图（无 PII）
└── kb_serving_asset     ← RAG 检索消费（Week08）

治理
├── audit_log            ← Tool API 审计
├── source_manifest      ← 采集清单元数据
├── release_manifest     ← 版本追踪（data/index/prompt release_id 联动）
├── rag_audit_log        ← RAG 审计（Week08）
├── index_manifest       ← 索引版本清单
├── document_parse_run   ← 解析运行记录（Week07）
└── chunk_quality_sample ← chunk 质量样本
```

### 模块依赖关系

```
contracts/ ──(校验)──→ 所有层
observability/runtime ──(traced_span)──→ services + agent + pipelines + tools
tools/ ──(registry/idempotency/fallback)──→ agent + services/tool_api
agent/ ──(控制面)──→ tools + observability + contracts

pipelines/ingestion ──→ pipelines/lakehouse ──→ analytics (dbt)
                  └──→ pipelines/parse_normalize ──→ pipelines/indexing ──→ services/rag_api

services/rag_api ──→ pipelines/indexing (embedder) + observability
services/tool_api ──→ analytics (metric_registry) + skills + contracts + agent

evals ──→ services/rag_api (HTTP 调用)
```

### Release 四元组（版本联动）

所有服务预埋版本标识，贯穿可观测与回滚：
- `data_release_id` — 数据版本
- `index_release_id` — 索引版本
- `prompt_release_id` — prompt 版本
- `release_id` — 服务发布版本（聚合前三者 + git_sha + eval_run_id）

`release_manifest` 表记录每次发布的四元组 + previous_release_id，支持 30 分钟内回滚。

---

## 8. 项目运行方式

### 前置条件

- Docker Desktop / Docker Engine 24+ 与 Docker Compose V2
- 现代浏览器
- 可选：`ANTHROPIC_API_KEY`（留空走 fallback，不影响工程基线验证）

### 机器配置建议

| 场景 | CPU | 内存 | 磁盘 |
|------|-----|------|------|
| Student Core Pack 最低 | 4 核 | 16 GB | 25 GB |
| Student Core Pack 推荐 | 8 核 | 24 GB | 50 GB |
| Instructor Scale Pack | 8-12 核 | 32 GB+ | 80 GB+ |

### Week01 快速启动

```bash
# 1. 复制环境变量
cp infra/env/.env.example infra/env/.env.local

# 2. 启动所有服务
docker compose --env-file infra/env/.env.local -f infra/docker-compose.yml up -d --build

# 3. 验证健康
curl http://localhost:8000/health   # RAG API
curl http://localhost:8001/health   # Tool API
# 浏览器: localhost:3000 Dagster | :9001 MinIO | :6006 Phoenix

# 4. 生成种子工单
docker compose --profile tools --env-file infra/env/.env.local -f infra/docker-compose.yml run --rm devbox \
  python data/synthetic_generators/ticket_simulator.py --count 500 \
    --output data/canonization/tickets/tickets-seed-001.jsonl

# 5. dry-run seed loader
docker compose --profile tools --env-file infra/env/.env.local -f infra/docker-compose.yml run --rm devbox \
  python -m pipelines.ingestion.seed_loader \
    --manifest-path data/seed_manifests/manifest_edge_gateway_pdf_v1.json \
    --manifest-path data/seed_manifests/manifest_tickets_synthetic_v1.json \
    --manifest-path data/seed_manifests/manifest_workspace_helpcenter_v1.json

# 6. 运行契约测试
docker compose --profile tools --env-file infra/env/.env.local -f infra/docker-compose.yml run --rm devbox \
  pytest tests/contract/ -v
```

### 各周关键命令

| Week | 主命令 | 产物 |
|------|--------|------|
| W04 | `python -m pipelines.lakehouse.materialize --all-core` | Iceberg 四表物化 |
| W05 | `cd analytics && DBT_PROFILES_DIR=. dbt build --select tag:week05` | KPI mart |
| W06 | `python -m pipelines.data_factory.backfill_plan --partition 2026-04-17 --mode dry-run` | 运行证据 |
| W07 | `python -m pipelines.parse_normalize.run_parse --manifest-path ... --dry-run` | chunks + evidence anchors |
| W08 | `python -m pipelines.indexing.embedder --index-release-id ...` | pgvector 索引 |
| W10 | `python demos/e2e_hitl_path.py` | HITL 演示 |
| W11 | `python -m evals.week11.runner` | 评测报告 |
| W12 | `python -m observability.week12.run_closure` | 可观测闭环 |

### PostgreSQL 直连

```
Host: localhost  Port: 15432  Database: omnisupport  User: omni  Password: omnipass
```
（端口可通过 `POSTGRES_HOST_PORT` 覆盖）

### Lint / Typecheck / Test

```bash
ruff check .          # Linter (line-length=100, py311)
mypy services pipelines  # 类型检查
pytest tests/ -v      # 测试 (asyncio_mode=auto)
```

---

## 9. 测试体系

### tests/ 三层测试

| 目录 | 内容 | 示例 |
|------|------|------|
| `contract/` | JSON Schema 契约测试 | `test_week07_parse_contracts.py`、`test_week8_rag_contracts.py`、`test_week10_controlled_agent_contracts.py` |
| `integration/` | API smoke + pipeline 集成 | `test_rag_api_smoke.py`、`test_week07_parse_pipeline.py`、`test_week10_controlled_agent.py` |
| `eval_regression/` | 回归评测门禁 | `test_regression_gate.py` |

### 评测闭环

```
evals/sets/*.jsonl (golden) → EvalRunner → RAG API → MetricsCalculator
  → EvalRunSummary → regression_pass_rate >= 0.8 ? PASS : FAIL
  → evals/baselines/ 对比基线 → check_regression.py 门禁
  → bad case → badcase_to_eval.py → 回流评测集
```

### CI（.github/workflows/rag-eval-gate.yml）

RAG 评测门禁 CI，防止回归。

---

## 10. 核心实施原则

### 非功能性要求

- **可重复**：同 release 组合离线评测可复现
- **可观测**：所有请求携带 `trace_id`，关键 span 可查（Phoenix）
- **可回滚**：30 分钟内可回滚到上一稳定 release（release_manifest）
- **可审计**：高风险操作记录完整审计日志（audit_log + action lineage）

### Evidence-first 约束

- Citation 只能来自 `evidence_anchor`，不能由 LLM 编造
- Week07 不做 embedding，只标记 `allowed_for_indexing`
- Week08 只消费 `allowed_for_indexing=true` 且有 evidence anchor 的 chunk

### Release-aware 设计

- 所有服务预埋 `release_id` / `trace_id`
- OTel Resource 携带 `omni.release_id`
- 四元组版本（data/index/prompt/release）联动追踪

### 边界纪律

- Week06 复用 Week03 采集逻辑，不复制
- Week04 lakehouse / Week05 analytics 在 Week06 是 optional observation，缺失写 `not_available` 不伪造
- Dagster 是 thin wrapper，主路径是 devbox CLI
- Tool Contract Registry 只读，不执行危险动作
- `agent/copilot.py` 是确定性控制面，不是 LLM autonomous agent

---

## 附录：关键文件索引

| 关注点 | 入口文件 |
|--------|---------|
| 项目说明 | [README.md](README.md) |
| 服务编排 | [infra/docker-compose.yml](infra/docker-compose.yml) |
| Dagster 入口 | [pipelines/definitions.py](pipelines/definitions.py) |
| RAG API | [services/rag_api/app/main.py](services/rag_api/app/main.py) |
| RAG 端点 | [services/rag_api/app/routers/rag.py](services/rag_api/app/routers/rag.py) |
| 混合检索 | [services/rag_api/app/retrieval.py](services/rag_api/app/retrieval.py) |
| 生成器 | [services/rag_api/app/generator.py](services/rag_api/app/generator.py) |
| Tool API | [services/tool_api/app/main.py](services/tool_api/app/main.py) |
| 受控 Agent | [agent/copilot.py](agent/copilot.py) |
| HITL 策略 | [agent/hitl.py](agent/hitl.py) |
| 动作血缘 | [agent/lineage.py](agent/lineage.py) |
| 工具注册表 | [tools/registry.py](tools/registry.py) |
| 幂等 | [tools/idempotency.py](tools/idempotency.py) |
| 降级链 | [tools/fallback.py](tools/fallback.py) |
| 解析 pipeline | [pipelines/parse_normalize/run_parse.py](pipelines/parse_normalize/run_parse.py) |
| 索引构建 | [pipelines/indexing/embedder.py](pipelines/indexing/embedder.py) |
| 湖仓 catalog | [pipelines/lakehouse/catalog.py](pipelines/lakehouse/catalog.py) |
| Week06 资产 | [pipelines/data_factory/assets.py](pipelines/data_factory/assets.py) |
| OTel 配置 | [observability/runtime/setup.py](observability/runtime/setup.py) |
| Span API | [observability/runtime/spans.py](observability/runtime/spans.py) |
| 评测执行器 | [evals/harness/eval_runner.py](evals/harness/eval_runner.py) |
| Week11 指标 | [evals/week11/metrics.py](evals/week11/metrics.py) |
| 数据库初始化 | [infra/migrations/001_init.sql](infra/migrations/001_init.sql) |
| dbt 项目 | [analytics/dbt_project.yml](analytics/dbt_project.yml) |
