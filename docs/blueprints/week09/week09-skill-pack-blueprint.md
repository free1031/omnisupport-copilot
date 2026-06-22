# Week09 Skill Pack Blueprint

Week09 turns reusable engineering craft into portable Agent Skill Packs.

## Scope

Student Core implements:

- local `skills/` directory with one folder per skill;
- required `SKILL.md` frontmatter plus Markdown instructions;
- optional `scripts/`, `references/`, and `assets/` directories;
- `contracts/skills/skill_pack.schema.json`;
- Tool API discovery endpoints under `/api/v1/skills`;
- OpenAI tool and MCP-style activation descriptor exports;
- release manifest extension for `skill_release_id` and locked skill digests.

Out of scope for Week09:

- remote marketplace;
- script sandbox execution service;
- cross-team registry API with auth;
- automatic destructive actions.

## Initial Skills

| skill | purpose | upstream week |
|---|---|---:|
| `data-contract-lint` | data contract, PII, license, quality gate checks | Week02 |
| `ingest-backfill-runbook` | bounded replay/backfill planning | Week03/06 |
| `rag-contract-check` | RAG citations, evidence ids, release ids, debug fields | Week08 |
| `prompt-release` | prompt-as-code release and rollback planning | Week08 |
| `release-check` | pre-release data/index/prompt/skill/eval binding | Week14 prep |

## Progressive Loading

1. `GET /api/v1/skills` reads only frontmatter metadata.
2. `GET /api/v1/skills/{name}` loads one full `SKILL.md` body and lists
   scripts, references, and assets.
3. Script execution remains explicit and bounded; Week09 lists scripts but does
   not create a remote script runner.

## Compatibility Notes

- OpenAI export: `GET /api/v1/skills/exports/openai` returns strict
  function-tool activation descriptors.
- MCP export: `GET /api/v1/skills/exports/mcp` returns descriptors with
  `inputSchema`, `outputSchema`, and read-only annotations.
- Skills are instructions, not business actions. Action execution stays in
  Tool API contracts and later Week10 HITL controls.

## Quality Gates

Run:

```bash
pytest tests/contract/test_week09_skill_packs.py -v
pytest tests/integration/test_week09_skill_registry.py -v
```

