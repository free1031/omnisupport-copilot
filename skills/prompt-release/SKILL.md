---
name: prompt-release
description: Prepare prompt-as-code changes with prompt release ids, regression checks, rollback notes, and links to RAG index and eval evidence.
version: 0.1.0
owner: ai-platform
status: active
tags:
  - prompt
  - release
  - rollback
  - eval
not_for:
  - One-off prompt brainstorming that will not be committed.
  - Changes that bypass RAG contract checks.
inputs:
  - services/rag_api/app/prompts/*
  - evals/week08/*
outputs:
  - reports/week09/prompt_release_plan.md
requires:
  - rag-contract-check
compatible_agents:
  - codex
  - claude-code
  - mcp-compatible-agent
artifacts:
  - reports/week09/prompt_release_plan.md
evals:
  - tests/integration/test_week8_prompt_release.py
---

# Prompt Release

Use this skill when a prompt template changes or when a prompt release needs
review, rollout, or rollback documentation.

## Procedure

1. Identify the changed prompt files and the new `prompt_release_id`.
2. Link the prompt release to the intended data and index release ids.
3. Run contract and smoke checks before promotion.
4. Capture expected behavior changes, bad-case risks, and rollback steps.
5. Write a release plan under `reports/week09/`.

## Safety Boundaries

- Do not change prompts without a release id.
- Do not promote prompt changes without regression evidence.
- Do not mix unrelated prompt and retrieval changes in one release note.

