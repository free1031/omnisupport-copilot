---
name: data-contract-lint
description: Validate OmniSupport data contracts, seed manifests, PII metadata, license tags, and quality gates before data enters ingestion or indexing.
version: 0.1.0
owner: data-platform
status: active
tags:
  - data-contract
  - pii
  - license
  - quality-gate
not_for:
  - General JSON formatting with no data contract semantics.
  - Runtime database migration execution.
inputs:
  - contracts/data/*.json
  - data/seed_manifests/*.json
outputs:
  - reports/week09/data_contract_lint_report.md
requires:
  - jsonschema
compatible_agents:
  - codex
  - claude-code
  - mcp-compatible-agent
artifacts:
  - reports/week09/data_contract_lint_report.md
evals:
  - tests/contract/test_week09_skill_packs.py
---

# Data Contract Lint

Use this skill when a task mentions data contracts, source manifests, PII
classification, license tags, source fingerprints, or quality gates.

## Procedure

1. Read the target schema or manifest path.
2. Validate it against the matching JSON Schema in `contracts/data/` or
   `data/seed_manifests/source_manifest_schema.json`.
3. Check that `owner`, `license_tag`, `pii_level`, `quality_gate`,
   `ingest_batch_id`, and source traceability fields are present where the
   contract expects them.
4. Treat unknown license tags as blocking unless a manifest explicitly allows
   a fallback policy.
5. Write a concise report with severity, field path, reason, and suggested fix.

## Safety Boundaries

- Do not silently weaken a contract to make invalid data pass.
- Do not add real PII into examples or fixtures.
- Do not index assets that fail license or quality checks.

