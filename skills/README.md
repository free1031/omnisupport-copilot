# OmniSupport Skill Pack v0.1

Week09 introduces Agent Skills as portable engineering craft packages. Each
skill is a directory with:

- `SKILL.md`: required frontmatter plus execution instructions.
- `scripts/`: optional executable checks or helpers.
- `references/`: optional standards, runbooks, or examples loaded on demand.
- `assets/`: optional templates used to produce artifacts.

The Tool API exposes discovery endpoints under `/api/v1/skills`. Discovery
returns frontmatter only; full `SKILL.md` bodies are loaded only when a specific
skill is requested. This follows the Week09 progressive-disclosure model.

Initial skills:

- `data-contract-lint`
- `ingest-backfill-runbook`
- `rag-contract-check`
- `prompt-release`
- `release-check`

