import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "services", "rag_api"))

from app.audit import write_rag_audit_log


class FakeConn:
    def __init__(self):
        self.calls = []

    async def execute(self, *args):
        self.calls.append(args)


def test_week8_rag_audit_log_writes_release_and_score_fields():
    conn = FakeConn()

    asyncio.run(
        write_rag_audit_log(
            conn=conn,
            request_id="req-1",
            trace_id="trace-1",
            question="How do I recover an Edge Gateway for owner@example.com?",
            tenant_id="course-legacy",
            actor_role="support_agent",
            filters={"product_line": "edge-gateway", "index_release_id": "index-week08-dev"},
            retrieved_evidence_ids=["ev-1"],
            scores=[{"chunk_id": "chunk-1", "rrf_score": 0.03, "rerank_score": 0.91}],
            answer="Use the grounded recovery runbook; token=do-not-store.",
            confidence=0.82,
            abstain_reason=None,
            release_id="rag-api-dev",
            data_release_id="data-week08-dev",
            index_release_id="index-week08-dev",
            prompt_release_id="prompt-week08-v1",
            query_rewrite={
                "mode": "llm",
                "original_query_sha256": "sha256:abc",
                "semantic_query_sha256": "sha256:def",
            },
            latency_ms=12.5,
        )
    )

    assert len(conn.calls) == 1
    sql, *params = conn.calls[0]
    assert "INSERT INTO rag_audit_log" in sql
    assert params[11] == "rag-api-dev"
    assert params[13] == "index-week08-dev"
    assert params[14] == "prompt-week08-v1"
    assert params[3] == "course-legacy"
    assert params[2] == "How do I recover an Edge Gateway for [EMAIL]?"
    assert params[8] == "Use the grounded recovery runbook; token=[SECRET]"
    assert json.loads(params[5])["product_line"] == "edge-gateway"
    assert json.loads(params[7])[0]["rerank_score"] == 0.91
    assert json.loads(params[15])["mode"] == "llm"
    assert "owner@example.com" not in params[15]
