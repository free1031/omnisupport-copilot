# Week13 GraphRAG Runbook

所有命令都从仓库根目录执行。Docker 与 Podman 使用同一份 Compose；Podman
用户把 `docker compose` 替换成 `podman compose`。

## 0. 先确认目录和分支

```bash
pwd
git branch --show-current
```

`pwd` 必须以 `omnisupport-copilot` 结尾。不要在历史的 Week07/08/10
独立目录中执行 Week13。

## 1. 启动依赖

```bash
docker compose --env-file infra/env/.env.local -f infra/docker-compose.yml up -d --build \
  postgres minio minio_init rag_api
```

检查：

```bash
docker compose --env-file infra/env/.env.local -f infra/docker-compose.yml ps
curl -fsS http://localhost:8000/health
```

## 2. 执行 Week13 增量迁移

已有 volume 不会自动重跑 `/docker-entrypoint-initdb.d`，因此必须手动执行：

```bash
docker compose --env-file infra/env/.env.local -f infra/docker-compose.yml exec -T postgres \
  psql -U omni -d omnisupport < infra/migrations/010_week13_graphrag.sql
```

确认表已建立：

```bash
docker compose --env-file infra/env/.env.local -f infra/docker-compose.yml exec postgres \
  psql -U omni -d omnisupport -c "\dt graph_*"
```

## 3. 先生成可审查的构图报告

这一步只生成报告，用来检查 schema、别名合并和隔离记录：

```bash
docker compose --profile tools --env-file infra/env/.env.local -f infra/docker-compose.yml run --rm devbox \
  python -m pipelines.graph.build \
    --input data/week13/graph_source_chunks_v1.jsonl \
    --graph-release-id graph-week13-dev-v1 \
    --output reports/week13/graph-build-report.json
```

预期：`status=pass`，entity/edge/community 均大于 0，rejected 为 0。

## 4. 真实写入 PostgreSQL

下面不是 dry-run。它在一个事务中写 evidence projection、节点、边、社区和
release 状态：

```bash
docker compose --profile tools --env-file infra/env/.env.local -f infra/docker-compose.yml run --rm devbox \
  python -m pipelines.graph.build \
    --input data/week13/graph_source_chunks_v1.jsonl \
    --graph-release-id graph-week13-dev-v1 \
    --output reports/week13/graph-build-report.json \
    --persist \
    --index-release-id index-week08-dev
```

检查真实数据：

```bash
docker compose --env-file infra/env/.env.local -f infra/docker-compose.yml exec postgres \
  psql -U omni -d omnisupport -c \
  "SELECT graph_release_id, build_status, entity_count, edge_count, community_count FROM graph_release ORDER BY created_at DESC;"
```

```bash
docker compose --env-file infra/env/.env.local -f infra/docker-compose.yml exec postgres \
  psql -U omni -d omnisupport -c \
  "SELECT relation_type, count(*), min(cardinality(evidence_ids)) AS min_evidence FROM graph_relation_edge GROUP BY relation_type ORDER BY relation_type;"
```

`min_evidence` 必须大于 0。

`graph_release_id` 是不可变发布标识：相同内容、相同上游 release 重跑会安全地
no-op；内容或 `index_release_id` 变化时必须使用新的 `graph_release_id`，禁止静默
覆盖已发布图。

## 5. 调用真实 GraphRAG API

多跳路径：

```bash
curl -sS http://localhost:8000/rag/answer \
  -H 'Content-Type: application/json' \
  -d '{
    "question": "Northstar Workspace SSO login loop 的问题、症状和解决方案关系链",
    "retrieval_mode": "graph_multihop",
    "graph_release_id": "graph-week13-dev-v1",
    "max_graph_hops": 3,
    "include_debug": true
  }'
```

预期：

- `retrieval_mode=graph_multihop`；
- `citations` 和 `evidence_ids` 非空；
- `graph_debug.paths` 非空；
- `graph_debug.fallback_reason=null`；
- 没配置外部 LLM 时返回证据摘要 fallback，但证据检索、路径与审计是真实的。

自动路由：

```bash
curl -sS http://localhost:8000/rag/answer \
  -H 'Content-Type: application/json' \
  -d '{
    "question": "过去半年所有故障的共性是什么",
    "retrieval_mode": "auto",
    "graph_release_id": "graph-week13-dev-v1",
    "include_debug": true
  }'
```

简单 FAQ 继续走 `hybrid`，不能因为启用了 Week13 就把所有请求送进图。

## 6. 按题型运行 A/B 门禁

```bash
docker compose --profile tools --env-file infra/env/.env.local -f infra/docker-compose.yml run --rm devbox \
  python -m evals.graphrag_ab \
    --cases evals/fixtures/week13/graphrag_ab_cases_v1.jsonl \
    --vector-release-id index-week08-dev \
    --graph-release-id graph-week13-dev-v1 \
    --output reports/week13/graphrag-ab-report.json
```

课程 fixture 的预期路由是：factual 用 hybrid，local/global/multi_hop 才用图。
生产评测必须替换成真实影子流量/标注集，不能拿课程 fixture 当上线证据。

## 7. 跑 Week13 全套测试

```bash
docker compose --profile tools --env-file infra/env/.env.local -f infra/docker-compose.yml run --rm devbox \
  pytest \
    tests/contract/test_week13_graphrag_contracts.py \
    tests/integration/test_week13_graphrag_pipeline.py \
    tests/integration/test_week13_graph_postgres.py \
    tests/integration/test_week13_rag_api_real_graph.py \
    tests/integration/test_week13_definitions_loadable.py \
    -v
```

后两个真实测试会创建独立测试 release，验证后只删除该测试 release。

## 8. Dagster 资产

启动 Dagster 后，在 UI 中找到 `week13_graphrag` group，依次 materialize：

1. `week13_graph_release`
2. `week13_graph_build`

Dagster 资产用于编排和观察构图报告。课堂真实持久化仍使用第 4 节显式命令，
避免 UI 误操作覆盖 release。

## 9. 回滚

GraphRAG 的回滚是路由/release 回滚，不是删库：

1. 把服务的 `GRAPH_RELEASE_ID` 切回上一个 active release；
2. 或把请求路由统一切回 `hybrid`；
3. 将问题 release 标成 `deprecated`，保留图和 build report 供审计；
4. 重跑 Week11/13 门禁后再重新激活。

```sql
UPDATE graph_release
SET build_status = 'deprecated'
WHERE graph_release_id = 'graph-week13-dev-v1';
```

## Troubleshooting

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `relation graph_entity_node does not exist` | 老 volume 没执行 010 迁移 | 重跑第 2 节迁移 |
| API 返回 `retrieval_mode=hybrid` | 图无证据、图 release 不存在/非 active 或运行时降级 | 看 `graph_debug.fallback_reason` 和 Phoenix trace |
| 图里同一产品多个节点 | alias 未覆盖或模糊匹配进入隔离 | 查 `graph_build_quarantine`，人工确认后更新 schema alias |
| Global 结果空 | 没有 community 或 graph release 不一致 | 查 `graph_community` 与请求中的 `graph_release_id` |
| 多跳结果爆炸 | hop/result 边界被放宽 | 恢复最大 3 hops，收紧实体种子和 relation allowlist |
| `already exists with different content` | 试图用旧 ID 覆盖已发布图 | 生成新的 `graph_release_id`，通过路由切换和回滚管理版本 |
| Orphan container warning | 旧 compose 中仍有 console 服务 | 不是测试失败；确认不用后再单独清理 |
