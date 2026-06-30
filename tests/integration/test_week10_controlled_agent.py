import sys
import types
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent.copilot import ControlledAgent
from tools.fallback import FallbackChain


PROJECT_ROOT = Path(__file__).parent.parent.parent
TOOL_API_PATH = PROJECT_ROOT / "services" / "tool_api"
CONTRACTS_ROOT = PROJECT_ROOT / "contracts" / "tools" / "tools"
CONTRACT_SCHEMA = PROJECT_ROOT / "contracts" / "tools" / "tool_contract_schema.json"


def _ticket_payload(**overrides):
    payload = {
        "ticket_id": "TKT-20260417-A1B2C3",
        "operation": "add_internal_note",
        "reason": "Attach recovery runbook note for the assigned support engineer.",
        "actor_id": "agent_001",
        "actor_role": "support_agent",
        "risk_level": "internal_write",
        "evidence_ids": ["evd_week08_001"],
        "data_snapshot_id": "snapshot_week04_20260417",
        "prompt_release_id": "prompt-v0.1.0",
        "model_version": "classroom-deterministic",
        "skill_release_id": "skills-v0.1.0",
        "idempotency_key": "note-TKT-20260417-A1B2C3-001",
        "trace_id": "trace_week10_test",
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_low_risk_ticket_update_executes_and_reuses_idempotency_cache():
    agent = ControlledAgent()

    first = await agent.invoke(
        "ticket_update",
        _ticket_payload(),
        actor_role="support_agent",
    )
    second = await agent.invoke(
        "ticket_update",
        _ticket_payload(),
        actor_role="support_agent",
    )

    assert first["status"] == "completed"
    assert second["status"] == "cached"
    assert first["lineage_event_id"].startswith("act_")
    assert second["lineage_event_id"] == first["lineage_event_id"]
    assert len(agent.lineage_events) == 1


@pytest.mark.asyncio
async def test_high_risk_financial_action_requires_hitl_before_execution():
    executed = False

    def executor(payload):
        nonlocal executed
        executed = True
        return {
            "ticket_id": payload["ticket_id"],
            "operation": payload["operation"],
            "status": "completed",
        }

    agent = ControlledAgent()
    first = await agent.invoke(
        "ticket_update",
        _ticket_payload(
            operation="refund_payment",
            risk_level="financial",
            actor_role="billing_ops",
            amount_cents=500000,
            currency="USD",
            idempotency_key="refund-TKT-20260417-A1B2C3-001",
            trace_id="trace_week10_hitl_test",
        ),
        actor_role="billing_ops",
        executor=executor,
    )

    assert first["status"] == "awaiting_approval"
    assert executed is False
    assert first["approval_id"].startswith("apr_")

    agent.hitl_store.decide(
        first["approval_id"],
        approved=True,
        reviewer="lead_001",
        reason="Refund evidence matches policy.",
    )
    second = await agent.resume_approved(first["approval_id"], executor=executor)

    assert executed is True
    assert second["status"] == "completed"
    assert second["lineage_event_id"].startswith("act_")
    assert len(agent.lineage_events) == 2


@pytest.mark.asyncio
async def test_permission_denial_emits_lineage_without_execution():
    agent = ControlledAgent()
    result = await agent.invoke(
        "ticket_update",
        _ticket_payload(actor_role="support_agent"),
        actor_role="end_user",
    )

    assert result["status"] == "denied"
    assert result["denial_code"] == "PERMISSION_DENIED"
    assert len(agent.lineage_events) == 1
    assert agent.lineage_events[0].status == "denied"


@pytest.mark.asyncio
async def test_rag_tool_fallback_chain_returns_cache_with_audit_attempts():
    def primary(_payload):
        raise RuntimeError("vector index timeout")

    def cache(payload):
        return {
            "results": [
                {
                    "chunk_id": "chk_001",
                    "content": "Restart the connector and replay the recovery job.",
                    "score": 0.67,
                    "evidence_anchor": {
                        "source_id": "workspace_recovery_manual",
                        "source_url": "s3://omni-raw-documents/workspace/recovery/manual.pdf",
                        "page_no": 3,
                        "section_path": "Recovery > Connector restart",
                    },
                }
            ],
            "trace_id": payload["trace_id"],
            "release_id": "dev-local",
        }

    agent = ControlledAgent()
    result = await agent.invoke(
        "knowledge_search",
        {
            "query": "recover connector",
            "product_line": "northstar_workspace",
            "modalities": ["document"],
            "top_k": 3,
            "min_score": 0.6,
            "trace_id": "trace_week10_fallback_test",
        },
        actor_role="support_agent",
        executor=FallbackChain([("primary_vector_search", primary), ("lexical_cache", cache)]),
    )

    assert result["status"] == "completed"
    assert result["fallback_level"] == "lexical_cache"
    assert result["fallback_attempts"][0]["status"] == "failed"
    assert result["results"][0]["evidence_anchor"]["source_id"] == "workspace_recovery_manual"


def _clear_app_modules():
    for module_name in list(sys.modules):
        if module_name == "app" or module_name.startswith("app."):
            sys.modules.pop(module_name, None)


def _install_asyncpg_stub():
    if "asyncpg" in sys.modules:
        return
    asyncpg_stub = types.ModuleType("asyncpg")

    async def connect(*_args, **_kwargs):
        raise RuntimeError("asyncpg is not installed in the local tool contract test env")

    asyncpg_stub.connect = connect
    sys.modules["asyncpg"] = asyncpg_stub


def test_tool_api_contract_discovery_endpoints(monkeypatch):
    _clear_app_modules()
    monkeypatch.setenv("TOOL_CONTRACTS_PATH", str(CONTRACTS_ROOT))
    monkeypatch.setenv("TOOL_CONTRACT_SCHEMA_PATH", str(CONTRACT_SCHEMA))
    tool_api_path = str(TOOL_API_PATH)
    if tool_api_path in sys.path:
        sys.path.remove(tool_api_path)
    sys.path.insert(0, tool_api_path)
    _install_asyncpg_stub()

    from app.main import app

    client = TestClient(app, raise_server_exceptions=False)

    listing = client.get("/api/v1/tool-contracts")
    assert listing.status_code == 200
    listing_payload = listing.json()
    assert listing_payload["count"] >= 5
    assert any(tool["name"] == "ticket_update" for tool in listing_payload["tools"])

    detail = client.get("/api/v1/tool-contracts/ticket_update")
    assert detail.status_code == 200
    assert detail.json()["idempotency_key_fields"] == ["idempotency_key"]

    openai = client.get("/api/v1/tool-contracts/exports/openai")
    assert openai.status_code == 200
    assert any(tool["function"]["name"] == "ticket_update" for tool in openai.json()["tools"])

    mcp = client.get("/api/v1/tool-contracts/exports/mcp")
    assert mcp.status_code == 200
    assert any(tool["name"] == "tools.invoke.ticket_update" for tool in mcp.json()["tools"])

    _clear_app_modules()
