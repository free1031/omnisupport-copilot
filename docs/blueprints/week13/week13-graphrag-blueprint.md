# Week13 GraphRAG Production Blueprint

Week13 is a governed retrieval extension of the existing OmniSupport data and
RAG path. It is not an independent graph demo.

## Runtime Architecture

```text
Week07 evidence-ready knowledge_section + evidence_anchor
  -> pipelines/graph/schema.yaml
  -> extract.py -> align.py -> community.py -> build.py
  -> graph_release + entity_node + relation_edge + community + evidence projection
  -> services/graph/classifier.py
       factual/simple -------------------------------> Week08 hybrid retrieval
       local --------> local subgraph expansion -----+
       global -------> precomputed community summary +-> bounded graph serialization
       multi_hop ----> recursive path traversal -----+       + evidence chunks
       mixed --------> DRIFT-style local + global ---+
  -> services/rag_api/app/routers/rag.py
  -> mode-specific prompt + grounded answer + citation + audit + OTel trace
  -> evals/week13/ab.py per-category A/B gate
  -> release manifest binds graph/schema/classifier/routing policy
```

## File-Level Reading Path

| Order | File | Responsibility | Failure boundary |
| --- | --- | --- | --- |
| 1 | `pipelines/graph/schema.yaml` | Entity/relation allowlist and quality limits | Unknown types and invalid endpoints are rejected |
| 2 | `pipelines/graph/models.py` | Source, extraction, aligned graph and report models | Missing source identity/evidence fails before build |
| 3 | `pipelines/graph/extract.py` | Reviewed annotation or high-precision labeled extraction | Low-confidence output is not passed downstream |
| 4 | `pipelines/graph/align.py` | Normalization, aliases and conservative entity resolution | Ambiguous fuzzy matches enter quarantine |
| 5 | `pipelines/graph/community.py` | Deterministic Student Core connected communities | Summary contains only persisted members/evidence |
| 6 | `pipelines/graph/build.py` | Build orchestration, stable IDs, dedupe and report | Evidence-free edges cannot enter the graph |
| 7 | `pipelines/graph/store.py` | One-transaction PostgreSQL release persistence | A partial graph release cannot become active |
| 8 | `infra/migrations/010_week13_graphrag.sql` | Additive graph tables, constraints and indexes | No Week01-Week12 table is dropped or renamed |
| 9 | `services/graph/classifier.py` | Conservative query admission and routing | Low confidence returns to hybrid retrieval |
| 10 | `services/graph/store.py` | GraphStore protocol, PostgreSQL recursive traversal, test adapter | Scope and hop limits are enforced below prompts |
| 11 | `services/graph/retrieval.py` | Local/global/multi-hop/DRIFT retrieval | No graph evidence means fallback, not an invented answer |
| 12 | `services/graph/serialize.py` | Bounded path/community context | Graph context is capped before generation |
| 13 | `services/rag_api/app/routers/rag.py` | Backward-compatible runtime integration | Graph errors are recorded and degraded to hybrid |
| 14 | `services/rag_api/app/prompts/graph_*_v1.md` | Mode-specific generation constraints | Model cannot create source metadata |
| 15 | `evals/week13/ab.py` | Per-category quality/cost decision | An overall average cannot enable GraphRAG globally |

## Storage Model

- `graph_release`: immutable build identity and activation state.
- One graph release consumes exactly one upstream data release; a new upstream
  release produces a new graph release instead of mutating an existing graph.
- `graph_evidence_projection`: source content and citation fields frozen for a
  graph release. It prevents a later chunk update from silently rewriting old
  graph evidence.
- `graph_entity_node` and `graph_entity_alias`: canonical entity plus reviewed
  aliases, release and scope.
- `graph_relation_edge`: typed relation with source/target foreign keys,
  confidence, and mandatory evidence IDs.
- `graph_community` and `graph_community_member`: precomputed Student Core
  global-search projection.
- `graph_build_quarantine`: ambiguous or rejected build records for review.

## Retrieval Modes

| Mode | Use it for | Runtime behavior |
| --- | --- | --- |
| `hybrid` | FAQ, factual lookup, operating steps | Existing pgvector + FTS + RRF path |
| `graph_local` | One issue and its direct symptoms/resolutions | Seed entity plus one-hop expansion |
| `graph_global` | Cross-document common patterns | Ranked precomputed communities |
| `graph_multihop` | Explicit relationship chains | Bounded recursive traversal, maximum three hops |
| `graph_drift` | A focal entity plus broader pattern | Local paths plus global communities |
| `auto` | Runtime classification | Deterministic classifier; uncertain queries use hybrid |

## Production Boundaries

PostgreSQL is the runnable Student Core backend. `GraphStore` is the replacement
boundary for Neo4j or another graph engine at higher scale. A production adapter
must preserve:

- typed schema and endpoint validation;
- graph/data/index/prompt release binding;
- product and visibility scope;
- evidence IDs on every edge and returned path;
- maximum-hop and result/token budgets;
- trace attributes and degradation reason;
- per-category A/B and regression gates.

An external graph framework or LLM extractor does not get to bypass those
controls.

## Acceptance Criteria

1. Rebuilding the same source/release produces the same IDs and topology.
2. `Workspace` and `Northstar Workspace` resolve to one PRODUCT node.
3. All relation edges contain at least one evidence ID.
4. Local, global, multi-hop and DRIFT return evidence-backed contexts.
5. `/rag/answer` keeps `hybrid` as the default and graph failures degrade cleanly.
6. Real PostgreSQL persistence and API tests pass without dry-run.
7. A/B enables graph only for categories where the quality delta and cost guard pass.
