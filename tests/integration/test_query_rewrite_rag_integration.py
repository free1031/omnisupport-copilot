# ruff: noqa: E402 - service path is installed before app imports

import asyncio
import json
import sys
from pathlib import Path

import pytest
from starlette.requests import Request

pytest.importorskip("asyncpg")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "rag_api"))

from app.internal_auth import InternalPrincipal
from app.models.rag_models import RagAnswerRequest
from app.query_rewrite import QueryRewriteResult
from app.routers import rag

from services.graph.models import RouteDecision


class FakeAcquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *_args):
        return False


class FakePool:
    def __init__(self):
        self.conn = object()

    def acquire(self):
        return FakeAcquire(self.conn)


class FakeRewriteService:
    def __init__(self, result):
        self.result = result

    async def rewrite(self, query, *, tenant_id):
        assert query == "How do I recover EG-3000?"
        assert tenant_id == "tenant-a"
        return self.result


def test_rag_answer_uses_rewrite_for_retrieval_but_original_for_audit(monkeypatch):
    observed = {}
    result = QueryRewriteResult(
        normalized_query="How do I recover EG-3000?",
        semantic_query="Edge Gateway recovery procedure EG-3000",
        lexical_query="How do I recover EG-3000 Edge Gateway recovery procedure EG-3000",
        lexical_terms=("EG-3000",),
        hyde_document=None,
        mode="llm",
        provider="ollama",
        model="qwen3:4b",
        prompt_release_id="query-rewrite-v1",
        rewrite_reasons=("intent_clarified",),
        fallback_reason=None,
        latency_ms=8.0,
        attempts=1,
    )

    async def fake_get_pool():
        return FakePool()

    async def fake_hybrid_retrieve(**kwargs):
        observed["retrieval"] = kwargs
        return []

    async def fake_audit(**kwargs):
        observed["audit"] = kwargs
        return True

    def fake_classify(question, *, threshold):
        observed["route_question"] = question
        observed["route_threshold"] = threshold
        return RouteDecision("hybrid", 0.9, ("test_original_intent",))

    monkeypatch.setattr(rag, "query_rewrite_service", FakeRewriteService(result))
    monkeypatch.setattr(rag, "_get_pool", fake_get_pool)
    monkeypatch.setattr("app.retrieval.hybrid_retrieve", fake_hybrid_retrieve)
    monkeypatch.setattr(rag, "write_rag_audit_log", fake_audit)
    monkeypatch.setattr(rag, "classify_query", fake_classify)

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/rag/answer",
            "headers": [],
            "query_string": b"",
            "server": ("test", 80),
            "client": ("test", 1234),
        }
    )
    request.state.request_id = "request-1"
    response = asyncio.run(
        rag.rag_answer(
            RagAnswerRequest(
                question="How do I recover EG-3000?",
                retrieval_mode="auto",
                include_debug=True,
            ),
            request,
            InternalPrincipal("actor-a", "support_agent", "tenant-a"),
        )
    )

    retrieval_call = observed["retrieval"]
    assert retrieval_call["query"] == "How do I recover EG-3000?"
    assert retrieval_call["semantic_query"] == "Edge Gateway recovery procedure EG-3000"
    assert retrieval_call["lexical_query"].startswith("How do I recover EG-3000")
    assert retrieval_call["rerank_query"] == "How do I recover EG-3000?"
    assert observed["route_question"] == "How do I recover EG-3000?"
    assert observed["audit"]["question"] == "How do I recover EG-3000?"
    assert "How do I recover" not in json.dumps(observed["audit"]["query_rewrite"])
    assert response.query_rewrite_debug is not None
    assert response.query_rewrite_debug.provider == "ollama"
    assert response.query_rewrite_debug.mode == "llm"
    assert response.abstain_reason == "no_retrieval_results"
