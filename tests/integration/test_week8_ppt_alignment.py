import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "services" / "rag_api"))
os.environ.setdefault("OTEL_ENABLED", "false")


def _prefer_rag_api_app_package():
    for module_name in list(sys.modules):
        if module_name == "app" or module_name.startswith("app."):
            sys.modules.pop(module_name, None)
    rag_api_path = str(PROJECT_ROOT / "services" / "rag_api")
    if rag_api_path in sys.path:
        sys.path.remove(rag_api_path)
    sys.path.insert(0, rag_api_path)


def test_ppt_hybrid_path_reuses_service_rrf():
    _prefer_rag_api_app_package()
    from pipelines.retrieve.hybrid import RetrievalResult, reciprocal_rank_fusion

    def result(chunk_id: str) -> RetrievalResult:
        return RetrievalResult(
            chunk_id=chunk_id,
            evidence_id=f"ev-{chunk_id}",
            doc_id="doc-1",
            source_id="source-1",
            content="firmware rollback recovery",
            section_path="Guide > Recovery",
            page_no=1,
            title="Guide",
            bbox=None,
            source_url=None,
            doc_version="2026.04",
            section_type="text",
        )

    merged = reciprocal_rank_fusion([result("a"), result("b")], [result("b"), result("c")])

    assert [item.chunk_id for item in merged][:2] == ["b", "a"]
    assert merged[0].rrf_score > 0


def test_query_rewrite_preserves_error_codes_and_hyde_plan():
    from pipelines.query.rewriter import build_hyde_document, rewrite_query
    from pipelines.query.router import route_query

    query = "How do I recover EG-3000 after EG-BOOT-004 firmware upgrade failure?"
    plan = rewrite_query(query)
    hyde = build_hyde_document(query)
    route = route_query(query)

    assert "EG-BOOT-004" in plan.lexical_terms
    assert "EG-3000" in plan.lexical_terms
    assert "preserve_lexical_identifiers" in plan.rewrite_reasons
    assert hyde.hyde_document
    assert route.mode == "hybrid_lexical_guard"


def test_context_pruning_keeps_top_chunks_with_budget():
    _prefer_rag_api_app_package()
    from app.context_pruning import prune_contexts

    class Chunk:
        def __init__(self, chunk_id: str, content: str):
            self.chunk_id = chunk_id
            self.content = content

    chunks = [
        Chunk("c1", "short evidence"),
        Chunk("c2", "x" * 200),
        Chunk("c3", "y" * 200),
    ]

    pruned = prune_contexts(chunks, max_chunks=3, token_budget=60)

    assert [chunk.chunk_id for chunk in pruned.chunks] == ["c1", "c2"]
    assert pruned.dropped_chunk_ids == ["c3"]
    assert pruned.strategy == "top_k_token_budget"


def test_prompt_rendering_uses_file_backed_templates():
    _prefer_rag_api_app_package()
    from app.generator import render_evidence_prompt

    class Chunk:
        section_path = "Guide > Recovery"
        page_no = 3
        source_url = "s3://omni/raw/guide.pdf"
        content = "Use the recovery runbook and cite evidence."

    system_prompt, user_prompt = render_evidence_prompt("How do I recover?", [Chunk()])

    assert "retrieved evidence" in system_prompt.lower()
    assert "Retrieved evidence" in user_prompt
    assert "Guide > Recovery" in user_prompt
