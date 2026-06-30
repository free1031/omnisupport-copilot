"""Week10 low-risk tool path demo."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.copilot import ControlledAgent


async def run_demo() -> dict:
    agent = ControlledAgent()
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
        "trace_id": "trace_week10_happy_demo",
    }
    first = await agent.invoke("ticket_update", payload, actor_role="support_agent")
    second = await agent.invoke("ticket_update", payload, actor_role="support_agent")
    assert first["status"] == "completed"
    assert second["status"] == "cached"
    return {
        "first_call": first,
        "second_call_idempotent": second,
        "lineage_events": [event.to_dict() for event in agent.lineage_events],
    }


if __name__ == "__main__":
    print(json.dumps(asyncio.run(run_demo()), ensure_ascii=False, indent=2))
