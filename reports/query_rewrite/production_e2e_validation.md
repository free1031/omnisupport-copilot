# Query Rewrite 生产级端到端验收报告

- 验收日期：2026-08-06
- 分支：`codex/production-query-rewrite`
- 基线：`origin/main@8310dd5`
- 工作区：`/Users/zengdan/Documents/New project/.worktrees/omnisupport-production-query-rewrite`
- 结论：**Query Rewrite 功能、降级、审计、可观测、RAG API 与产品 Auto Route 端到端本地验收通过**

## 1. 最终运行拓扑

| 职责 | Provider | Model | Context | 状态 |
|---|---|---|---:|---|
| Query Rewrite | 本地 Ollama | `qwen3:4b` | 2,048 | `llm_ready` |
| 证据答案生成 | 本地 Ollama | `qwen3:14b` | 8,192 | `external` |
| 结构化存储 | PostgreSQL | `rag_audit_log.query_rewrite JSONB` | - | 已迁移 |
| Trace | Phoenix / OTLP | `omnisupport-copilot` | - | 已入库 |

资源治理后 `ollama ps` 实测：4B 为 2.9GB，14B 为 10GB，两者可同时常驻。
未设置 context 上限时，4B 曾按 262K context 加载成约 41GB；该问题已通过
`QUERY_REWRITE_CONTEXT_TOKENS=2048` 和 `LLM_CONTEXT_TOKENS=8192` 修复。

## 2. 发布门禁结果

| 门禁 | 实测结果 | 判定 |
|---|---|---|
| 真实 Ollama 评测集 | 5/5 通过 | PASS |
| 受保护标识符保留率 | 100% | PASS |
| 最终结果新造标识符率 | 0% | PASS |
| Rewrite fallback 率 | 0% | PASS |
| Rewrite P95 | 1,296.83ms，门禁 3,000ms | PASS |
| 全量在线回归 | 227 passed，0 skipped | PASS |
| Ruff | All checks passed | PASS |
| 核心文件 mypy | 6 files，0 issue | PASS |

全量回归命令显式设置 `RAG_API_URL=http://rag_api:8000`，因此原先可能跳过的
在线回归用例已实际执行。唯一输出为 Starlette `python_multipart` 的上游
PendingDeprecationWarning，不影响本次功能。

## 3. 正常链路端到端证据

最终 API 请求使用 `retrieval_mode=auto`，问题包含 `WS-AUTH-001`，结果：

- Auto Route 正确选择 `hybrid`，没有被 Rewrite 添加的 `root cause` 误导到 Graph；
- Query Rewrite：`mode=llm`、`provider=ollama`、`model=qwen3:4b`；
- 首次 Rewrite：979.56ms，`fallback_reason=null`，`safety_repairs=[]`；
- 回答生成：`mode=llm`、`provider=ollama`、`model=qwen3:14b`；
- 返回受治理证据与引用，答案只使用证据中的 break-glass owner、IdP 元数据和证书指纹；
- Trace：`6c57f6e62f2c5207f3fca7bf331408ac`。

同租户同问题重复调用：

- `cache_hit=true`；
- Rewrite 延迟 0.25ms；
- Trace：`6f57493ad53892fc0eb8258c7aed3364`。

## 4. 产品界面验收

通过 Playwright 在 `http://localhost:8010` 实际完成：

1. 登录 Agent Workspace；
2. 选择工单 `TKT-20260623-900240`；
3. 使用产品默认 `Auto route` 提问；
4. 页面展示答案、5 个 Source 按钮、置信度、本地 `ollama · qwen3:14b` 和 trace 前缀；
5. 点击证据按钮后，Evidence detail 展示原文、Evidence ID、文档、Section、Source 和 Score；
6. 产品消息和 RAG 审计均已写入 PostgreSQL。

产品验收 Trace：`0b91578efd40bd38cd97667726257784`。数据库记录显示：

- 回答模型：`ollama / qwen3:14b`；
- Rewrite 模型：`ollama / qwen3:4b`；
- 请求模式为 `auto`，实际存在 `rag.retrieve.hybrid` Span；
- 5 条引用；
- 审计 JSON 不含 `original_query` 或 `semantic_query` 原文。

## 5. Phoenix 验收

Trace `0b91578efd40bd38cd97667726257784` 共观察到 19 类 Span，必需 Span 全部存在：

- `product.copilot.answer`
- `rag.query`
- `rag.query.rewrite`
- `rag.retrieve.hybrid`
- `llm.generate`
- `rag.audit.persist`

最终资源治理后的 API Trace `6c57f6e62f2c5207f3fca7bf331408ac` 也通过
Rewrite、Hybrid Retrieval、Generation 和 Audit 的完整 Span 验证。

## 6. 故障注入验收

临时把 `QUERY_REWRITE_BASE_URL` 指向不可达端口后，调用结果：

- HTTP 仍为 200；
- `mode=fallback`；
- `fallback_reason=llm_error:ConnectError`；
- `attempts=2`；
- 无证据时 `generation_mode=not_invoked`；
- `abstain_reason=no_retrieval_results`；
- Trace：`27aef68b5de282aaccccd4029febae91`。

故障注入完成后已恢复健康配置，RAG API、Copilot API、PostgreSQL、Tool API
均为 `ok`，产品首页 HTTP 200。

## 7. 验收边界

本报告证明代码与本地完整产品栈已经通过生产级工程验收。正式生产发布仍需在
目标基础设施使用脱敏真实流量完成容量压测、1% canary、业务指标观察和逐级放量；
这些属于部署环境验收，不能由本地测试替代。
