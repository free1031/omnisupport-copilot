# Week8 RAG Engineering Runbook

Week 8：从“搜得到”到“答得稳”——检索 × 生成的一体化工程闭环

## Scope

This runbook validates the Student Core path:

1. Contract tests for RAG request/response/citation/index manifest.
2. Index dry-run and index build with an explicit `index_release_id`.
3. Hybrid retrieval with pgvector, PostgreSQL FTS, RRF, metadata filters, and optional rerank.
4. Structured RAG API response with citations, release ids, prompt release id, and trace id.
5. Minimal audit log and smoke eval.

Week8 does not implement Week10 actions, Week11 full eval, Week12 tracing, Week13 GraphRAG, or Week14 release governance.

## Code Architecture Map

![Week08 RAG 服务化文件级代码架构图](../docs/assets/week08/rag-service-code-architecture.png)

Read this map before running the commands below. It shows the Week08 file-level
path:

- Week07 evidence-ready chunks enter through `knowledge_doc`,
  `knowledge_section`, and `evidence_anchor`.
- `pipelines/indexing/` builds a versioned index and binds
  `index_release_id`.
- `pipelines/query/` explains Query Rewrite, HyDE, and Adaptive RAG as
  deterministic classroom scaffolds.
- `services/rag_api/app/retrieval.py` owns the runnable pgvector + FTS + RRF +
  optional rerank path.
- `services/rag_api/app/context_pruning.py`, `services/rag_api/app/prompts/`,
  and `services/rag_api/app/generator.py` constrain generation to retrieved
  evidence.
- `services/rag_api/app/routers/rag.py`, `contracts/service/`, `audit.py`, and
  `evals/week08/` close the API, audit, eval, and release loop.

## PPT Alignment Boundary

The Week08 lesson deck uses several production labels. The runnable student
core maps them to these repository paths:

- `pipelines/retrieve/hybrid.py`: deck-compatible wrapper for the real runtime
  in `services/rag_api/app/retrieval.py`.
- `pipelines/retrieve/rerank.py`: deck-compatible rerank wrapper with the same
  fallback semantics as the API service.
- `pipelines/query/rewriter.py`: deterministic Query Rewrite / HyDE planning.
- `pipelines/query/router.py`: deterministic Adaptive RAG route planning.
- `services/rag_api/app/context_pruning.py`: top-k + token-budget context
  pruning.
- `services/rag_api/app/prompts/`: file-backed Prompt as Code templates.

See `docs/blueprints/week08/ppt-alignment-gap-check.md` for the full
"implemented / classroom fallback / deferred" map. In short: Hybrid retrieval,
RRF, structured response, evidence-derived citations, prompt release ids, audit,
and smoke eval are runnable. Cohere rerank, Anthropic native Citations API,
Prompt Cache, LLM-as-Judge, bad-case replay, canary routing, and rollback
execution are production extensions, not Week08 Student Core.

## Start local stack

```bash
cp infra/env/.env.example infra/env/.env.local

docker compose --env-file infra/env/.env.local -f infra/docker-compose.yml up -d --build

curl http://localhost:8000/health
```

Expected: the health endpoint returns `status`, `service`, `release_id`, `data_release_id`, `index_release_id`, and `prompt_release_id`.

## Run contract tests

```bash
docker compose --profile tools --env-file infra/env/.env.local -f infra/docker-compose.yml run --rm devbox \
  pytest tests/contract/ -v
```

Expected: Week8 schema fixtures validate. A no-answer response must still carry `index_release_id`, `prompt_release_id`, and `trace_id`.

## Build index in dry-run mode

```bash
docker compose --profile tools --env-file infra/env/.env.local -f infra/docker-compose.yml run --rm devbox \
  python -m pipelines.indexing.embedder \
  --index-release-id index-week08-dev \
  --batch-size 32 \
  --dry-run
```

Expected: no embeddings are written. A report is generated under `reports/week08/` and records provider/model/dimension/warnings.

## Build index

```bash
docker compose --profile tools --env-file infra/env/.env.local -f infra/docker-compose.yml run --rm devbox \
  python -m pipelines.indexing.embedder \
  --index-release-id index-week08-dev \
  --batch-size 32
```

Expected: chunks are embedded only if provider output dimension matches the database vector dimension. Dimension mismatch must be rejected and reported.

## Call RAG API

```bash
curl -X POST http://localhost:8000/rag/answer \
  -H "Content-Type: application/json" \
  -d '{
    "question": "How do I recover an Edge Gateway after firmware upgrade failure?",
    "product_line": "edge-gateway",
    "top_k": 5,
    "index_release_id": "index-week08-dev",
    "prompt_release_id": "prompt-week08-v1",
    "include_debug": true
  }'
```

Expected:

- Answer cases include `citations` and `evidence_ids` from retrieved evidence.
- No-answer cases include `abstain_reason`.
- Every response includes `release_id`, `data_release_id`, `index_release_id`, `prompt_release_id`, and `trace_id`.

## Run smoke eval

```bash
docker compose --profile tools --env-file infra/env/.env.local -f infra/docker-compose.yml run --rm devbox \
  python evals/week08/run_smoke_eval.py
```

Expected: `reports/week08/smoke_eval_report.md` is generated. In a database-empty environment, answer cases may pass as structured abstain. In the fully seeded environment, at least the known-hit cases should return citations.

## Common failures

| Symptom | Likely cause | Action |
|---|---|---|
| `dimension mismatch` | Provider output dim differs from pgvector column | Use the configured embedding model or migrate vector dimension deliberately. |
| Empty retrieval results | Index not built, filters too strict, or Week7 chunks unavailable | Run index build, check `index_release_id`, or use synthetic fixture fallback. |
| Reranker unavailable | Cross-Encoder dependency/model unavailable | Keep RRF fallback. Do not fail the API. |
| Citation missing | Retrieval result lacks evidence metadata | Fix retrieval projection. Do not let the generator invent citations. |
| No LLM key | Anthropic/OpenAI key absent | Return structured no-answer or citation-carrying fallback. |

## Handoff

Students submit:

- `reports/week08/index_build_report_<index_release_id>.md`
- `reports/week08/retrieval_smoke_report.md`
- `reports/week08/rag_api_smoke_report.md`
- `reports/week08/smoke_eval_report.md`
- Short answers for why vector-only retrieval is insufficient, why citations cannot be generated by the LLM, and why release ids must enter the response.
