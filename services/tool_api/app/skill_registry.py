"""Week09 Agent Skill Pack registry.

The registry implements the classroom progressive-disclosure model:

1. discovery reads only SKILL.md frontmatter;
2. activation reads the full SKILL.md body for one skill;
3. scripts, references, and assets are listed for on-demand use.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml


FRONTMATTER_RE = re.compile(r"^---\n(?P<frontmatter>.*?)\n---\n(?P<body>.*)$", re.DOTALL)
SKILL_NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")


class SkillRegistryError(ValueError):
    """Raised when a skill pack is malformed or cannot be resolved."""


@dataclass(frozen=True)
class SkillMeta:
    name: str
    description: str
    version: str
    path: str
    owner: str = "data-platform"
    status: str = "active"
    tags: list[str] = field(default_factory=list)
    not_for: list[str] = field(default_factory=list)
    inputs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    requires: list[str] = field(default_factory=list)
    compatible_agents: list[str] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    evals: list[str] = field(default_factory=list)
    digest: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SkillDetail:
    meta: SkillMeta
    body: str
    scripts: list[str]
    references: list[str]
    assets: list[str]

    def to_dict(self) -> dict[str, Any]:
        payload = self.meta.to_dict()
        payload.update(
            {
                "body": self.body,
                "scripts": self.scripts,
                "references": self.references,
                "assets": self.assets,
            }
        )
        return payload


def split_skill_markdown(text: str) -> tuple[dict[str, Any], str]:
    match = FRONTMATTER_RE.match(text)
    if not match:
        raise SkillRegistryError("SKILL.md must start with YAML frontmatter delimited by ---")
    frontmatter = yaml.safe_load(match.group("frontmatter")) or {}
    if not isinstance(frontmatter, dict):
        raise SkillRegistryError("SKILL.md frontmatter must be a mapping")
    return frontmatter, match.group("body").strip()


def _as_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return value
    raise SkillRegistryError("frontmatter list fields must be strings")


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _meta_from_markdown(path: Path, text: str) -> SkillMeta:
    frontmatter, _body = split_skill_markdown(text)
    name = frontmatter.get("name")
    description = frontmatter.get("description")
    version = str(frontmatter.get("version", "0.0.0"))
    if not isinstance(name, str) or not SKILL_NAME_RE.match(name):
        raise SkillRegistryError(f"invalid skill name in {path}")
    if not isinstance(description, str) or len(description.strip()) < 20:
        raise SkillRegistryError(f"invalid skill description in {path}")
    if path.parent.name != name:
        raise SkillRegistryError(f"skill folder name {path.parent.name!r} must match {name!r}")
    return SkillMeta(
        name=name,
        description=description.strip(),
        version=version,
        path=str(path.parent),
        owner=str(frontmatter.get("owner", "data-platform")),
        status=str(frontmatter.get("status", "active")),
        tags=_as_str_list(frontmatter.get("tags")),
        not_for=_as_str_list(frontmatter.get("not_for")),
        inputs=_as_str_list(frontmatter.get("inputs")),
        outputs=_as_str_list(frontmatter.get("outputs")),
        requires=_as_str_list(frontmatter.get("requires")),
        compatible_agents=_as_str_list(frontmatter.get("compatible_agents")),
        artifacts=_as_str_list(frontmatter.get("artifacts")),
        evals=_as_str_list(frontmatter.get("evals")),
        digest=_digest(text),
    )


class SkillRegistry:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self._metas: dict[str, SkillMeta] | None = None

    def discover(self) -> list[SkillMeta]:
        if self._metas is None:
            metas: dict[str, SkillMeta] = {}
            if not self.root.exists():
                self._metas = metas
                return []
            for skill_md in sorted(self.root.glob("*/SKILL.md")):
                text = skill_md.read_text(encoding="utf-8")
                meta = _meta_from_markdown(skill_md, text)
                if meta.name in metas:
                    raise SkillRegistryError(f"duplicate skill name: {meta.name}")
                metas[meta.name] = meta
            self._metas = metas
        return list(self._metas.values())

    def get_meta(self, name: str) -> SkillMeta:
        for meta in self.discover():
            if meta.name == name:
                return meta
        raise SkillRegistryError(f"skill not found: {name}")

    def get_skill(self, name: str) -> SkillDetail:
        meta = self.get_meta(name)
        skill_dir = Path(meta.path)
        text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
        _frontmatter, body = split_skill_markdown(text)
        return SkillDetail(
            meta=meta,
            body=body,
            scripts=_relative_files(skill_dir / "scripts", skill_dir),
            references=_relative_files(skill_dir / "references", skill_dir),
            assets=_relative_files(skill_dir / "assets", skill_dir),
        )

    def search(self, query: str) -> list[SkillMeta]:
        terms = [term for term in re.split(r"\W+", query.lower()) if term]
        if not terms:
            return self.discover()
        results = []
        for meta in self.discover():
            haystack = " ".join(
                [meta.name, meta.description, *meta.tags, *meta.inputs, *meta.outputs]
            ).lower()
            if all(term in haystack for term in terms):
                results.append(meta)
        return results


def _relative_files(root: Path, base: Path) -> list[str]:
    if not root.exists():
        return []
    return sorted(str(path.relative_to(base)) for path in root.rglob("*") if path.is_file())


def openai_tool_exports(metas: list[SkillMeta]) -> list[dict[str, Any]]:
    """Return OpenAI tool-compatible activation descriptors.

    Skills are instructions, not business actions, so the exported tool only
    activates a skill pack and returns an execution plan. Actual scripts remain
    explicit Stage 3 operations.
    """

    exports = []
    for meta in metas:
        tool_name = f"activate_skill_{meta.name.replace('-', '_')}"
        exports.append(
            {
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": meta.description,
                    "strict": True,
                    "parameters": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["task", "context_summary"],
                        "properties": {
                            "task": {
                                "type": "string",
                                "description": "The user task that triggered this skill.",
                            },
                            "context_summary": {
                                "type": "string",
                                "description": "Short summary of relevant repo or runtime context.",
                            },
                        },
                    },
                },
                "x-omni-skill": {
                    "name": meta.name,
                    "version": meta.version,
                    "digest": meta.digest,
                    "artifacts": meta.artifacts,
                },
            }
        )
    return exports


def mcp_tool_exports(metas: list[SkillMeta]) -> list[dict[str, Any]]:
    """Return MCP-style tool descriptors for skill activation."""

    return [
        {
            "name": f"skills.activate.{meta.name}",
            "description": meta.description,
            "inputSchema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["task", "context_summary"],
                "properties": {
                    "task": {"type": "string"},
                    "context_summary": {"type": "string"},
                },
            },
            "outputSchema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["skill", "version", "instructions"],
                "properties": {
                    "skill": {"type": "string"},
                    "version": {"type": "string"},
                    "instructions": {"type": "string"},
                    "artifacts": {"type": "array", "items": {"type": "string"}},
                },
            },
            "annotations": {
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
            },
            "x-omni-skill": {
                "name": meta.name,
                "version": meta.version,
                "digest": meta.digest,
            },
        }
        for meta in metas
    ]
