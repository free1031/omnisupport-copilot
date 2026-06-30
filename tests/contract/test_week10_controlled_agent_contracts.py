import json
from pathlib import Path

import jsonschema

from tools.registry import ToolContractRegistry


PROJECT_ROOT = Path(__file__).parent.parent.parent
TOOL_SCHEMA = PROJECT_ROOT / "contracts" / "tools" / "tool_contract_schema.json"
TOOL_CONTRACTS = PROJECT_ROOT / "contracts" / "tools" / "tools"
ACTION_LINEAGE_SCHEMA = PROJECT_ROOT / "contracts" / "agent" / "action_lineage_event.schema.json"
HITL_SCHEMA = PROJECT_ROOT / "contracts" / "agent" / "hitl_approval.schema.json"


def test_all_tool_contracts_match_week10_schema():
    schema = json.loads(TOOL_SCHEMA.read_text(encoding="utf-8"))
    names = set()
    for path in sorted(TOOL_CONTRACTS.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        jsonschema.validate(payload, schema)
        assert payload["name"] not in names
        names.add(payload["name"])
        assert payload["audit_fields"]["log_actor"] is True
        assert payload["failure_codes"]

    assert {"query_support_kpis_v1", "knowledge_search", "ticket_update"}.issubset(names)


def test_ticket_update_contract_blocks_uncontrolled_writes():
    contract = json.loads((TOOL_CONTRACTS / "ticket_update.json").read_text(encoding="utf-8"))

    assert contract["idempotent"] is True
    assert contract["idempotency_key_fields"] == ["idempotency_key"]
    assert "PERMISSION_DENIED" in contract["failure_codes"]
    assert "IDEMPOTENCY_CONFLICT" in contract["failure_codes"]
    assert any(
        item["action"] == "require_approval" and "refund_payment" in item["condition"]
        for item in contract["hitl_conditions"]
    )
    assert "evidence_ids" in contract["input_schema"]["properties"]
    assert "trace_id" in contract["input_schema"]["required"]


def test_knowledge_search_keeps_week08_evidence_contract():
    contract = json.loads((TOOL_CONTRACTS / "knowledge_search.json").read_text(encoding="utf-8"))
    result_item = contract["output_schema"]["properties"]["results"]["items"]

    assert "evidence_anchor" in result_item["required"]
    assert "trace_id" in contract["output_schema"]["required"]
    assert contract["idempotency_key_fields"] == ["query", "product_line", "top_k"]


def test_agent_control_plane_schemas_accept_sample_events():
    lineage_schema = json.loads(ACTION_LINEAGE_SCHEMA.read_text(encoding="utf-8"))
    hitl_schema = json.loads(HITL_SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(
        {
            "event_id": "act_001",
            "trace_id": "trace_001",
            "actor_id": "agent_001",
            "tool_name": "ticket_update",
            "tool_version": "v1.0",
            "status": "awaiting_approval",
            "approval_id": "apr_001",
            "audit_id": None,
            "bindings": {
                "data_snapshot_id": "snapshot_week04_20260417",
                "evidence_ids": ["evd_001"],
                "prompt_release_id": "prompt-v0.1.0",
                "model_version": "classroom-deterministic",
                "skill_release_id": "skills-v0.1.0",
            },
            "payload_digest": "abc123",
            "output_ref": None,
            "created_at": "2026-04-17T00:00:00+00:00",
        },
        lineage_schema,
    )

    jsonschema.validate(
        {
            "approval_id": "apr_001",
            "trace_id": "trace_001",
            "tool_name": "ticket_update",
            "action": "require_approval",
            "status": "pending",
            "reviewer": None,
            "decision_reason": None,
            "reason_codes": ["risk_level == 'financial'"],
            "payload_digest": "abc123",
            "created_at": "2026-04-17T00:00:00+00:00",
            "decided_at": None,
        },
        hitl_schema,
    )


def test_tool_contract_registry_exports_openai_and_mcp_descriptors():
    registry = ToolContractRegistry()
    names = {contract.name for contract in registry.discover()}
    openai_exports = registry.openai_tool_exports(["ticket_update"])
    mcp_exports = registry.mcp_tool_exports(["ticket_update"])

    assert "ticket_update" in names
    assert openai_exports[0]["function"]["name"] == "ticket_update"
    assert openai_exports[0]["function"]["strict"] is True
    assert openai_exports[0]["x-omni-tool"]["idempotent"] is True
    assert mcp_exports[0]["annotations"]["destructiveHint"] is True
