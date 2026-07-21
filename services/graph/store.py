"""GraphStore boundary with PostgreSQL and deterministic in-memory adapters."""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Protocol

from services.graph.models import (
    GraphCommunityRecord,
    GraphEntityRecord,
    GraphEvidenceChunk,
    GraphPathRecord,
    GraphRelationRecord,
)


class GraphStore(Protocol):
    async def get_release_status(self, graph_release_id: str) -> str | None: ...

    async def find_entities(
        self,
        query: str,
        *,
        graph_release_id: str,
        product_line: str | None,
        visibility_scope: str | None,
        limit: int,
    ) -> list[GraphEntityRecord]: ...

    async def traverse(
        self,
        seed_entity_ids: list[str],
        *,
        graph_release_id: str,
        product_line: str | None,
        visibility_scope: str | None,
        max_hops: int,
        limit: int,
    ) -> list[GraphPathRecord]: ...

    async def find_communities(
        self,
        query: str,
        *,
        graph_release_id: str,
        product_line: str | None,
        visibility_scope: str | None,
        limit: int,
    ) -> list[GraphCommunityRecord]: ...

    async def load_evidence(
        self,
        evidence_ids: list[str],
        *,
        graph_release_id: str,
        product_line: str | None,
        visibility_scope: str | None,
        limit: int,
    ) -> list[GraphEvidenceChunk]: ...


class InMemoryGraphStore:
    def __init__(
        self,
        *,
        entities: list[GraphEntityRecord],
        relations: list[GraphRelationRecord],
        communities: list[GraphCommunityRecord],
        evidence: list[GraphEvidenceChunk],
        release_status: str = "active",
    ):
        self.entities = {item.entity_id: item for item in entities}
        self.relations = relations
        self.communities = communities
        self.evidence = {item.evidence_id: item for item in evidence}
        self.release_status = release_status

    async def get_release_status(self, graph_release_id: str) -> str | None:
        return self.release_status

    async def find_entities(self, query: str, **kwargs) -> list[GraphEntityRecord]:
        limit = int(kwargs["limit"])
        lowered = query.casefold()
        scoped = [
            item for item in self.entities.values()
            if (not kwargs.get("product_line") or item.product_line in {kwargs["product_line"], "any"})
            and (not kwargs.get("visibility_scope") or item.visibility_scope == kwargs["visibility_scope"])
        ]
        matches = [item for item in scoped if item.canonical_name.casefold() in lowered]
        if not matches:
            tokens = {token for token in _tokens(lowered) if len(token) > 1}
            matches = [
                item
                for item in scoped
                if tokens & set(_tokens(item.canonical_name.casefold()))
            ]
        return sorted(matches, key=lambda item: (-item.confidence, item.entity_id))[:limit]

    async def traverse(self, seed_entity_ids: list[str], **kwargs) -> list[GraphPathRecord]:
        max_hops = min(max(int(kwargs["max_hops"]), 1), 3)
        limit = int(kwargs["limit"])
        adjacency: dict[str, list[tuple[GraphRelationRecord, str]]] = defaultdict(list)
        for edge in self.relations:
            adjacency[edge.source_entity_id].append((edge, edge.target_entity_id))
            adjacency[edge.target_entity_id].append((edge, edge.source_entity_id))
        paths: list[GraphPathRecord] = []
        for seed in seed_entity_ids:
            queue = deque([(seed, (seed,), tuple())])
            while queue and len(paths) < limit:
                current, entity_path, edge_path = queue.popleft()
                if edge_path:
                    entities = tuple(self.entities[item] for item in entity_path)
                    score = sum(edge.confidence for edge in edge_path) / len(edge_path)
                    paths.append(GraphPathRecord(entities, edge_path, round(score / len(edge_path), 6)))
                if len(edge_path) >= max_hops:
                    continue
                for edge, neighbor in sorted(adjacency[current], key=lambda item: item[0].edge_id):
                    neighbor_entity = self.entities[neighbor]
                    if kwargs.get("product_line") and neighbor_entity.product_line not in {
                        kwargs["product_line"],
                        "any",
                    }:
                        continue
                    if (
                        kwargs.get("visibility_scope")
                        and neighbor_entity.visibility_scope != kwargs["visibility_scope"]
                    ):
                        continue
                    if neighbor not in entity_path:
                        queue.append((neighbor, entity_path + (neighbor,), edge_path + (edge,)))
        return paths[:limit]

    async def find_communities(self, query: str, **kwargs) -> list[GraphCommunityRecord]:
        limit = int(kwargs["limit"])
        tokens = set(_tokens(query.casefold()))
        scoped = [
            item for item in self.communities
            if (
                not kwargs.get("product_line")
                or kwargs["product_line"] in item.product_lines
                or "any" in item.product_lines
            )
            and (
                not kwargs.get("visibility_scope")
                or kwargs["visibility_scope"] in item.visibility_scopes
            )
        ]
        ranked = sorted(
            scoped,
            key=lambda item: (len(tokens & set(_tokens(item.summary.casefold()))), item.member_count),
            reverse=True,
        )
        return ranked[:limit]

    async def load_evidence(self, evidence_ids: list[str], **kwargs) -> list[GraphEvidenceChunk]:
        limit = int(kwargs["limit"])
        return [
            self.evidence[item]
            for item in evidence_ids
            if item in self.evidence
            and (
                not kwargs.get("product_line")
                or self.evidence[item].product_line in {kwargs["product_line"], "any"}
            )
            and (
                not kwargs.get("visibility_scope")
                or self.evidence[item].visibility_scope == kwargs["visibility_scope"]
            )
        ][:limit]


class AsyncPostgresGraphStore:
    def __init__(self, conn):
        self.conn = conn

    async def get_release_status(self, graph_release_id: str) -> str | None:
        return await self.conn.fetchval(
            "SELECT build_status FROM graph_release WHERE graph_release_id = $1",
            graph_release_id,
        )

    async def find_entities(self, query: str, **kwargs) -> list[GraphEntityRecord]:
        rows = await self.conn.fetch(
            """
            SELECT entity_id, entity_type, canonical_name, confidence, evidence_ids,
                   product_line, visibility_scope
            FROM graph_entity_node
            WHERE graph_release_id = $1
              AND ($2::text IS NULL OR product_line IN ($2, 'any'))
              AND ($3::text IS NULL OR visibility_scope = $3)
              AND (
                position(lower(canonical_name) in lower($4)) > 0
                OR lower(canonical_name) LIKE '%' || lower($4) || '%'
                OR EXISTS (
                  SELECT 1 FROM graph_entity_alias a
                  WHERE a.graph_release_id = graph_entity_node.graph_release_id
                    AND a.entity_id = graph_entity_node.entity_id
                    AND position(lower(a.alias) in lower($4)) > 0
                )
              )
            ORDER BY confidence DESC, canonical_name
            LIMIT $5
            """,
            kwargs["graph_release_id"],
            kwargs.get("product_line"),
            kwargs.get("visibility_scope"),
            query,
            kwargs["limit"],
        )
        return [_entity_from_row(row) for row in rows]

    async def traverse(self, seed_entity_ids: list[str], **kwargs) -> list[GraphPathRecord]:
        if not seed_entity_ids:
            return []
        rows = await self.conn.fetch(
            """
            WITH RECURSIVE walk AS (
              SELECT seed AS current_id, ARRAY[seed]::text[] AS node_path,
                     ARRAY[]::text[] AS edge_path, 0 AS depth
              FROM unnest($1::text[]) AS seed
              UNION ALL
              SELECT
                CASE WHEN e.source_entity_id = w.current_id
                     THEN e.target_entity_id ELSE e.source_entity_id END,
                w.node_path || CASE WHEN e.source_entity_id = w.current_id
                                    THEN e.target_entity_id ELSE e.source_entity_id END,
                w.edge_path || e.edge_id,
                w.depth + 1
              FROM walk w
              JOIN graph_relation_edge e
                ON e.graph_release_id = $2
               AND (e.source_entity_id = w.current_id OR e.target_entity_id = w.current_id)
              JOIN graph_entity_node n
                ON n.graph_release_id = e.graph_release_id
               AND n.entity_id = CASE WHEN e.source_entity_id = w.current_id
                                      THEN e.target_entity_id ELSE e.source_entity_id END
              WHERE w.depth < $3
                AND NOT (n.entity_id = ANY(w.node_path))
                AND ($4::text IS NULL OR n.product_line IN ($4, 'any'))
                AND ($5::text IS NULL OR n.visibility_scope = $5)
            )
            SELECT node_path, edge_path, depth
            FROM walk
            WHERE depth > 0
            ORDER BY depth, node_path
            LIMIT $6
            """,
            seed_entity_ids,
            kwargs["graph_release_id"],
            min(max(int(kwargs["max_hops"]), 1), 3),
            kwargs.get("product_line"),
            kwargs.get("visibility_scope"),
            kwargs["limit"],
        )
        entity_ids = sorted({item for row in rows for item in row["node_path"]})
        edge_ids = sorted({item for row in rows for item in row["edge_path"]})
        entity_rows = await self.conn.fetch(
            """SELECT entity_id, entity_type, canonical_name, confidence, evidence_ids,
                      product_line, visibility_scope
               FROM graph_entity_node WHERE graph_release_id = $1 AND entity_id = ANY($2::text[])""",
            kwargs["graph_release_id"], entity_ids,
        )
        edge_rows = await self.conn.fetch(
            """SELECT edge_id, relation_type, source_entity_id, target_entity_id,
                      confidence, evidence_ids
               FROM graph_relation_edge WHERE graph_release_id = $1 AND edge_id = ANY($2::text[])""",
            kwargs["graph_release_id"], edge_ids,
        )
        entities = {row["entity_id"]: _entity_from_row(row) for row in entity_rows}
        edges = {row["edge_id"]: _relation_from_row(row) for row in edge_rows}
        output = []
        for row in rows:
            path_edges = tuple(edges[item] for item in row["edge_path"] if item in edges)
            if not path_edges:
                continue
            score = sum(item.confidence for item in path_edges) / (len(path_edges) ** 2)
            output.append(
                GraphPathRecord(
                    tuple(entities[item] for item in row["node_path"] if item in entities),
                    path_edges,
                    round(score, 6),
                )
            )
        return output

    async def find_communities(self, query: str, **kwargs) -> list[GraphCommunityRecord]:
        rows = await self.conn.fetch(
            """
            SELECT community_id, summary, member_count, evidence_ids,
                   product_lines, visibility_scopes,
                   CASE WHEN lower(summary) LIKE '%' || lower($2) || '%' THEN 1.0 ELSE 0.5 END AS score
            FROM graph_community
            WHERE graph_release_id = $1
              AND ($3::text IS NULL OR $3 = ANY(product_lines) OR 'any' = ANY(product_lines))
              AND ($4::text IS NULL OR $4 = ANY(visibility_scopes))
            ORDER BY score DESC, member_count DESC, community_id
            LIMIT $5
            """,
            kwargs["graph_release_id"], query, kwargs.get("product_line"),
            kwargs.get("visibility_scope"), kwargs["limit"],
        )
        return [
            GraphCommunityRecord(
                community_id=row["community_id"],
                summary=row["summary"],
                member_count=row["member_count"],
                evidence_ids=tuple(row["evidence_ids"] or ()),
                score=float(row["score"]),
                product_lines=tuple(row["product_lines"] or ()),
                visibility_scopes=tuple(row["visibility_scopes"] or ()),
            )
            for row in rows
        ]

    async def load_evidence(self, evidence_ids: list[str], **kwargs) -> list[GraphEvidenceChunk]:
        rows = await self.conn.fetch(
            """
            SELECT chunk_id, evidence_id, doc_id, source_id, content, section_path,
                   page_no, title, bbox, source_url, doc_version,
                   product_line, visibility_scope
            FROM graph_evidence_projection
            WHERE graph_release_id = $1 AND evidence_id = ANY($2::text[])
              AND ($3::text IS NULL OR product_line IN ($3, 'any'))
              AND ($4::text IS NULL OR visibility_scope = $4)
            ORDER BY array_position($2::text[], evidence_id)
            LIMIT $5
            """,
            kwargs["graph_release_id"], evidence_ids, kwargs.get("product_line"),
            kwargs.get("visibility_scope"), kwargs["limit"],
        )
        return [GraphEvidenceChunk(**dict(row), final_score=0.85) for row in rows]


def _entity_from_row(row) -> GraphEntityRecord:
    return GraphEntityRecord(
        entity_id=row["entity_id"],
        entity_type=row["entity_type"],
        canonical_name=row["canonical_name"],
        confidence=float(row["confidence"]),
        evidence_ids=tuple(row["evidence_ids"] or ()),
        product_line=row["product_line"],
        visibility_scope=row["visibility_scope"],
    )


def _relation_from_row(row) -> GraphRelationRecord:
    return GraphRelationRecord(
        edge_id=row["edge_id"],
        relation_type=row["relation_type"],
        source_entity_id=row["source_entity_id"],
        target_entity_id=row["target_entity_id"],
        confidence=float(row["confidence"]),
        evidence_ids=tuple(row["evidence_ids"] or ()),
    )


def _tokens(value: str) -> list[str]:
    import re

    latin = re.findall(r"[a-z0-9_]+", value)
    cjk = re.findall(r"[\u4e00-\u9fff]{2,}", value)
    return latin + cjk
