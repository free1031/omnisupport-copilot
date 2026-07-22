# ruff: noqa: E402 - RAG service path is installed before app imports

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "services" / "rag_api"))

from app.retrieval import RetrievalResult, _build_fts_query, reciprocal_rank_fusion


def result(chunk_id: str, vector_score: float = 0.0, fts_score: float = 0.0) -> RetrievalResult:
    return RetrievalResult(
        chunk_id=chunk_id,
        evidence_id=f"ev-{chunk_id}",
        doc_id="doc-1",
        source_id="source-1",
        content=f"content for {chunk_id}",
        section_path="Guide > Recovery",
        page_no=1,
        title="Guide",
        bbox=None,
        source_url="s3://omni-raw-documents/guide.pdf",
        doc_version="2026.04",
        section_type="text",
        data_release_id="data-week08-dev",
        index_release_id="index-week08-dev",
        vector_score=vector_score,
        fts_score=fts_score,
    )


def test_rrf_merges_same_chunk_and_preserves_scores():
    merged = reciprocal_rank_fusion(
        vector_results=[result("a", vector_score=0.9), result("b", vector_score=0.8)],
        fts_results=[result("a", fts_score=0.4), result("c", fts_score=0.3)],
    )

    by_id = {item.chunk_id: item for item in merged}
    assert set(by_id) == {"a", "b", "c"}
    assert by_id["a"].vector_score == 0.9
    assert by_id["a"].fts_score == 0.4
    assert by_id["a"].rrf_score > by_id["b"].rrf_score
    assert by_id["a"].debug_scores()["final_score"] == by_id["a"].rrf_score


def test_fts_query_preserves_business_terms_and_removes_question_noise():
    query = _build_fts_query("What must happen before rotating a Workspace webhook signing secret?")

    assert query == "happen OR rotating OR workspace OR webhook OR signing OR secret"
