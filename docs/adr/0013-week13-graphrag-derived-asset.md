# ADR-0013: GraphRAG as a governed derived asset

- Status: accepted
- Date: 2026-07-20
- Scope: Week13 GraphRAG

## Context

Week13 must answer cross-document, global-summary, and multi-hop questions that
the Week08 chunk retrieval path cannot answer reliably. It must not create a
second ingestion, evidence, evaluation, or release system.

The classroom runtime also has two scales. Student Core must run with the
existing PostgreSQL/pgvector stack under Docker or Podman. A production
deployment may use a dedicated graph engine, but the storage choice must not
change API contracts, evidence lineage, routing, or evaluation.

## Decision

1. Graph data is derived from evidence-ready `knowledge_section` records. Every
   node and edge is bound to `graph_release_id`, source chunks, evidence IDs,
   and the upstream data/index release.
2. Entity and relation types are schema-first and allowlisted in
   `pipelines/graph/schema.yaml`. Unknown types and evidence-free edges are
   rejected, not silently persisted.
3. Student Core stores the graph in additive PostgreSQL tables and queries it
   through a `GraphStore` boundary. A Neo4j adapter may replace the store at
   instructor/production scale without changing higher layers.
4. Entity resolution auto-merges only deterministic aliases and high-confidence
   unique matches. Ambiguous candidates are quarantined for review.
5. `/rag/answer` remains backward compatible. Its default remains Week08
   hybrid retrieval. Graph modes are explicit or selected by a deterministic
   classifier and always fall back to hybrid retrieval on low confidence or
   runtime failure.
6. Local, global, multi-hop, and DRIFT-style retrieval return bounded graph
   evidence. Generation cannot invent graph citations; citations are built from
   persisted evidence metadata.
7. GraphRAG adoption is decided per query category by a Week11-compatible A/B
   gate. Overall-average improvement alone is not a release criterion.

## Consequences

- Week01-Week12 commands and default RAG behavior remain unchanged.
- PostgreSQL is a runnable baseline, not a claim that it replaces every
  dedicated graph database at large scale.
- Graph construction can be rebuilt and rolled back independently through
  `graph_release_id`.
- Production teams may plug in Neo4j or another backend, but must preserve the
  schema, source scope, evidence, release, observability, and evaluation rails.
