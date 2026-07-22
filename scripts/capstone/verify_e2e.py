"""Verify the product control plane through its public HTTP APIs.

The verifier intentionally exercises real persistence and one approved service
credit. Re-running it is safe because every write uses a unique idempotency key.
"""

from __future__ import annotations

import argparse
import json
import time
import uuid
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import httpx

from observability.week12.verify_phoenix import fetch_trace


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _trace_has(
    *, base_url: str, project: str, trace_id: str, required: set[str], retries: int = 15
) -> dict[str, Any]:
    trace = None
    names: set[str] = set()
    for _ in range(retries):
        trace = fetch_trace(base_url, project, trace_id)
        names = {span["name"] for span in trace.get("spans", [])} if trace else set()
        if required.issubset(names):
            break
        time.sleep(1)
    missing = sorted(required - names)
    _check(trace is not None, f"trace not found in Phoenix: {trace_id}")
    _check(not missing, f"trace {trace_id} is missing spans: {', '.join(missing)}")
    return {"trace_id": trace_id, "span_count": len(names), "required_spans": sorted(required)}


def _login(client: httpx.Client, email: str, password: str) -> tuple[str, dict[str, Any]]:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    response.raise_for_status()
    body = response.json()
    return body["access_token"], body["user"]


def _request(
    client: httpx.Client,
    token: str,
    method: str,
    path: str,
    **kwargs: Any,
) -> httpx.Response:
    headers = dict(kwargs.pop("headers", {}))
    headers["Authorization"] = f"Bearer {token}"
    response = client.request(method, path, headers=headers, **kwargs)
    response.raise_for_status()
    return response


def _select_workspace_case(client: httpx.Client, token: str) -> dict[str, Any]:
    items = _request(client, token, "GET", "/api/v1/cases?limit=100").json()["items"]
    for item in items:
        detail = _request(client, token, "GET", f"/api/v1/cases/{item['ticket_id']}").json()["case"]
        if detail["product_line"] == "northstar_workspace":
            return detail
    raise RuntimeError("no northstar_workspace case found")


def run(args: argparse.Namespace) -> dict[str, Any]:
    run_id = uuid.uuid4().hex[:12]
    report: dict[str, Any] = {"status": "running", "run_id": run_id, "checks": {}}
    with httpx.Client(base_url=args.base_url.rstrip("/"), timeout=60.0) as client:
        live = client.get("/live")
        live.raise_for_status()
        ready = client.get("/health")
        ready.raise_for_status()
        _check(ready.json()["status"] == "ok", "product dependencies are degraded")
        report["checks"]["runtime"] = ready.json()

        agent_token, agent = _login(client, args.agent_email, args.agent_password)
        admin_token, admin = _login(client, args.admin_email, args.admin_password)
        _check(agent["tenant_id"] == admin["tenant_id"], "demo users are in different tenants")
        report["checks"]["identity"] = {
            "tenant_id": agent["tenant_id"],
            "agent_role": agent["role"],
            "admin_role": admin["role"],
        }

        case = _select_workspace_case(client, agent_token)
        _check(case["tenant_id"] == agent["tenant_id"], "case escaped tenant boundary")
        report["checks"]["case_queue"] = {
            "ticket_id": case["ticket_id"],
            "product_line": case["product_line"],
        }

        conversation = _request(
            client,
            agent_token,
            "POST",
            f"/api/v1/cases/{case['ticket_id']}/conversations",
            json={"title": f"Capstone E2E {run_id}"},
        ).json()
        answer_response = _request(
            client,
            agent_token,
            "POST",
            f"/api/v1/conversations/{conversation['conversation_id']}/messages",
            json={
                "question": "What must happen before rotating a Workspace webhook signing secret?",
                "retrieval_mode": "hybrid",
                "include_debug": True,
            },
        )
        answer = answer_response.json()
        _check(answer["evidence_ids"], "RAG answer has no evidence")
        if args.require_llm:
            _check(answer.get("generation_mode") == "llm", "answer used deterministic fallback")
        _check(
            any("workspace-api-webhook" in str(item.get("source_url", "")) for item in answer["citations"]),
            "RAG did not retrieve the capstone webhook source",
        )
        report["checks"]["rag"] = {
            "message_id": answer["message_id"],
            "trace_id": answer["trace_id"],
            "confidence": answer["confidence"],
            "evidence_count": len(answer["evidence_ids"]),
            "release_id": answer["release_id"],
            "generation_mode": answer.get("generation_mode"),
            "generation_provider": answer.get("generation_provider"),
            "generation_model": answer.get("generation_model"),
        }
        _request(
            client,
            agent_token,
            "POST",
            f"/api/v1/messages/{answer['message_id']}/feedback",
            json={"rating": 1, "reason_code": "e2e_verified", "comment": "Automated capstone verification"},
        )
        report["checks"]["feedback"] = {"status": "persisted"}

        overview = _request(client, agent_token, "GET", "/api/v1/operations/overview").json()
        date_to = date.fromisoformat(overview["data_window"]["date_to"])
        available_from = date.fromisoformat(overview["data_window"]["date_from"])
        date_from = max(available_from, date_to - timedelta(days=30))
        kpi = _request(
            client,
            agent_token,
            "POST",
            "/api/v1/analytics/kpis",
            json={
                "metrics": ["ticket_count", "sla_breach_count"],
                "dimensions": ["product_line"],
                "filters": {},
                "date_from": date_from.isoformat(),
                "date_to": date_to.isoformat(),
                "limit": 100,
            },
        ).json()
        _check(kpi["allowed"] and kpi["rows"], "governed KPI query returned no rows")
        _check("semantic_aggregation" in kpi["policy_applied"], "semantic aggregation policy missing")
        report["checks"]["kpi"] = {
            "row_count": len(kpi["rows"]),
            "audit_id": kpi["audit_id"],
            "policies": kpi["policy_applied"],
        }

        note = _request(
            client,
            agent_token,
            "POST",
            f"/api/v1/cases/{case['ticket_id']}/actions",
            json={
                "operation": "add_internal_note",
                "reason": f"Capstone E2E evidence review completed ({run_id}).",
                "evidence_ids": answer["evidence_ids"],
                "idempotency_key": f"capstone-e2e-note-{run_id}",
            },
        ).json()
        _check(note["status"] == "completed", "low-risk ticket action did not complete")
        report["checks"]["low_risk_action"] = note

        credit_response = _request(
            client,
            agent_token,
            "POST",
            f"/api/v1/cases/{case['ticket_id']}/actions",
            json={
                "operation": "grant_service_credit",
                "reason": f"Capstone E2E verifies financial HITL ({run_id}).",
                "amount_cents": 100,
                "currency": "USD",
                "evidence_ids": answer["evidence_ids"],
                "idempotency_key": f"capstone-e2e-credit-{run_id}",
            },
        )
        credit = credit_response.json()
        _check(credit["status"] == "awaiting_approval", "financial action bypassed HITL")
        approval_response = _request(
            client,
            admin_token,
            "POST",
            f"/api/v1/approvals/{credit['approval_id']}/decision",
            json={"approved": True, "reason": "Automated E2E: evidence and one-dollar limit verified"},
        )
        approval = approval_response.json()
        _check(approval["status"] == "completed", "approved action did not resume")
        report["checks"]["hitl"] = {
            "approval_id": credit["approval_id"],
            "wait_trace_id": credit_response.headers.get("X-Trace-ID"),
            "resume_trace_id": approval_response.headers.get("X-Trace-ID"),
            "status": approval["status"],
        }

    if not args.skip_phoenix:
        report["checks"]["phoenix_rag"] = _trace_has(
            base_url=args.phoenix_url,
            project=args.phoenix_project,
            trace_id=report["checks"]["rag"]["trace_id"],
            required={"product.copilot.answer", "rag.query", "rag.retrieve.hybrid", "rag.audit.persist"},
        )
        report["checks"]["phoenix_hitl_wait"] = _trace_has(
            base_url=args.phoenix_url,
            project=args.phoenix_project,
            trace_id=report["checks"]["hitl"]["wait_trace_id"],
            required={"hitl.evaluate", "hitl.wait", "agent.lineage.persist"},
        )
        report["checks"]["phoenix_hitl_resume"] = _trace_has(
            base_url=args.phoenix_url,
            project=args.phoenix_project,
            trace_id=report["checks"]["hitl"]["resume_trace_id"],
            required={"hitl.resume", "tool.execute.ticket_update", "agent.lineage.persist"},
        )

    report["status"] = "pass"
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the enterprise capstone product E2E")
    parser.add_argument("--base-url", default="http://copilot_api:8002")
    parser.add_argument("--phoenix-url", default="http://phoenix:6006")
    parser.add_argument("--phoenix-project", default="omnisupport-copilot")
    parser.add_argument("--agent-email", default="agent@northstar.demo")
    parser.add_argument("--agent-password", default="Agent@2026")
    parser.add_argument("--admin-email", default="admin@northstar.demo")
    parser.add_argument("--admin-password", default="Admin@2026")
    parser.add_argument("--output", default="reports/capstone/e2e-verification.json")
    parser.add_argument("--skip-phoenix", action="store_true")
    parser.add_argument(
        "--require-llm",
        action="store_true",
        help="Fail unless the product answer was generated by a configured LLM provider",
    )
    args = parser.parse_args()
    try:
        report = run(args)
    except Exception as exc:
        report = {"status": "fail", "error": str(exc), "error_type": type(exc).__name__}
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
