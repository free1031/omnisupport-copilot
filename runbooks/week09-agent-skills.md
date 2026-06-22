# Week09 Agent Skills Runbook

## Inspect Skill Packs

```bash
find skills -maxdepth 2 -type f | sort
```

Expected: five initial skills, each with `SKILL.md`, `scripts/`,
`references/`, and `assets/`.

## Run Contract Checks

```bash
pytest tests/contract/test_week09_skill_packs.py -v
```

Expected:

- every `SKILL.md` frontmatter validates against
  `contracts/skills/skill_pack.schema.json`;
- release manifest accepts optional skill bindings.

## Run Registry Checks

```bash
pytest tests/integration/test_week09_skill_registry.py -v
```

Expected:

- discovery returns metadata only;
- activation loads one skill body on demand;
- OpenAI and MCP exports include strict schemas;
- Tool API routes respond under `/api/v1/skills`.

## Local Tool API Smoke

```bash
SKILL_REGISTRY_PATH="$PWD/skills" PYTHONPATH=services/tool_api \
  uvicorn app.main:app --host 127.0.0.1 --port 8001
```

Then:

```bash
curl http://127.0.0.1:8001/api/v1/skills
curl http://127.0.0.1:8001/api/v1/skills/rag-contract-check
curl http://127.0.0.1:8001/api/v1/skills/exports/openai
curl http://127.0.0.1:8001/api/v1/skills/exports/mcp
```

## Classroom Explanation

Start from the folder shape:

```text
skills/<skill-name>/
  SKILL.md
  scripts/
  references/
  assets/
```

Then show Tool API progressive loading. The main distinction:

- Skill Pack: portable instructions and craft.
- Tool Contract: executable business action boundary.
- MCP/OpenAI export: adapter layer for discovery and activation.

