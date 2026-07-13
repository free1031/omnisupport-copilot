"""Verify that a distributed trace and its required spans reached Phoenix."""

from __future__ import annotations

import argparse
import json
import time
from urllib.parse import quote

import httpx


def resolve_project_identifier(base_url: str, project: str) -> str | None:
    response = httpx.get(f"{base_url.rstrip('/')}/v1/projects", params={"limit": 100}, timeout=10.0)
    response.raise_for_status()
    for item in response.json().get("data", []):
        if item.get("name") == project or item.get("id") == project:
            return str(item["id"])
    return None


def fetch_trace(base_url: str, project: str, trace_id: str) -> dict | None:
    identifier = resolve_project_identifier(base_url, project)
    if identifier is None:
        return None
    url = f"{base_url.rstrip('/')}/v1/projects/{quote(identifier, safe='')}/traces"
    response = httpx.get(
        url,
        params={"limit": 100, "include_spans": "true", "sort": "start_time", "order": "desc"},
        timeout=10.0,
    )
    if response.status_code == 404:
        return None
    response.raise_for_status()
    for trace in response.json().get("data", []):
        if trace.get("trace_id") == trace_id:
            return trace
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify Week12 spans in Phoenix")
    parser.add_argument("--base-url", default="http://phoenix:6006")
    parser.add_argument("--project", default="omnisupport-copilot")
    parser.add_argument("--trace-id", required=True)
    parser.add_argument(
        "--required-spans",
        default=(
            "omni.demo.flow,client.rag_api,rag.query,rag.intent.route,"
            "rag.retrieve.hybrid,rag.rerank.cross,llm.generate,rag.audit.persist,"
            "client.tool_api,tool.execute.get_ticket_status,agent.invoke,"
            "hitl.evaluate,hitl.wait,hitl.resume,tool.idempotency.check,"
            "tool.execute.ticket_update,agent.lineage.persist"
        ),
    )
    parser.add_argument("--retries", type=int, default=20)
    parser.add_argument("--delay", type=float, default=1.0)
    args = parser.parse_args(argv)
    required = {name.strip() for name in args.required_spans.split(",") if name.strip()}
    trace = None
    names: set[str] = set()
    for _ in range(args.retries):
        trace = fetch_trace(args.base_url, args.project, args.trace_id)
        names = {span["name"] for span in trace.get("spans", [])} if trace else set()
        if trace and required.issubset(names):
            break
        time.sleep(args.delay)
    if trace is None:
        print(json.dumps({"status": "fail", "reason": "trace_not_found", "trace_id": args.trace_id}))
        return 1

    missing = sorted(required - names)
    result = {
        "status": "pass" if not missing else "fail",
        "trace_id": args.trace_id,
        "span_count": len(names),
        "required_span_count": len(required),
        "missing_spans": missing,
        "observed_spans": sorted(names),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not missing else 1


if __name__ == "__main__":
    raise SystemExit(main())
