"""Local, global, multi-hop, and DRIFT-style graph retrieval."""

from __future__ import annotations

from services.graph.classifier import classify_query
from services.graph.models import GraphRetrievalResult, RetrievalMode, RouteDecision
from services.graph.serialize import serialize_graph_context
from services.graph.store import GraphStore


class GraphRetriever:
    def __init__(self, store: GraphStore):
        self.store = store

    async def retrieve(
        self,
        question: str,
        *,
        mode: RetrievalMode,
        graph_release_id: str,
        product_line: str | None = None,
        visibility_scope: str | None = None,
        max_hops: int = 2,
        top_k: int = 5,
        route_decision: RouteDecision | None = None,
    ) -> GraphRetrievalResult:
        release_status = await self.store.get_release_status(graph_release_id)
        if release_status != "active":
            raise ValueError(
                f"graph release {graph_release_id!r} is not active: "
                f"{release_status or 'not_found'}"
            )
        decision = route_decision or classify_query(question)
        selected = decision.mode if mode == "auto" else mode
        if selected == "hybrid":
            return GraphRetrievalResult(
                mode="hybrid",
                graph_release_id=graph_release_id,
                route_confidence=decision.confidence,
                route_reasons=decision.reasons,
                warnings=["classifier_selected_hybrid"],
            )
        if selected not in {"graph_local", "graph_global", "graph_multihop", "graph_drift"}:
            raise ValueError(f"unsupported graph retrieval mode: {selected}")

        paths = []
        communities = []
        if selected in {"graph_local", "graph_multihop", "graph_drift"}:
            seeds = await self.store.find_entities(
                question,
                graph_release_id=graph_release_id,
                product_line=product_line,
                visibility_scope=visibility_scope,
                limit=max(top_k, 3),
            )
            hop_limit = 1 if selected == "graph_local" else min(max(max_hops, 1), 3)
            paths = await self.store.traverse(
                [item.entity_id for item in seeds],
                graph_release_id=graph_release_id,
                product_line=product_line,
                visibility_scope=visibility_scope,
                max_hops=hop_limit,
                limit=top_k * 2,
            )
        if selected in {"graph_global", "graph_drift"}:
            communities = await self.store.find_communities(
                question,
                graph_release_id=graph_release_id,
                product_line=product_line,
                visibility_scope=visibility_scope,
                limit=top_k,
            )

        evidence_ids = sorted(
            {evidence_id for path in paths for evidence_id in path.evidence_ids}
            | {evidence_id for community in communities for evidence_id in community.evidence_ids}
        )
        chunks = await self.store.load_evidence(
            evidence_ids,
            graph_release_id=graph_release_id,
            product_line=product_line,
            visibility_scope=visibility_scope,
            limit=top_k,
        )
        warnings = []
        if not paths and selected != "graph_global":
            warnings.append("no_graph_paths")
        if not chunks:
            warnings.append("no_graph_evidence")
        return GraphRetrievalResult(
            mode=selected,
            graph_release_id=graph_release_id,
            route_confidence=decision.confidence,
            route_reasons=decision.reasons,
            paths=paths,
            communities=communities,
            chunks=chunks,
            serialized_context=serialize_graph_context(paths, communities),
            warnings=warnings,
        )
