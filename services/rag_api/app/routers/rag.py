"""Week8 contract-first RAG endpoint."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Request

from app.audit import Timer, write_rag_audit_log
from app.config import settings
from app.generator import generate_grounded_answer
from app.models.rag_models import (
    Citation,
    RagAnswerRequest,
    RagAnswerResponse,
    RetrievalContext,
    RetrievalDebugItem,
    RetrievalDebugPayload,
)
from app.routers.query import _get_pool
from observability.runtime import current_trace_id, hash_text, safe_preview, traced_span

router = APIRouter(tags=["week08-rag"])


@router.post("/rag/answer", response_model=RagAnswerResponse, summary="Week8 RAG answer")
async def rag_answer(payload: RagAnswerRequest, http_request: Request) -> RagAnswerResponse:
    timer = Timer()
    request_id = getattr(http_request.state, "request_id", str(uuid.uuid4()))
    trace_id = current_trace_id() or request_id
    index_release_id = payload.index_release_id or settings.index_release_id
    data_release_id = payload.data_release_id or settings.data_release_id
    prompt_release_id = payload.prompt_release_id or settings.prompt_release_id
    filters = {
        "product_line": payload.product_line,
        "visibility_scope": payload.visibility_scope,
        "entitlement_tier": payload.entitlement_tier,
        "status": payload.status,
        "quality_status": payload.quality_status,
        "data_release_id": data_release_id,
        "index_release_id": index_release_id,
    }

    root_attributes = {
        "omni.request_id": request_id,
        "omni.query.sha256": hash_text(payload.question),
        "omni.query.length": len(payload.question),
        "omni.actor.role": payload.actor_role or "anonymous",
        "omni.product_line": payload.product_line or "any",
        "omni.release_id": settings.release_id,
        "omni.data_release_id": data_release_id,
        "omni.index_release_id": index_release_id,
        "omni.prompt_release_id": prompt_release_id,
    }
    if settings.otel_capture_content:
        root_attributes["input.value"] = safe_preview(payload.question)

    with traced_span("rag.query", kind="CHAIN", attributes=root_attributes) as root_span:
        trace_id = current_trace_id() or trace_id
        with traced_span(
            "rag.intent.route",
            kind="CHAIN",
            attributes={"omni.route": "knowledge_rag", "omni.route.reason": "rag_answer"},
        ):
            pass

        raw_chunks = []
        pool = None
        with traced_span(
            "rag.retrieve.hybrid",
            kind="RETRIEVER",
            attributes={
                "omni.retrieval.strategy": "pgvector+postgres_fts+rrf",
                "omni.retrieval.top_k": payload.top_k,
                "omni.rerank.enabled": settings.rerank_enabled,
            },
        ) as retrieval_span:
            try:
                pool = await _get_pool()
                async with pool.acquire() as conn:
                    from app.retrieval import hybrid_retrieve

                    raw_chunks = await hybrid_retrieve(
                        conn=conn,
                        query=payload.question,
                        top_k=payload.top_k,
                        product_line=payload.product_line,
                        index_release_id=index_release_id,
                        data_release_id=data_release_id,
                        visibility_scope=payload.visibility_scope,
                        entitlement_tier=payload.entitlement_tier,
                        status=payload.status,
                        quality_status=payload.quality_status,
                        rerank=settings.rerank_enabled,
                    )
            except Exception as exc:
                retrieval_span.set_attribute("omni.business_status", "retrieval_degraded")
                retrieval_span.set_attribute("error.type", type(exc).__name__)
                raw_chunks = []
            retrieval_span.set_attribute("omni.retrieval.result_count", len(raw_chunks))
            retrieval_span.set_attribute(
                "omni.retrieval.top_chunk_ids", [chunk.chunk_id for chunk in raw_chunks[:3]]
            )

        citations = [_citation_from_chunk(chunk) for chunk in raw_chunks]
        with traced_span(
            "llm.generate",
            kind="LLM",
            attributes={
                "llm.model_name": settings.llm_model,
                "llm.invocation_parameters": (
                    f"max_tokens={settings.llm_max_tokens},temperature={settings.llm_temperature}"
                ),
                "omni.prompt_release_id": prompt_release_id,
                "omni.evidence_count": len(citations),
            },
        ) as generation_span:
            answer, confidence, abstain_reason = await generate_grounded_answer(
                question=payload.question,
                chunks=raw_chunks,
                prompt_release_id=prompt_release_id,
            )
            generation_span.set_attribute("omni.answer.length", len(answer))
            generation_span.set_attribute("omni.answer.confidence", confidence)
            generation_span.set_attribute(
                "omni.business_status", abstain_reason or "grounded_answer"
            )
            if settings.otel_capture_content:
                generation_span.set_attribute("output.value", safe_preview(answer))
        if not raw_chunks and abstain_reason is None:
            abstain_reason = "no_retrieval_results"

        retrieved_contexts = [
            RetrievalContext(
                chunk_id=chunk.chunk_id,
                content=chunk.content,
                score=chunk.final_score,
                citation=citation,
            )
            for chunk, citation in zip(raw_chunks, citations)
        ]
        debug = _debug_payload(raw_chunks, filters) if payload.include_debug else None

        audit_persisted = False
        with traced_span(
            "rag.audit.persist",
            kind="TOOL",
            attributes={"omni.audit.store": "postgresql.rag_audit_log"},
        ) as audit_span:
            if pool is not None:
                try:
                    async with pool.acquire() as conn:
                        audit_persisted = await write_rag_audit_log(
                            conn=conn,
                            request_id=request_id,
                            trace_id=trace_id,
                            question=payload.question,
                            actor_role=payload.actor_role,
                            filters=filters,
                            retrieved_evidence_ids=[c.evidence_id for c in citations],
                            scores=[chunk.debug_scores() for chunk in raw_chunks],
                            answer=answer,
                            confidence=confidence,
                            abstain_reason=abstain_reason,
                            release_id=settings.release_id,
                            data_release_id=data_release_id,
                            index_release_id=index_release_id,
                            prompt_release_id=prompt_release_id,
                            latency_ms=timer.elapsed_ms,
                        )
                except Exception as exc:
                    audit_span.set_attribute("error.type", type(exc).__name__)
            audit_span.set_attribute("omni.audit.persisted", audit_persisted)

        root_span.set_attribute("omni.evidence_count", len(citations))
        root_span.set_attribute("omni.answer.confidence", confidence)
        root_span.set_attribute("omni.answer.abstain_reason", abstain_reason or "")
        root_span.set_attribute("omni.audit.persisted", audit_persisted)
        root_span.set_attribute("omni.latency_ms", timer.elapsed_ms)

        return RagAnswerResponse(
            answer=answer,
            citations=citations,
            evidence_ids=[c.evidence_id for c in citations],
            confidence=confidence,
            abstain_reason=abstain_reason,
            release_id=settings.release_id,
            data_release_id=data_release_id,
            index_release_id=index_release_id,
            prompt_release_id=prompt_release_id,
            trace_id=trace_id,
            retrieved_contexts=retrieved_contexts,
            retrieval_debug=debug,
        )


def _citation_from_chunk(chunk) -> Citation:
    return Citation(
        evidence_id=chunk.evidence_id,
        chunk_id=chunk.chunk_id,
        section_id=chunk.chunk_id,
        doc_id=chunk.doc_id,
        source_id=chunk.source_id,
        title=chunk.title,
        page_no=chunk.page_no,
        section_path=chunk.section_path,
        bbox=chunk.bbox,
        source_url=chunk.source_url,
        doc_version=chunk.doc_version,
        quote=chunk.content[:500],
        score=chunk.final_score,
    )


def _debug_payload(chunks, filters: dict) -> RetrievalDebugPayload:
    has_rerank = any(chunk.rerank_score is not None for chunk in chunks)
    return RetrievalDebugPayload(
        mode="hybrid_rrf_rerank" if has_rerank else "hybrid_rrf",
        rrf_k=60,
        rerank_enabled=settings.rerank_enabled,
        rerank_fallback=settings.rerank_enabled and not has_rerank,
        filters_applied={key: value for key, value in filters.items() if value is not None},
        results=[
            RetrievalDebugItem(
                chunk_id=chunk.chunk_id,
                vector_score=chunk.vector_score,
                fts_score=chunk.fts_score,
                rrf_score=chunk.rrf_score,
                rerank_score=chunk.rerank_score,
                final_score=chunk.final_score,
            )
            for chunk in chunks
        ],
    )
