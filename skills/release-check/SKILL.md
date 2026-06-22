---
name: release-check
description: Verify that data, index, prompt, skill, eval, trace, and lineage evidence are bound before an OmniSupport release is promoted.
version: 0.1.0
owner: platform-governance
status: active
tags:
  - release
  - governance
  - lineage
  - eval
not_for:
  - Local scratch runs with no release intent.
  - Emergency rollback commands without operator approval.
inputs:
  - contracts/release/release_manifest_schema.json
  - reports/week*/**/*
outputs:
  - reports/week09/release_check_report.md
requires:
  - data-contract-lint
  - rag-contract-check
  - prompt-release
compatible_agents:
  - codex
  - claude-code
  - mcp-compatible-agent
artifacts:
  - reports/week09/release_check_report.md
evals:
  - tests/contract/test_week09_skill_packs.py
---

# Release Check

Use this skill before promoting a release or when verifying rollback readiness.

## Procedure

1. Load the release manifest and confirm it binds data, index, prompt, skill,
   eval, trace, and lineage evidence where applicable.
2. Check that each referenced artifact exists and has a stable identifier.
3. Verify all required tests or smoke reports passed.
4. Record incompatible versions or missing evidence as blockers.
5. Produce a release check report with promote, hold, or rollback advice.

## Safety Boundaries

- Do not promote without eval evidence.
- Do not accept unversioned prompt or skill references.
- Do not run rollback actions automatically; produce the checklist first.

