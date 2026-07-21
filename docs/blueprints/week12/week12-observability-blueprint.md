# Week12 Full-Path Observability Blueprint

Week12 does not add a detached monitoring demo. It closes the loop around the
Week08 RAG path, Week10 controlled actions, and Week11 evaluation gate.

## Code Architecture Map

![Week12 full-path observability file-level code architecture](../../assets/week12/week12-observability-code-architecture.png)

Read the diagram from left to right. The upper lane follows the live distributed
trace from business code to Phoenix; the lower lane follows telemetry through
SLO evaluation, incident handling, bad-case conversion, and the Week11
regression gate. The three rails at the bottom are the identifiers that keep
the runtime and governance paths connected.

```text
request
  -> FastAPI server span and W3C trace context
  -> rag.query / agent.invoke
  -> retrieve / rerank / llm / tool / hitl / audit spans
  -> OTLP HTTP -> OTel Collector -> Phoenix
  -> dashboard/SLO decision -> alert context with sample trace IDs
  -> incident + postmortem
  -> bad case -> temporary Week11 eval set -> regression gate
```

## File-Level Map

```text
observability/runtime/
  privacy.py              PII redaction, bounded preview, stable digest
  setup.py                resource, sampler, span limits, OTLP exporter
  spans.py                OpenInference kind, status, trace-id helpers

services/rag_api/app/
  main.py                 FastAPI auto-instrumentation and trace response header
  routers/rag.py          query/intent/retrieve/generate/audit parent chain
  retrieval.py            vector/lexical/RRF/rerank child spans

services/tool_api/app/
  main.py                 FastAPI trace extraction and propagation
  routers/tickets.py      tool execution spans

agent/copilot.py          contract/permission/HITL/idempotency/execute/lineage spans
tools/fallback.py         one span per fallback attempt and graceful fallback

observability/week12/
  demo_flow.py            one trace across devbox -> RAG API -> Tool API
  verify_phoenix.py       query Phoenix and assert the required span tree
  slo.py                  deterministic SLI, error-budget, burn-rate evaluation
  incident.py             incident contract validation and postmortem rendering
  badcase.py              incident -> non-mutating Week11 regression assets
  run_closure.py          alert -> incident -> eval -> gate orchestration

observability/dashboards/week12_panels.yaml
observability/slo/week12_slo.yaml
observability/alerts/burn_rate.yaml
contracts/observability/*.schema.json
postmortems/template.md
```

## Span Naming Contract

Names follow `layer.action.strategy` and must explain the trace as a story:

| Layer | Required spans | Diagnostic question |
| --- | --- | --- |
| Request | `rag.query`, `agent.invoke` | Which user operation failed? |
| Intent | `rag.intent.route` | Why did the request choose RAG? |
| Retrieval | `rag.retrieve.vector`, `rag.retrieve.lexical`, `rag.retrieve.rrf` | Which retrieval leg lost candidates? |
| Rerank | `rag.rerank.cross` | How many candidates survived? |
| Generation | `llm.generate` | Which model/release answered with how much evidence? |
| Tool | `tool.execute.*`, `tool.fallback.*` | Which action or fallback failed? |
| HITL | `hitl.evaluate`, `hitl.wait`, `hitl.resume` | Was approval required and how long did it wait? |
| Evidence | `rag.audit.persist`, `agent.lineage.persist` | Was operational evidence persisted? |

## Data Safety

The default is `OTEL_CAPTURE_CONTENT=false`.

- Query and payload fields use SHA-256 digest plus length.
- Optional previews are redacted and capped at 200 characters.
- SDK span limits cap each span at 20 attributes and 512 bytes per value.
- Full prompts, answers, retrieved chunks, API keys, passwords, phone numbers,
  identity numbers, and payment card data do not belong in trace attributes.

## Two Verification Paths

The live path proves transport and context propagation:

```text
devbox root span -> RAG API child tree -> Tool API child span
                -> Collector -> Phoenix REST API verification
```

The deterministic path proves the operational learning loop without requiring
an external LLM:

```text
telemetry fixture -> SLO alert -> incident -> postmortem
                  -> Week11 regression sample -> eval gate
```

Both paths are required. A unit test alone does not prove OTLP/Phoenix wiring;
a screenshot alone does not prove regression closure.

## Scope Boundary

Student Core Pack includes self-hosted Phoenix, OTel Collector, the five panel
definitions, executable SLO evaluation, and bad-case regression closure.
Production expansion should add a managed trace store, retention policy,
tail-based sampling, Prometheus/Grafana or an APM backend, on-call routing, and
an incident system integration. The contracts and span names stay unchanged.
