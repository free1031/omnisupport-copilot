"""Emit one distributed Week12 trace through RAG API and Tool API."""

from __future__ import annotations

import argparse
import asyncio
import json
import os

import httpx
from opentelemetry.propagate import inject

from agent.copilot import ControlledAgent
from observability.runtime import (
    TelemetryConfig,
    configure_telemetry,
    current_trace_id,
    force_flush,
    traced_span,
)


def _post(client: httpx.Client, url: str, payload: dict, span_name: str) -> dict:
    with traced_span(span_name, kind="TOOL", attributes={"server.address": url}) as span:
        headers: dict[str, str] = {"X-Request-ID": f"week12-{span_name.replace('.', '-')}"}
        inject(headers)
        response = client.post(url, json=payload, headers=headers)
        span.set_attribute("http.response.status_code", response.status_code)
        response.raise_for_status()
        return response.json()


async def _run_hitl_path() -> dict:
    agent = ControlledAgent(release_id=os.getenv("RELEASE_ID", "dev-week12-local"))
    payload = {
        "ticket_id": "TKT-20260417-A1B2C3",
        "operation": "refund_payment",
        "reason": "Verified duplicate charge from the recovery-window billing incident.",
        "actor_id": "agent_week12_demo",
        "actor_role": "billing_ops",
        "risk_level": "financial",
        "amount_cents": 500000,
        "currency": "USD",
        "evidence_ids": ["ev-workspace-billing-001"],
        "data_snapshot_id": "snapshot_week04_20260417",
        "prompt_release_id": "prompt-v3.2.1",
        "model_version": "classroom-deterministic",
        "skill_release_id": "skills-v0.1.0",
        "idempotency_key": "refund-TKT-20260417-A1B2C3-week12-demo",
        "trace_id": current_trace_id(),
    }
    pending = await agent.invoke("ticket_update", payload, actor_role="billing_ops")
    agent.hitl_store.decide(
        pending["approval_id"],
        approved=True,
        reviewer="support_lead_week12",
        reason="Evidence and billing incident ID match the refund policy.",
    )
    completed = await agent.resume_approved(pending["approval_id"])
    return {"pending": pending, "completed": completed}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Week12 distributed tracing demo")
    parser.add_argument("--rag-api", default="http://rag_api:8000")
    parser.add_argument("--tool-api", default="http://tool_api:8001")
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args(argv)

    configure_telemetry(
        TelemetryConfig(
            service_name=os.getenv("OTEL_SERVICE_NAME", "week12_demo"),
            release_id=os.getenv("RELEASE_ID", "dev-week12-local"),
            environment=os.getenv("OTEL_ENVIRONMENT", "dev"),
            endpoint=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel_collector:4318"),
            project_name=os.getenv("OTEL_PROJECT_NAME", "omnisupport-copilot"),
            sample_ratio=1.0,
        )
    )

    with httpx.Client(timeout=args.timeout) as client:
        with traced_span(
            "omni.demo.flow",
            kind="AGENT",
            attributes={"omni.demo.week": "week12", "omni.demo.mode": "distributed"},
        ):
            trace_id = current_trace_id()
            rag = _post(
                client,
                f"{args.rag_api.rstrip('/')}/rag/answer",
                {
                    "question": "Workspace device offline heartbeat",
                    "product_line": "northstar_workspace",
                    "actor_role": "support_agent",
                    "top_k": 5,
                    "include_debug": True,
                },
                "client.rag_api",
            )
            tool = _post(
                client,
                f"{args.tool_api.rstrip('/')}/api/v1/tools/get_ticket_status",
                {"ticket_id": "TKT-20260417-000001", "include_comments": False},
                "client.tool_api",
            )
            agent_result = asyncio.run(_run_hitl_path())

    force_flush(10000)
    result = {
        "status": "pass",
        "trace_id": trace_id,
        "rag_trace_id": rag.get("trace_id"),
        "tool_trace_id": tool.get("trace_id"),
        "rag_abstain_reason": rag.get("abstain_reason"),
        "rag_evidence_count": len(rag.get("evidence_ids", [])),
        "tool_status": tool.get("status"),
        "agent_before_approval": agent_result["pending"].get("status"),
        "agent_after_approval": agent_result["completed"].get("status"),
    }
    result["same_distributed_trace"] = (
        result["trace_id"]
        == result["rag_trace_id"]
        == result["tool_trace_id"]
        == agent_result["pending"].get("trace_id")
        == agent_result["completed"].get("trace_id")
    )
    if not result["same_distributed_trace"]:
        result["status"] = "fail"
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
