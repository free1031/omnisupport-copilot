"""Week10 HITL path demo.

Run from the project root:

    python demos/e2e_hitl_path.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.copilot import ControlledAgent


def _refund_payload() -> dict:
    return {
        "ticket_id": "TKT-20260417-A1B2C3",
        "operation": "refund_payment",
        "reason": "Customer was double charged during the recovery-window billing incident.",
        "actor_id": "agent_001",
        "actor_role": "billing_ops",
        "risk_level": "financial",
        "amount_cents": 500000,
        "currency": "USD",
        "evidence_ids": ["evd_week08_001", "evd_week08_002"],
        "data_snapshot_id": "snapshot_week04_20260417",
        "prompt_release_id": "prompt-v0.1.0",
        "model_version": "classroom-deterministic",
        "skill_release_id": "skills-v0.1.0",
        "idempotency_key": "refund-TKT-20260417-A1B2C3-incident-001",
        "trace_id": "trace_week10_hitl_demo",
    }


async def run_demo() -> dict:
    agent = ControlledAgent()
    first = await agent.invoke(
        "ticket_update",
        _refund_payload(),
        actor_role="billing_ops",
    )
    assert first["status"] == "awaiting_approval"

    agent.hitl_store.decide(
        first["approval_id"],
        approved=True,
        reviewer="support_lead_001",
        reason="Evidence and billing incident ID match the refund policy.",
    )
    second = await agent.resume_approved(first["approval_id"])
    assert second["status"] == "completed"

    return {
        "step_1_before_approval": first,
        "step_2_after_approval": second,
        "lineage_events": [event.to_dict() for event in agent.lineage_events],
    }


if __name__ == "__main__":
    print(json.dumps(asyncio.run(run_demo()), ensure_ascii=False, indent=2))
