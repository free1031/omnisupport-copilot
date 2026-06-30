"""Tool contract registry for Week10 controlled Agent execution.

The registry is intentionally read-only. It turns the JSON contracts under
``contracts/tools/tools`` into discovery metadata and OpenAI/MCP-compatible
descriptors without executing any business action.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jsonschema


class ToolContractRegistryError(ValueError):
    """Raised when a tool contract is missing or malformed."""


@dataclass(frozen=True)
class ToolContract:
    name: str
    version: str
    description: str
    path: str
    allowed_roles: list[str]
    idempotent: bool
    hitl_conditions: list[dict[str, Any]]
    failure_codes: dict[str, str]
    payload: dict[str, Any]

    @property
    def digest(self) -> str:
        from tools.idempotency import stable_digest

        return stable_digest(self.payload)

    def to_dict(self) -> dict[str, Any]:
        data = dict(self.payload)
        data["_path"] = self.path
        data["_digest"] = self.digest
        return data


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


class ToolContractRegistry:
    """Load and validate Agent tool contracts from disk."""

    def __init__(
        self,
        contracts_dir: str | Path | None = None,
        schema_path: str | Path | None = None,
    ) -> None:
        root = _project_root()
        self.contracts_dir = Path(contracts_dir) if contracts_dir else root / "contracts" / "tools" / "tools"
        self.schema_path = Path(schema_path) if schema_path else root / "contracts" / "tools" / "tool_contract_schema.json"
        self._schema: dict[str, Any] | None = None
        self._contracts: dict[str, ToolContract] | None = None

    def discover(self) -> list[ToolContract]:
        if self._contracts is None:
            self._contracts = self._load_all()
        return list(self._contracts.values())

    def get(self, name: str) -> ToolContract:
        if self._contracts is None:
            self._contracts = self._load_all()
        try:
            return self._contracts[name]
        except KeyError as exc:
            raise ToolContractRegistryError(f"tool contract not found: {name}") from exc

    def openai_tool_exports(self, names: list[str] | None = None) -> list[dict[str, Any]]:
        contracts = self._select(names)
        exports = []
        for contract in contracts:
            input_schema = copy.deepcopy(contract.payload["input_schema"])
            input_schema.setdefault("additionalProperties", False)
            exports.append(
                {
                    "type": "function",
                    "function": {
                        "name": contract.name,
                        "description": contract.description,
                        "strict": True,
                        "parameters": input_schema,
                    },
                    "x-omni-tool": {
                        "version": contract.version,
                        "digest": contract.digest,
                        "idempotent": contract.idempotent,
                        "allowed_roles": contract.allowed_roles,
                        "hitl_conditions": contract.hitl_conditions,
                    },
                }
            )
        return exports

    def mcp_tool_exports(self, names: list[str] | None = None) -> list[dict[str, Any]]:
        contracts = self._select(names)
        return [
            {
                "name": f"tools.invoke.{contract.name}",
                "description": contract.description,
                "inputSchema": contract.payload["input_schema"],
                "outputSchema": contract.payload["output_schema"],
                "annotations": {
                    "readOnlyHint": contract.name in {"search_knowledge", "knowledge_search", "get_ticket_status"},
                    "destructiveHint": any(
                        condition.get("action") == "require_approval"
                        for condition in contract.hitl_conditions
                    ),
                    "idempotentHint": contract.idempotent,
                },
                "x-omni-tool": {
                    "name": contract.name,
                    "version": contract.version,
                    "digest": contract.digest,
                },
            }
            for contract in contracts
        ]

    def _select(self, names: list[str] | None) -> list[ToolContract]:
        contracts = self.discover()
        if names is None:
            return contracts
        wanted = set(names)
        return [contract for contract in contracts if contract.name in wanted]

    def _load_schema(self) -> dict[str, Any]:
        if self._schema is None:
            self._schema = json.loads(self.schema_path.read_text(encoding="utf-8"))
        return self._schema

    def _load_all(self) -> dict[str, ToolContract]:
        if not self.contracts_dir.exists():
            raise ToolContractRegistryError(f"contracts directory not found: {self.contracts_dir}")

        schema = self._load_schema()
        contracts: dict[str, ToolContract] = {}
        for path in sorted(self.contracts_dir.glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            jsonschema.validate(payload, schema)
            name = payload["name"]
            if name in contracts:
                raise ToolContractRegistryError(f"duplicate tool contract name: {name}")
            contracts[name] = ToolContract(
                name=name,
                version=payload["version"],
                description=payload["description"],
                path=str(path),
                allowed_roles=list(payload["allowed_roles"]),
                idempotent=bool(payload["idempotent"]),
                hitl_conditions=list(payload.get("hitl_conditions", [])),
                failure_codes=dict(payload.get("failure_codes", {})),
                payload=payload,
            )
        return contracts
