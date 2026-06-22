"""Week09 Agent Skill Pack discovery endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.config import settings
from app.skill_registry import (
    SkillRegistry,
    SkillRegistryError,
    mcp_tool_exports,
    openai_tool_exports,
)

router = APIRouter(tags=["skills"])


def _registry() -> SkillRegistry:
    return SkillRegistry(settings.skill_registry_path)


@router.get("/skills", summary="List available Agent Skills")
async def list_skills(q: str | None = Query(default=None)) -> dict:
    registry = _registry()
    metas = registry.search(q) if q else registry.discover()
    return {
        "skills": [meta.to_dict() for meta in metas],
        "count": len(metas),
        "progressive_disclosure": {
            "stage_1": "list_skills returns frontmatter metadata only",
            "stage_2": "get_skill loads one SKILL.md body on demand",
            "stage_3": "scripts, references, and assets are listed for explicit use",
        },
        "release_id": settings.release_id,
    }


@router.get("/skills/{name}", summary="Load one Agent Skill")
async def get_skill(name: str) -> dict:
    try:
        detail = _registry().get_skill(name)
    except SkillRegistryError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return detail.to_dict() | {"release_id": settings.release_id}


@router.get("/skills/exports/openai", summary="Export skill activation descriptors for OpenAI tools")
async def export_openai_tools() -> dict:
    metas = _registry().discover()
    return {
        "format": "openai_tools",
        "tools": openai_tool_exports(metas),
        "count": len(metas),
        "release_id": settings.release_id,
    }


@router.get("/skills/exports/mcp", summary="Export skill activation descriptors for MCP-compatible clients")
async def export_mcp_tools() -> dict:
    metas = _registry().discover()
    return {
        "format": "mcp_tools",
        "tools": mcp_tool_exports(metas),
        "count": len(metas),
        "release_id": settings.release_id,
    }
