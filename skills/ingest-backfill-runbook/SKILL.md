---
name: ingest-backfill-runbook
description: Plan and execute safe ingestion replay or backfill runs with partition locks, idempotency checks, evidence outputs, and rollback notes.
version: 0.1.0
owner: data-platform
status: active
tags:
  - ingestion
  - backfill
  - replay
  - dagster
not_for:
  - Ad hoc SQL updates without source manifest or partition scope.
  - Destructive data deletion requests.
inputs:
  - data/seed_manifests/*.json
  - pipelines/data_factory/*
outputs:
  - reports/week09/backfill_runbook.md
requires:
  - data-contract-lint
compatible_agents:
  - codex
  - claude-code
  - mcp-compatible-agent
artifacts:
  - reports/week09/backfill_runbook.md
evals:
  - tests/integration/test_week06_backfill_plan.py
---

# Ingest Backfill Runbook

Use this skill when a task asks for replay, backfill, idempotent ingestion,
partition repair, or recovery after a failed ingest.

## Procedure

1. Identify the affected data release, source manifest, partitions, and
   downstream assets.
2. Confirm idempotency keys and partition boundaries before running anything.
3. Produce a dry-run plan with expected row counts and affected artifacts.
4. Execute only bounded runs. Record command, operator, timestamps, and output.
5. Write recovery evidence under `reports/week09/` and include rollback notes.

## Safety Boundaries

- Never run broad unscoped backfills.
- Never overwrite prior reports without preserving the original evidence.
- Escalate if partition locks or source fingerprints are missing.

