"""Week8 contract-first RAG endpoint."""

from __future__ import annotations

import uuid
from typing import Any, Literal, cast

from fastapi import APIRouter, Depends, Request

from app.audit import Timer, write_rag_audit_log
from app.config import settings
from app.context_pruning import prune_contexts
from app.generator import generate_grounded_answer
from app.internal_auth import InternalPrincipal, require_internal_request
from app.llm import resolve_llm_runtime
from app.models.rag_models import (
    Citation,
    GraphRetrievalDebug,
    QueryRewriteDebug,
    RagAnswerRequest,
    RagAnswerResponse,
    RetrievalContext,
    RetrievalDebugItem,
    RetrievalDebugPayload,
)
from app.query_rewrite import query_rewrite_service
from app.routers.query import _get_pool
from observability.runtime import current_trace_id, hash_text, safe_preview, traced_span
from services.graph.classifier import classify_query
from services.graph.models import RouteDecision
from services.graph.retrieval import GraphRetriever
from services.graph.serialize import serialize_graph_context
from services.graph.store import AsyncPostgresGraphStore

router = APIRouter(tags=["week08-rag"])


@router.post("/rag/answer", response_model=RagAnswerResponse, summary="Week8 RAG answer")
async def rag_answer(
    payload: RagAnswerRequest,
    http_request: Request,
    principal: InternalPrincipal = Depends(require_internal_request),
) -> RagAnswerResponse:
    timer = Timer()
    request_id = getattr(http_request.state, "request_id", str(uuid.uuid4()))
    trace_id = current_trace_id() or request_id
    index_release_id = payload.index_release_id or settings.index_release_id
    data_release_id = payload.data_release_id or settings.data_release_id
    prompt_release_id = payload.prompt_release_id or settings.prompt_release_id
    graph_release_id = payload.graph_release_id or settings.graph_release_id
    graph_visibility_scope = (
        payload.visibility_scope or settings.graph_default_visibility_scope
    )
    requested_mode = payload.retrieval_mode
    tenant_id = principal.tenant_id or payload.tenant_id or "course-legacy"
    actor_role = principal.actor_role or payload.actor_role
    graph_result = None
    graph_fallback_reason = None
    filters = {
        "product_line": payload.product_line,
        "visibility_scope": payload.visibility_scope,
        "entitlement_tier": payload.entitlement_tier,
        "status": payload.status,
        "quality_status": payload.quality_status,
        "data_release_id": data_release_id,
        "index_release_id": index_release_id,
        "graph_release_id": graph_release_id,
        "retrieval_mode": requested_mode,
        "graph_visibility_scope": graph_visibility_scope,
        "tenant_id": tenant_id,
        "query_rewrite_prompt_release_id": settings.query_rewrite_prompt_release_id,
    }

    root_attributes = {
        "omni.request_id": request_id,
        "omni.query.sha256": hash_text(payload.question),
        "omni.query.length": len(payload.question),
        "omni.actor.role": actor_role or "anonymous",
        "omni.tenant_id": tenant_id,
        "omni.product_line": payload.product_line or "any",
        "omni.release_id": settings.release_id,
        "omni.data_release_id": data_release_id,
        "omni.index_release_id": index_release_id,
        "omni.prompt_release_id": prompt_release_id,
        "omni.graph_release_id": graph_release_id,
        "omni.retrieval.requested_mode": requested_mode,
    }
    if settings.otel_capture_content:
        root_attributes["input.value"] = safe_preview(payload.question)

    with traced_span("rag.query", kind="CHAIN", attributes=root_attributes) as root_span:
        trace_id = current_trace_id() or trace_id
        with traced_span(
            "rag.query.rewrite",
            kind="CHAIN",
            attributes={
                "omni.query_rewrite.strategy": settings.query_rewrite_strategy,
                "omni.query_rewrite.prompt_release_id": (
                    settings.query_rewrite_prompt_release_id
                ),
            },
        ) as rewrite_span:
            rewrite = await query_rewrite_service.rewrite(
                payload.question,
                tenant_id=tenant_id,
            )
            rewrite_metadata = rewrite.audit_metadata(payload.question)
            rewrite_span.set_attribute("omni.query_rewrite.mode", rewrite.mode)
            rewrite_span.set_attribute("omni.query_rewrite.provider", rewrite.provider)
            rewrite_span.set_attribute("omni.query_rewrite.model", rewrite.model)
            rewrite_span.set_attribute(
                "omni.query_rewrite.reasons", list(rewrite.rewrite_reasons)
            )
            rewrite_span.set_attribute(
                "omni.query_rewrite.fallback_reason", rewrite.fallback_reason or ""
            )
            rewrite_span.set_attribute(
                "omni.query_rewrite.semantic_sha256", hash_text(rewrite.semantic_query)
            )
            rewrite_span.set_attribute(
                "omni.query_rewrite.semantic_length", len(rewrite.semantic_query)
            )
            rewrite_span.set_attribute(
                "omni.query_rewrite.lexical_term_count", len(rewrite.lexical_terms)
            )
            rewrite_span.set_attribute(
                "omni.query_rewrite.hyde_used", bool(rewrite.hyde_document)
            )
            rewrite_span.set_attribute("omni.query_rewrite.attempts", rewrite.attempts)
            rewrite_span.set_attribute(
                "omni.query_rewrite.safety_repair_count",
                len(rewrite.safety_repairs),
            )
            rewrite_span.set_attribute("omni.query_rewrite.cache_hit", rewrite.cache_hit)
            rewrite_span.set_attribute("omni.query_rewrite.coalesced", rewrite.coalesced)
            rewrite_span.set_attribute(
                "omni.query_rewrite.circuit_state", rewrite.circuit_state
            )
            rewrite_span.set_attribute(
                "omni.query_rewrite.latency_ms", rewrite.latency_ms
            )

        route_decision = (
            classify_query(
                # Routing follows the user's intent, not retrieval-only terms
                # added by query rewrite (for example "root cause").
                payload.question,
                threshold=settings.graph_classifier_threshold,
            )
            if requested_mode == "auto"
            else RouteDecision(requested_mode, 1.0, ("explicit_request_mode",))
        )
        selected_mode = route_decision.mode
        effective_mode = selected_mode
        llm_runtime = resolve_llm_runtime()
        with traced_span(
            "rag.intent.route",
            kind="CHAIN",
            attributes={
                "omni.route": selected_mode,
                "omni.route.reason": ",".join(route_decision.reasons),
                "omni.route.confidence": route_decision.confidence,
            },
        ):
            pass

        raw_chunks: list[Any] = []
        pool = None
        with traced_span(
            "rag.retrieve.route",
            kind="RETRIEVER",
            attributes={
                "omni.retrieval.strategy": selected_mode,
                "omni.retrieval.top_k": payload.top_k,
                "omni.rerank.enabled": settings.rerank_enabled,
            },
        ) as retrieval_span:
            try:
                pool = await _get_pool()
                async with pool.acquire() as conn:
                    if selected_mode.startswith("graph_"):
                        with traced_span(
                            "rag.retrieve.graph",
                            kind="RETRIEVER",
                            attributes={
                                "omni.graph.mode": selected_mode,
                                "omni.graph.release_id": graph_release_id,
                                "omni.graph.max_hops": min(
                                    payload.max_graph_hops, settings.graph_max_hops
                                ),
                            },
                        ) as graph_span:
                            try:
                                graph_result = await GraphRetriever(
                                    AsyncPostgresGraphStore(conn)
                                ).retrieve(
                                    rewrite.semantic_query,
                                    mode=selected_mode,
                                    graph_release_id=graph_release_id,
                                    product_line=payload.product_line,
                                    visibility_scope=graph_visibility_scope,
                                    max_hops=min(payload.max_graph_hops, settings.graph_max_hops),
                                    top_k=payload.top_k,
                                    route_decision=route_decision,
                                )
                                raw_chunks = graph_result.chunks
                                graph_span.set_attribute("omni.graph.path_count", len(graph_result.paths))
                                graph_span.set_attribute(
                                    "omni.graph.community_count", len(graph_result.communities)
                                )
                                graph_span.set_attribute(
                                    "omni.graph.evidence_count", len(graph_result.chunks)
                                )
                                if not raw_chunks:
                                    graph_fallback_reason = "graph_returned_no_evidence"
                            except Exception as graph_exc:
                                graph_fallback_reason = f"graph_runtime_error:{type(graph_exc).__name__}"
                                graph_span.set_attribute("error.type", type(graph_exc).__name__)
                                raw_chunks = []

                    if not selected_mode.startswith("graph_") or not raw_chunks:
                        from app.retrieval import hybrid_retrieve

                        with traced_span(
                            "rag.retrieve.hybrid",
                            kind="RETRIEVER",
                            attributes={
                                "omni.retrieval.strategy": "pgvector+postgres_fts+rrf",
                                "omni.retrieval.fallback_from": (
                                    selected_mode if selected_mode.startswith("graph_") else ""
                                ),
                            },
                        ):
                            raw_chunks = await hybrid_retrieve(
                                conn=conn,
                                query=payload.question,
                                semantic_query=rewrite.vector_query,
                                lexical_query=rewrite.lexical_query,
                                rerank_query=payload.question,
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
                        effective_mode = "hybrid"
            except Exception as exc:
                retrieval_span.set_attribute("omni.business_status", "retrieval_degraded")
                retrieval_span.set_attribute("error.type", type(exc).__name__)
                raw_chunks = []
                if selected_mode.startswith("graph_"):
                    graph_fallback_reason = f"retrieval_runtime_error:{type(exc).__name__}"
                    effective_mode = "hybrid"
            retrieval_span.set_attribute("omni.retrieval.result_count", len(raw_chunks))
            retrieval_span.set_attribute("omni.retrieval.effective_mode", effective_mode)
            retrieval_span.set_attribute(
                "omni.retrieval.fallback_reason", graph_fallback_reason or ""
            )
            retrieval_span.set_attribute(
                "omni.retrieval.top_chunk_ids", [chunk.chunk_id for chunk in raw_chunks[:3]]
            )

        generation_chunks = prune_contexts(
            raw_chunks,
            max_chunks=5,
            token_budget=2500,
        ).chunks
        citations = [_citation_from_chunk(chunk) for chunk in generation_chunks]
        selected_evidence_ids = {chunk.evidence_id for chunk in generation_chunks}
        graph_context = None
        if graph_result is not None and effective_mode.startswith("graph_"):
            graph_context = serialize_graph_context(
                graph_result.paths,
                graph_result.communities,
                allowed_evidence_ids=selected_evidence_ids,
            )
        with traced_span(
            "llm.generate",
            kind="LLM",
            attributes={
                "llm.provider": llm_runtime.provider,
                "llm.model_name": llm_runtime.model,
                "llm.invocation_parameters": (
                    f"max_tokens={settings.llm_max_tokens},temperature={settings.llm_temperature}"
                ),
                "omni.prompt_release_id": prompt_release_id,
                "omni.evidence_count": len(citations),
            },
        ) as generation_span:
            answer, confidence, abstain_reason, generation = await generate_grounded_answer(
                question=payload.question,
                chunks=generation_chunks,
                prompt_release_id=prompt_release_id,
                graph_context=graph_context,
                retrieval_mode=effective_mode,
            )
            generation_span.set_attribute("omni.answer.length", len(answer))
            generation_span.set_attribute("omni.generation.mode", generation["mode"])
            generation_span.set_attribute("llm.provider", generation["provider"])
            generation_span.set_attribute("llm.model_name", generation["model"])
            if generation.get("input_tokens") is not None:
                generation_span.set_attribute("llm.token_count.prompt", generation["input_tokens"])
            if generation.get("output_tokens") is not None:
                generation_span.set_attribute(
                    "llm.token_count.completion", generation["output_tokens"]
                )
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
            for chunk, citation in zip(generation_chunks, citations)
        ]
        debug = (
            _debug_payload(raw_chunks, filters, mode=effective_mode)
            if payload.include_debug
            else None
        )
        query_rewrite_debug = (
            QueryRewriteDebug.model_validate(rewrite_metadata)
            if payload.include_debug
            else None
        )
        graph_debug = None
        if payload.include_debug and requested_mode != "hybrid":
            graph_debug = GraphRetrievalDebug(
                requested_mode=requested_mode,
                selected_mode=effective_mode,
                graph_release_id=graph_release_id,
                route_confidence=route_decision.confidence,
                route_reasons=list(route_decision.reasons),
                paths=[item.to_dict() for item in graph_result.paths] if graph_result else [],
                communities=[item.to_dict() for item in graph_result.communities] if graph_result else [],
                warnings=list(graph_result.warnings) if graph_result else [],
                fallback_reason=graph_fallback_reason,
            )

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
                            tenant_id=tenant_id,
                            actor_role=actor_role,
                            filters=filters,
                            retrieved_evidence_ids=[c.evidence_id for c in citations],
                            scores=[chunk.debug_scores() for chunk in generation_chunks],
                            answer=answer,
                            confidence=confidence,
                            abstain_reason=abstain_reason,
                            release_id=settings.release_id,
                            data_release_id=data_release_id,
                            index_release_id=index_release_id,
                            prompt_release_id=prompt_release_id,
                            query_rewrite=rewrite_metadata,
                            latency_ms=timer.elapsed_ms,
                        )
                except Exception as exc:
                    audit_span.set_attribute("error.type", type(exc).__name__)
            audit_span.set_attribute("omni.audit.persisted", audit_persisted)

        root_span.set_attribute("omni.evidence_count", len(citations))
        root_span.set_attribute("omni.answer.confidence", confidence)
        root_span.set_attribute("omni.answer.abstain_reason", abstain_reason or "")
        root_span.set_attribute("omni.audit.persisted", audit_persisted)
        root_span.set_attribute("omni.query_rewrite.mode", rewrite.mode)
        root_span.set_attribute(
            "omni.query_rewrite.fallback_reason", rewrite.fallback_reason or ""
        )
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
            graph_release_id=graph_release_id if requested_mode != "hybrid" else None,
            retrieval_mode=effective_mode,
            generation_mode=cast(
                Literal["llm", "deterministic_fallback", "not_invoked"],
                generation["mode"],
            ),
            generation_provider=str(generation["provider"]),
            generation_model=str(generation["model"]),
            trace_id=trace_id,
            retrieved_contexts=retrieved_contexts,
            retrieval_debug=debug,
            graph_debug=graph_debug,
            query_rewrite_debug=query_rewrite_debug,
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


def _debug_payload(chunks, filters: dict, *, mode: str) -> RetrievalDebugPayload:
    has_rerank = any(chunk.rerank_score is not None for chunk in chunks)
    debug_mode = mode if mode.startswith("graph_") else (
        "hybrid_rrf_rerank" if has_rerank else "hybrid_rrf"
    )
    return RetrievalDebugPayload(
        mode=cast(
            Literal[
                "vector",
                "fts",
                "hybrid_rrf",
                "hybrid_rrf_rerank",
                "graph_local",
                "graph_global",
                "graph_multihop",
                "graph_drift",
            ],
            debug_mode,
        ),
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
