"""Week8 minimal RAG smoke evaluation.

This is intentionally not a Week11-style eval harness. It checks that the
Week8 RAG API returns contract-shaped responses with release ids, trace ids,
citations for answer cases, and abstain reasons for no-answer cases.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import types
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
RAG_API_ROOT = ROOT / "services" / "rag_api"
REPORT_PATH = ROOT / "reports" / "week08" / "smoke_eval_report.md"


CASES = [
    {
        "id": "known_hit_edge_gateway",
        "question": "How do I recover an Edge Gateway after firmware upgrade failure?",
        "product_line": "edge-gateway",
        "top_k": 5,
        "expected": "answer_or_structured_abstain",
    },
    {
        "id": "lexical_keyword_firmware",
        "question": "firmware rollback gateway recovery",
        "product_line": "edge-gateway",
        "top_k": 5,
        "expected": "answer_or_structured_abstain",
    },
    {
        "id": "semantic_paraphrase",
        "question": "What should support do when a device upgrade breaks connectivity?",
        "product_line": "edge-gateway",
        "top_k": 5,
        "expected": "answer_or_structured_abstain",
    },
    {
        "id": "product_line_filter",
        "question": "How do I recover an Edge Gateway after firmware upgrade failure?",
        "product_line": "billing",
        "top_k": 5,
        "expected": "answer_or_structured_abstain",
    },
    {
        "id": "no_answer",
        "question": "What is the private roadmap for an unreleased satellite product?",
        "product_line": "edge-gateway",
        "top_k": 5,
        "expected": "structured_abstain",
    },
    {
        "id": "permission_like_filter",
        "question": "Show internal-only recovery runbooks.",
        "product_line": "edge-gateway",
        "visibility_scope": "public",
        "top_k": 5,
        "expected": "answer_or_structured_abstain",
    },
]


def _install_asyncpg_stub() -> None:
    if "asyncpg" in sys.modules:
        return
    asyncpg_stub = types.ModuleType("asyncpg")

    class Pool:
        pass

    async def create_pool(*_args, **_kwargs):
        raise RuntimeError("asyncpg is not installed in the local smoke env")

    asyncpg_stub.Pool = Pool
    asyncpg_stub.create_pool = create_pool
    sys.modules["asyncpg"] = asyncpg_stub


def _client() -> TestClient:
    sys.path.insert(0, str(RAG_API_ROOT))
    os.environ.setdefault("OTEL_ENABLED", "false")
    _install_asyncpg_stub()
    from app.main import app

    return TestClient(app, raise_server_exceptions=False)


def _check_payload(payload: dict, expected: str) -> tuple[bool, list[str]]:
    issues: list[str] = []
    for field in ["answer", "citations", "evidence_ids", "release_id", "index_release_id", "prompt_release_id", "trace_id"]:
        if field not in payload:
            issues.append(f"missing {field}")

    abstain_reason = payload.get("abstain_reason")
    has_answer_evidence = bool(payload.get("evidence_ids")) and bool(payload.get("citations"))

    if expected == "structured_abstain" and not abstain_reason:
        issues.append("expected abstain_reason")
    if not abstain_reason and not has_answer_evidence:
        issues.append("answer case must include citations and evidence_ids")
    if payload.get("citations") and len(payload.get("evidence_ids", [])) < len(payload["citations"]):
        issues.append("citation coverage lower than citation count")

    return len(issues) == 0, issues


def run() -> int:
    client = _client()
    rows = []
    failures = 0
    started = time.time()

    for case in CASES:
        payload = {
            "question": case["question"],
            "product_line": case.get("product_line"),
            "visibility_scope": case.get("visibility_scope"),
            "top_k": case.get("top_k", 5),
            "index_release_id": "index-week08-dev",
            "prompt_release_id": "prompt-week08-v1",
            "include_debug": True,
        }
        response = client.post("/rag/answer", json={k: v for k, v in payload.items() if v is not None})
        if response.status_code != 200:
            ok = False
            issues = [f"http {response.status_code}"]
            body = {}
        else:
            body = response.json()
            ok, issues = _check_payload(body, case["expected"])

        failures += 0 if ok else 1
        rows.append(
            {
                "case_id": case["id"],
                "status": "PASS" if ok else "FAIL",
                "abstain_reason": body.get("abstain_reason") if body else None,
                "evidence_count": len(body.get("evidence_ids", [])) if body else 0,
                "issues": "; ".join(issues) if issues else "-",
            }
        )

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    elapsed = round((time.time() - started) * 1000, 2)
    lines = [
        "# Week8 Smoke Eval Report",
        "",
        "Week 8：从“搜得到”到“答得稳”——检索 × 生成的一体化工程闭环",
        "",
        f"- Generated at: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "- Runner: `evals/week08/run_smoke_eval.py`",
        f"- Elapsed: `{elapsed} ms`",
        f"- Result: `{'PASS' if failures == 0 else 'FAIL'}`",
        "",
        "| case | status | evidence_count | abstain_reason | issues |",
        "|---|---:|---:|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| `{row['case_id']}` | {row['status']} | {row['evidence_count']} | "
            f"{row['abstain_reason'] or '-'} | {row['issues']} |"
        )
    lines.extend(
        [
            "",
            "Notes:",
            "- This is a Week8 smoke eval, not a Week11 LLM-as-judge harness.",
            "- In an environment without PostgreSQL/pgvector data, answer cases may pass through structured abstain.",
            "- A production-grade run should be executed through Docker Compose after index build.",
            "",
        ]
    )
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"report": str(REPORT_PATH), "failures": failures}, ensure_ascii=False))
    return 1 if failures else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.parse_args()
    raise SystemExit(run())
