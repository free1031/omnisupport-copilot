---
name: rag-contract-check
description: Check RAG API responses for evidence-derived citations, retrieval debug fields, release ids, trace ids, and structured abstain behavior.
version: 0.1.0
owner: ai-platform
status: active
tags:
  - rag
  - citations
  - retrieval
  - audit
not_for:
  - General language quality review with no RAG contract fields.
  - Prompt rewriting without response schema verification.
inputs:
  - contracts/service/rag_request.schema.json
  - contracts/service/rag_response.schema.json
  - services/rag_api/app/routers/rag.py
outputs:
  - reports/week09/rag_contract_check.md
requires:
  - data-contract-lint
compatible_agents:
  - codex
  - claude-code
  - mcp-compatible-agent
artifacts:
  - reports/week09/rag_contract_check.md
evals:
  - tests/contract/test_week8_rag_contracts.py
  - evals/week08/run_smoke_eval.py
---

# RAG Contract Check

Use this skill when validating a RAG response, debug payload, no-answer case, or
evidence citation path.

## Procedure

1. Validate the request and response shapes against `contracts/service/`.
2. Confirm `answer` is accompanied by evidence-derived `citations` and
   `evidence_ids` unless `abstain_reason` is set.
3. Confirm `release_id`, `data_release_id`, `index_release_id`,
   `prompt_release_id`, and `trace_id` are present.
4. If `include_debug=true`, check vector, FTS, RRF, rerank, and final scores.
5. Record any missing field as a contract failure, not a wording issue.

## Safety Boundaries

- Do not let the generator invent citation metadata.
- Do not treat structured abstain as a failure when evidence is absent.
- Do not hide low confidence or no-answer reasons.

