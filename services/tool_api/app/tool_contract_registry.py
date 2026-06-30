"""Read-only Tool Contract registry for the Tool API service."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jsonschema


class ToolContractError(ValueError):
    """Raised when tool contract discovery fails."""


@dataclass(frozen=True)
class ToolContractMeta:
    name: str
    version: str
    description: str
    allowed_roles: list[str]
    idempotent: bool
    hitl_conditions: list[dict[str, Any]]
    digest: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "allowed_roles": self.allowed_roles,
            "idempotent": self.idempotent,
            "hitl_conditions": self.hitl_conditions,
            "digest": self.digest,
        }


class ToolContractRegistry:
    def __init__(self, contracts_path: str | Path, schema_path: str | Path):
        self.contracts_path = Path(contracts_path)
        self.schema_path = Path(schema_path)

    def discover(self) -> list[dict[str, Any]]:
        return [self._load_contract(path) for path in sorted(self.contracts_path.glob("*.json"))]

    def get(self, name: str) -> dict[str, Any]:
        for contract in self.discover():
            if contract["name"] == name:
                return contract
        raise ToolContractError(f"tool contract not found: {name}")

    def metas(self) -> list[ToolContractMeta]:
        return [
            ToolContractMeta(
                name=contract["name"],
                version=contract["version"],
                description=contract["description"],
                allowed_roles=list(contract["allowed_roles"]),
                idempotent=bool(contract["idempotent"]),
                hitl_conditions=list(contract.get("hitl_conditions", [])),
                digest=_digest(contract),
            )
            for contract in self.discover()
        ]

    def openai_exports(self) -> list[dict[str, Any]]:
        exports = []
        for contract in self.discover():
            input_schema = copy.deepcopy(contract["input_schema"])
            input_schema.setdefault("additionalProperties", False)
            exports.append(
                {
                    "type": "function",
                    "function": {
                        "name": contract["name"],
                        "description": contract["description"],
                        "strict": True,
                        "parameters": input_schema,
                    },
                    "x-omni-tool": {
                        "version": contract["version"],
                        "digest": _digest(contract),
                        "idempotent": contract["idempotent"],
                        "hitl_conditions": contract.get("hitl_conditions", []),
                    },
                }
            )
        return exports

    def mcp_exports(self) -> list[dict[str, Any]]:
        return [
            {
                "name": f"tools.invoke.{contract['name']}",
                "description": contract["description"],
                "inputSchema": contract["input_schema"],
                "outputSchema": contract["output_schema"],
                "annotations": {
                    "readOnlyHint": contract["name"] in {"search_knowledge", "knowledge_search", "get_ticket_status"},
                    "destructiveHint": any(
                        item.get("action") == "require_approval"
                        for item in contract.get("hitl_conditions", [])
                    ),
                    "idempotentHint": contract["idempotent"],
                },
                "x-omni-tool": {
                    "name": contract["name"],
                    "version": contract["version"],
                    "digest": _digest(contract),
                },
            }
            for contract in self.discover()
        ]

    def _load_contract(self, path: Path) -> dict[str, Any]:
        schema = json.loads(self.schema_path.read_text(encoding="utf-8"))
        contract = json.loads(path.read_text(encoding="utf-8"))
        jsonschema.validate(contract, schema)
        return contract


def _digest(value: dict[str, Any]) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
