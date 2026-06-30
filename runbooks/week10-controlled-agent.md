# Week10 Controlled Agent Runbook

Week10 把前几周的能力放进受控 Agent 执行框架：

- Week05 的 `query_support_kpis_v1` 是只读 KPI 工具。
- Week08 的 RAG 被包装为 `knowledge_search` 工具。
- Week09 的 Skill Pack 继续作为可发现、可版本治理的操作说明。
- Week10 新增 `ticket_update` 这种可写动作，并要求幂等、HITL、fallback、action lineage。

## Code Architecture Map

![Week10 受控 Agent 文件级代码架构图](../docs/assets/week10/week10-controlled-agent-code-architecture.png)

Read this map before running the commands below. Week10 is the control plane
around tool execution: tool contracts define the allowed boundary,
`ControlledAgent` enforces the boundary, and idempotency / HITL / fallback /
lineage keep tool calls safe and traceable.

## 1. Inspect Tool Contracts

```bash
find contracts/tools/tools -maxdepth 1 -type f | sort
```

重点看：

- `contracts/tools/tools/knowledge_search.json`
- `contracts/tools/tools/ticket_update.json`
- `contracts/tools/tool_contract_schema.json`

## 2. Run Week10 Contract Tests

```bash
docker compose --profile tools --env-file infra/env/.env.local -f infra/docker-compose.yml run --rm devbox \
  pytest tests/contract/test_week10_controlled_agent_contracts.py -v
```

Expected:

- 所有 Tool Contract 都符合统一 schema。
- `ticket_update` 必须声明 `idempotency_key_fields`、HITL 条件和审计字段。
- `knowledge_search` 必须保留 evidence anchor 输出。

## 3. Run Controlled Agent Tests

```bash
docker compose --profile tools --env-file infra/env/.env.local -f infra/docker-compose.yml run --rm devbox \
  pytest tests/integration/test_week10_controlled_agent.py -v
```

Expected:

- 低风险动作可直接执行。
- 相同幂等键重复调用返回 cached，不重复执行。
- 金融动作先返回 `awaiting_approval`，审批通过后才能执行。
- fallback 链能从 primary failure 降级到 cache。
- action lineage 包含 data snapshot、evidence、prompt、model、skill、tool version。

## 4. Run Classroom E2E Demos

Happy path:

```bash
docker compose --profile tools --env-file infra/env/.env.local -f infra/docker-compose.yml run --rm devbox \
  python demos/e2e_happy_path.py
```

Fallback path:

```bash
docker compose --profile tools --env-file infra/env/.env.local -f infra/docker-compose.yml run --rm devbox \
  python demos/e2e_fallback_path.py
```

HITL path:

```bash
docker compose --profile tools --env-file infra/env/.env.local -f infra/docker-compose.yml run --rm devbox \
  python demos/e2e_hitl_path.py
```

课堂讲解顺序：

1. 先展示 `ticket_update.json`，说明“工具不是函数名，而是一份执行契约”。
2. 再跑 `e2e_happy_path.py`，证明低风险动作可以自动执行，并且第二次命中幂等缓存。
3. 再跑 `e2e_fallback_path.py`，说明 RAG 工具失败时不会乱答，而是走 fallback。
4. 最后跑 `e2e_hitl_path.py`，说明退款类高风险动作不会自动执行，必须审批后恢复。

## 5. Smoke Tool API Contract Discovery

Start services:

```bash
docker compose --env-file infra/env/.env.local -f infra/docker-compose.yml up -d --build postgres tool_api
```

Query:

```bash
curl http://localhost:8001/api/v1/tool-contracts
curl http://localhost:8001/api/v1/tool-contracts/ticket_update
curl http://localhost:8001/api/v1/tool-contracts/exports/openai
curl http://localhost:8001/api/v1/tool-contracts/exports/mcp
```

This endpoint is read-only. It does not mutate tickets or call external systems.

## 6. Week10 Mental Model

Do not explain Week10 as “Agent can do more things”. Explain it as:

> Agent 只有在 contract、permission、idempotency、HITL、fallback、lineage 都通过后，才可以执行动作。

This is the difference between a demo bot and a controllable production Copilot.
