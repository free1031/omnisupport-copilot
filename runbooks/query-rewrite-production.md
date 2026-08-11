# Query Rewrite 生产运行手册

## 1. 当前结论

Query Rewrite 已接入两个在线 RAG 入口：

- 主入口：`POST /rag/answer`
- 兼容入口：`POST /api/v1/query`

它不再是 `pipelines/query/` 下孤立的课堂示例。当前链路为：

```text
原始问题
  -> 确定性规范化与关键标识提取
  -> 可选 LLM Rewrite
  -> JSON/长度/关键标识安全门禁
  -> 向量 Query + FTS Query + 原始 rerank Query
  -> GraphRAG 或 Hybrid Retrieval
  -> 使用原始问题生成答案
  -> Trace + 无原文审计元数据
```

生产级在这里指代码已经具备可接入、可降级、可观测、可审计、可评测和
可回滚的工程闭环。正式流量上线仍必须使用目标模型和生产数据完成本文第
9 节的容量、质量与灰度验收；单元测试通过不能替代环境验收。

## 2. 代码主线

| 责任 | 文件 |
|---|---|
| 确定性安全底座、标识提取与无模型 fallback | `pipelines/query/rewriter.py` |
| 在线 Rewrite、缓存、单飞、重试、超时、熔断、输出校验 | `services/rag_api/app/query_rewrite.py` |
| 版本化 Rewrite Prompt | `services/rag_api/app/prompts/query_rewrite_v1.md` |
| `/rag/answer` 主链集成 | `services/rag_api/app/routers/rag.py` |
| 向量、FTS、rerank 三类 Query 分离 | `services/rag_api/app/retrieval.py` |
| API Debug 契约 | `contracts/service/query_rewrite.schema.json` |
| 审计字段迁移 | `infra/migrations/015_production_query_rewrite.sql` |
| 离线发布门禁 | `evals/query_rewrite/run_eval.py` |
| SLO、看板和告警 | `observability/{slo,dashboards,alerts}/query_rewrite*` |

## 3. 三条 Query 为什么必须分开

| Query | 用途 | 约束 |
|---|---|---|
| `vector_query` | 向量召回 | 使用语义改写；开启 HyDE 后使用经过校验的 HyDE 文档 |
| `lexical_query` | PostgreSQL FTS | 原问题放在最前，确保错误码、型号、版本等精确词不丢失 |
| 原始 `question` | CrossEncoder rerank 和答案生成 | 最终排序与回答必须服从用户原意，不服从 LLM 改写文本 |

这解决了工业场景里最常见的失败：为了扩大语义召回，错误码被模型改掉；
或者生成阶段直接使用扩写文本，导致答案回答了模型补充出来的问题。

## 4. 安全与正确性不变量

1. LLM 输出只能是严格 JSON，Markdown 代码块、额外字段和非法类型全部拒绝。
2. 错误码、产品型号、CVE、UUID 和版本号不得被删除；遗漏时由确定性层补回。
3. LLM 新增上述受保护标识时，整个候选结果被拒绝并重试或降级。
4. Rewrite 失败、超时、熔断或模型未配置时，RAG 请求继续执行确定性路径。
5. Trace、Debug 和 `rag_audit_log.query_rewrite` 默认只保存哈希、长度、模式、
   模型、版本、耗时和降级原因，不保存改写前后原文。发送给 Rewrite 模型和
   Embedding 的 Query 默认先做 PII 脱敏。
6. 缓存键包含租户、Query 哈希、模型、Prompt Release 和 HyDE 策略，禁止跨租户复用。
7. 同租户相同 Query 的并发请求使用 single-flight，避免缓存击穿和重复模型费用。
8. HyDE 默认关闭；只有独立评测证明收益后才能在灰度环境开启。

## 5. 运行配置

| 环境变量 | 默认值 | 生产含义 |
|---|---:|---|
| `QUERY_REWRITE_ENABLED` | `true` | 总开关；紧急回滚设为 `false` |
| `QUERY_REWRITE_STRATEGY` | `auto` | `auto/llm/deterministic/disabled` |
| `QUERY_REWRITE_PROVIDER` | 空 | 空值继承答案模型 Provider，也可独立配置 |
| `QUERY_REWRITE_MODEL` | 空 | 空值继承答案模型；生产建议使用低延迟小模型 |
| `QUERY_REWRITE_BASE_URL` | 空 | 空值继承答案模型地址 |
| `QUERY_REWRITE_PROMPT_RELEASE_ID` | `query-rewrite-v1` | 审计、评测和回滚使用的 Prompt 版本 |
| `QUERY_REWRITE_TIMEOUT_SECONDS` | `6` | 每次请求的 Rewrite 总时间预算，不是单次重试预算 |
| `QUERY_REWRITE_MAX_ATTEMPTS` | `2` | 应用层最大尝试次数 |
| `QUERY_REWRITE_MAX_OUTPUT_CHARS` | `1024` | 语义 Query/HyDE 输出长度上限 |
| `QUERY_REWRITE_MAX_TOKENS` | `256` | Rewrite 专用生成上限，不能沿用答案模型的 2048 |
| `QUERY_REWRITE_TEMPERATURE` | `0` | 确定性输出，便于缓存、复现和回归 |
| `QUERY_REWRITE_HYDE_ENABLED` | `false` | 高风险扩召回开关，默认关闭 |
| `QUERY_REWRITE_REDACT_PII` | `true` | 模型和语义检索前执行 PII 最小化；生产不得关闭 |
| `QUERY_REWRITE_CACHE_TTL_SECONDS` | `300` | 单实例内存缓存 TTL |
| `QUERY_REWRITE_CACHE_MAX_ENTRIES` | `2048` | 有界 LRU 容量 |
| `QUERY_REWRITE_CIRCUIT_FAILURE_THRESHOLD` | `5` | 连续失败后打开熔断器 |
| `QUERY_REWRITE_CIRCUIT_RECOVERY_SECONDS` | `30` | 半开探测等待时间 |

缓存是性能优化而不是正确性依赖。当前实现为进程内、有界、租户隔离缓存；
多副本之间不共享缓存，因此不会引入分布式一致性要求。需要全局成本优化时，
可以在保持相同 key 组成和 TTL 语义的前提下替换成 Redis。

## 6. 本地 Ollama 验证

```bash
cp infra/env/.env.example infra/env/.env.local
```

把 `.env.local` 设置为：

```dotenv
LLM_PROVIDER=ollama
LLM_MODEL=qwen3:14b
LLM_MAX_TOKENS=768
LLM_CONTEXT_TOKENS=8192
LLM_BASE_URL=http://host.docker.internal:11434/v1
QUERY_REWRITE_STRATEGY=llm
QUERY_REWRITE_ENABLED=true
QUERY_REWRITE_PROVIDER=ollama
QUERY_REWRITE_MODEL=qwen3:4b
QUERY_REWRITE_CONTEXT_TOKENS=2048
QUERY_REWRITE_BASE_URL=http://host.docker.internal:11434/v1
QUERY_REWRITE_HYDE_ENABLED=false
```

这里有意拆分模型：14B 负责最终证据答案，4B 负责低时延改写。Ollama 走
原生 `/api/chat`，以确保 `think=false` 和 JSON Schema 结构化输出真实生效；
不能只凭 OpenAI 兼容接口的配置字段判断思考已经关闭。

启动并调用：

```bash
docker compose --env-file infra/env/.env.local -f infra/docker-compose.yml up -d --build

curl -sS -X POST http://localhost:8000/rag/answer \
  -H 'Content-Type: application/json' \
  -H 'X-Service-Token: dev-internal-token-change-in-prod' \
  -H 'X-Actor-ID: instructor-local' \
  -H 'X-Actor-Role: instructor' \
  -H 'X-Tenant-ID: course-legacy' \
  -d '{
    "question":"How do I recover EG-3000 after EG-BOOT-004?",
    "retrieval_mode":"hybrid",
    "include_debug":true
  }' | jq '.query_rewrite_debug'
```

确认以下字段：

```json
{
  "mode": "llm",
  "provider": "ollama",
  "model": "qwen3:4b",
  "prompt_release_id": "query-rewrite-v1",
  "fallback_reason": null,
  "safety_repairs": []
}
```

如果 `mode=fallback`，根据 `fallback_reason` 检查 Ollama 可达性、JSON 输出、
超时或熔断状态。即使 Rewrite 降级，整个 RAG 请求也不应该返回 500。

## 7. 离线发布门禁

先跑无模型、完全可复现的安全基线：

```bash
python -m evals.query_rewrite.run_eval --strategy deterministic
```

再使用候选生产模型：

```bash
LLM_PROVIDER=ollama QUERY_REWRITE_PROVIDER=ollama \
QUERY_REWRITE_MODEL=qwen3:4b \
QUERY_REWRITE_BASE_URL=http://localhost:11434/v1 \
python -m evals.query_rewrite.run_eval \
  --strategy llm \
  --max-fallback-rate 0 \
  --max-latency-p95-ms 3000 \
  --output reports/query_rewrite/ollama_candidate.json
```

门禁必须同时满足：

- Case 通过率 100%；
- 受保护标识保留率 100%；
- 新增受保护标识率 0%；
- 模型标识符修复通过 `safety_repairs` 可见，最终检索不得包含新造标识；
- 降级率不高于当前发布阈值；
- p95 不高于当前发布阈值。

候选模型评测集必须补充真实脱敏 Bad Case；仓库内五个合成 Case 只负责代码
回归，不能代表生产业务分布。

## 8. 审计与 Phoenix 排障

Phoenix 中搜索 Span：`rag.query.rewrite`。建议按以下属性过滤：

- `omni.query_rewrite.mode`
- `omni.query_rewrite.provider`
- `omni.query_rewrite.model`
- `omni.query_rewrite.prompt_release_id`
- `omni.query_rewrite.fallback_reason`
- `omni.query_rewrite.circuit_state`

数据库审计示例：

```sql
SELECT
  created_at,
  trace_id,
  query_rewrite->>'mode' AS rewrite_mode,
  query_rewrite->>'provider' AS provider,
  query_rewrite->>'model' AS model,
  query_rewrite->>'fallback_reason' AS fallback_reason,
  query_rewrite->'safety_repairs' AS safety_repairs,
  (query_rewrite->>'latency_ms')::double precision AS latency_ms
FROM rag_audit_log
WHERE created_at >= now() - interval '1 hour'
ORDER BY created_at DESC;
```

## 9. 上线验收

1. 在 CI 中通过 Query Rewrite 单元、契约、集成和离线评测门禁。
2. 在预发使用与生产相同的模型、Prompt Release、网络出口和超时配置。
3. 使用脱敏生产样本比较“原 Query 检索”与“Rewrite 检索”的 Recall@K、
   MRR/nDCG、答案正确率、拒答率、p95/p99 和单请求成本。
4. 用独立服务副本承载 1% 流量，观察至少一个完整业务高峰；逐步扩到
   5%、25%、50%、100%，每级都检查本文 SLO。
5. 只有离线质量显著不退化、在线 fallback 低于 5%、p95 低于 500ms、
   无隐私红线时才能扩大流量。

容量测试至少覆盖：稳定 QPS、2 倍突发、模型超时、模型返回非法 JSON、模型
完全不可达、数据库审计不可用以及单租户热 Query 并发。验收重点不是“模型
永远成功”，而是所有故障下 RAG 仍然可用且决策可追踪。

## 10. 告警处置

| 告警 | 第一检查项 | 处置 |
|---|---|---|
| `QueryRewriteFallbackRatioHigh` | 按 provider/model/reason 分组 | 模型异常则切 `deterministic`，随后排查供应商 |
| `QueryRewriteCircuitOpen` | `fallback_reason` 与上游状态 | 保持 fallback，确认恢复后等待半开探测 |
| `QueryRewriteLatencyHigh` | cache hit、模型 p95、网络 | 降低超时/模型规格或切确定性策略 |
| 标识保留率下降 | 离线失败 Case | 阻断发布，不允许用线上 fallback 掩盖 |
| 新增标识率大于 0 | 候选模型输出 | 红线阻断，回滚 Prompt/模型版本 |

## 11. 回滚

最快回滚不需要代码发布：

```dotenv
QUERY_REWRITE_STRATEGY=deterministic
```

若要完全恢复原始 Query 行为：

```dotenv
QUERY_REWRITE_ENABLED=false
```

回滚后重新部署 RAG API，并通过 `/health` 确认 `checks.query_rewrite`，再用
`include_debug=true` 验证 `mode=deterministic` 或 `mode=disabled`。保留
`QUERY_REWRITE_PROMPT_RELEASE_ID` 和出问题的 Trace ID，用于复盘而不是覆盖审计证据。
