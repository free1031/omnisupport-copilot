# ADR-0014: Immutable manifest and atomic release pointer

- Status: accepted
- Date: 2026-07-20
- Scope: Week14 governance and versioning

## Context

By Week13, OmniSupport already emits data, index, prompt, skill, graph, eval and trace identifiers.
Those identifiers are useful for diagnosis but do not by themselves prevent partial deployment,
silent overwrite or an unreviewed rollback.

## Decision

1. Keep the v1 manifest for backward compatibility and introduce a strict v2 governed manifest.
2. Generate release IDs and artifact digests; never hand-edit an issued manifest.
3. Store manifests append-only. A release ID can be registered again only with the same digest.
4. Route an environment through one generation-checked pointer. Promotion and rollback switch that
   pointer in one PostgreSQL transaction and append a hash-chained audit event.
5. Permit rollback only to the direct previous manifest. Forward fixes use a new release ID.
6. Evaluate compliance red lines before quality gates. Missing observations do not pass.
7. Emit all six component versions as OpenLineage inputs and the governed release as one output.

## Consequences

- Week01-13 interfaces remain stable.
- Rollback is fast because data and derived assets remain immutable and addressable.
- Production services must resolve the active pointer rather than mix independent environment vars.
- External signing, lakeFS HA and deployment-controller integration remain deployment adapters; the
  control-plane contracts and deterministic tests are already executable locally.
