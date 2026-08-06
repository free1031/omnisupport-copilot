# Week08 PPT Alignment Gap Check

This note maps `Week08-RAG服务化.pptx` to the repository implementation. It is
intended for instructor use and for students who need to locate code paths from
the slide deck.

## Executive Conclusion

There is no architectural conflict between the Week08 deck and the repository.
The repository implements the Week08 Student Core as a Docker/Podman-runnable
RAG service factory:

- versioned index build over `knowledge_section`;
- pgvector + PostgreSQL FTS + RRF hybrid retrieval;
- optional CrossEncoder rerank with safe RRF fallback;
- contract-first `/rag/answer` response with citations, evidence ids, release
  ids, prompt release id, trace id, debug scores, and audit log;
- file-backed prompt templates and smoke eval.

The deck also covers production extensions. Query Rewrite has since been
promoted into the online runtime with governed LLM output and deterministic
fallback. Other items below remain classroom-safe scaffolds or deferred work.

## Slide Concept To Code Map

| Deck concept | Repository path | Current status |
|---|---|---|
| `pipelines/retrieve/hybrid.py` | `pipelines/retrieve/hybrid.py` wrapping `services/rag_api/app/retrieval.py` | Path-compatible alias; runtime logic stays in one service module |
| pgvector + BM25/FTS + RRF | `services/rag_api/app/retrieval.py` | Implemented with pgvector, PostgreSQL FTS, RRF `k=60` |
| Rerank | `pipelines/retrieve/rerank.py`, `services/rag_api/app/retrieval.py` | Optional CrossEncoder; unavailable dependency falls back to RRF |
| Query Rewrite / HyDE | `pipelines/query/rewriter.py`, `services/rag_api/app/query_rewrite.py` | Production runtime integrated; strict LLM admission, timeout/retry/circuit breaker/cache, privacy-safe trace/audit, deterministic fallback; HyDE opt-in |
| Adaptive RAG router | `pipelines/query/router.py` | Deterministic route plan; LangGraph runtime is deferred |
| Multi-hop retrieval | `pipelines/query/multi_hop.py` | Plan object only; runtime loop deferred |
| Structured RAG response | `contracts/service/*.schema.json`, `services/rag_api/app/models/rag_models.py` | Implemented |
| Citations | `services/rag_api/app/routers/rag.py` | Derived from retrieval evidence metadata, not invented by LLM |
| Context Engineering | `services/rag_api/app/context_pruning.py` | Top-k + token budget strategy implemented |
| Prompt as Code | `services/rag_api/app/prompts/`, `services/rag_api/app/generator.py` | File-backed templates used by `/rag/answer` generation path |
| Prompt Cache | Not implemented | Deferred; can be added as provider-specific API integration |
| LLM-as-Judge / RAGAS | `evals/week08/run_smoke_eval.py` | Week08 smoke eval only; full judge harness deferred to Week11 |
| Bad Case Library | sample audit + future Week12 scope | Deferred to tracing/bad-case week |
| Canary / Feature Flag | release ids and manifests only | Runtime flag routing deferred |
| Release Manifest rollback | `contracts/release/release_manifest_schema.json` | Schema exists; rollback executor deferred to governance weeks |

## Teaching Positioning

Use this language in class:

- "Week08 has the production RAG minimum viable control plane."
- "Hybrid retrieval, RRF, structured response, citations, release ids, and audit
  are runnable."
- "Query Rewrite is wired into the production runtime with deterministic safety
  and release controls. HyDE stays off by default; Adaptive RAG, provider prompt
  cache and remaining extensions retain their documented boundaries."

Avoid saying:

- "Cohere rerank is fully integrated." The current implementation is
  CrossEncoder fallback, not Cohere API.
- "Anthropic Citations API is fully used." The current implementation uses
  retrieval-metadata citations and JSON schema contracts.
- "Prompt cache is active." It is not currently wired to Anthropic/OpenAI cache
  controls.
- "Week08 includes full production eval." Week08 has smoke eval; Week11 owns
  full LLM-as-Judge / regression evaluation.

## Recommended Follow-up Backlog

1. Add provider-specific Cohere rerank adapter behind the existing rerank
   interface.
2. Add Anthropic/OpenAI structured-output and citation adapter while preserving
   retrieval-metadata citation as the source of truth.
3. Add provider prompt-cache metrics when an API key and provider cache controls are
   configured.
4. Add a platform-level weighted canary executor; Query Rewrite already exposes
   release ids, quality gates and immediate deterministic/disabled rollback.
5. Add rollback executor after release manifest governance is
   introduced.
