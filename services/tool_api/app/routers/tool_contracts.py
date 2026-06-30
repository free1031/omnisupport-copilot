"""Week10 read-only Tool Contract discovery endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.config import settings
from app.tool_contract_registry import ToolContractError, ToolContractRegistry

router = APIRouter(tags=["tool-contracts"])


def _registry() -> ToolContractRegistry:
    return ToolContractRegistry(
        contracts_path=settings.tool_contracts_path,
        schema_path=settings.tool_contract_schema_path,
    )


@router.get("/tool-contracts", summary="List governed Agent tool contracts")
async def list_tool_contracts() -> dict:
    metas = _registry().metas()
    return {
        "tools": [meta.to_dict() for meta in metas],
        "count": len(metas),
        "control_plane": {
            "schema": "contracts/tools/tool_contract_schema.json",
            "idempotency": "idempotency_key_fields",
            "hitl": "hitl_conditions",
            "audit": "audit_fields",
        },
        "release_id": settings.release_id,
    }


@router.get("/tool-contracts/{name}", summary="Load one governed tool contract")
async def get_tool_contract(name: str) -> dict:
    try:
        contract = _registry().get(name)
    except ToolContractError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return contract | {"release_id": settings.release_id}


@router.get("/tool-contracts/exports/openai", summary="Export governed tools for OpenAI function calling")
async def export_openai_tool_contracts() -> dict:
    exports = _registry().openai_exports()
    return {
        "format": "openai_tools",
        "tools": exports,
        "count": len(exports),
        "release_id": settings.release_id,
    }


@router.get("/tool-contracts/exports/mcp", summary="Export governed tools for MCP-compatible clients")
async def export_mcp_tool_contracts() -> dict:
    exports = _registry().mcp_exports()
    return {
        "format": "mcp_tools",
        "tools": exports,
        "count": len(exports),
        "release_id": settings.release_id,
    }
