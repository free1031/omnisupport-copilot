# Week14 Model System Card

## Runtime identity

- Release: `model-local-deterministic-v1`
- Provider: local
- Snapshot: `deterministic-course-baseline@sha256-pinned`
- Purpose: deterministic Student Core baseline for contracts, retrieval, evaluation, release and rollback tests

## Intended use

This snapshot proves the governance path without requiring an external model key. It may summarize
retrieved evidence but cannot authorize tools, override evidence gates, or make release decisions.

## Known limits

- It is not a production language model and is not evidence of production answer quality.
- Production releases must replace this entry with a provider snapshot that cannot drift behind an alias.
- The provider model card, safety evaluation, region, retention policy and contractual terms must be
  attached to the production release evidence pack.

## Controls

- Answers remain evidence-bound and carry release/trace identifiers.
- Week11 evaluation and Week12 SLO gates run before promotion.
- Week10 action tools retain permission, idempotency and HITL controls.
- Week14 release policy requires a signed manifest and four-eyes approval in `prod`.
