"""Transactional PostgreSQL persistence for a versioned graph build."""

from __future__ import annotations

import json
from typing import Iterable

from pipelines.graph.align import normalize_name
from pipelines.graph.models import GraphBuildResult, SourceChunk


def persist_graph_build(
    database_url: str,
    result: GraphBuildResult,
    chunks: Iterable[SourceChunk],
    *,
    index_release_id: str | None = None,
) -> None:
    import psycopg2
    from psycopg2.extras import execute_values

    dsn = database_url.replace("postgresql+psycopg2://", "postgresql://", 1)
    dsn = dsn.replace("postgresql+asyncpg://", "postgresql://", 1)
    chunks = list(chunks)
    build_report = result.to_dict()
    with psycopg2.connect(dsn) as conn:
        with conn.cursor() as cursor:
            # Serialize builds for the same release and keep activated releases immutable.
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (result.graph_release_id,),
            )
            cursor.execute(
                """
                SELECT schema_version, index_release_id, build_report
                FROM graph_release
                WHERE graph_release_id = %s
                FOR UPDATE
                """,
                (result.graph_release_id,),
            )
            existing = cursor.fetchone()
            if existing:
                same_release = (
                    existing[0] == result.graph_schema_version
                    and existing[1] == index_release_id
                    and existing[2] == build_report
                )
                if same_release:
                    return
                raise ValueError(
                    f"graph release {result.graph_release_id!r} already exists with different "
                    "content or upstream release; use a new graph_release_id"
                )
            cursor.execute(
                """
                INSERT INTO graph_release (
                    graph_release_id, schema_version, data_release_ids, index_release_id,
                    build_status, source_chunk_count, build_report
                ) VALUES (%s, %s, %s, %s, 'building', %s, %s::jsonb)
                ON CONFLICT (graph_release_id) DO UPDATE SET
                    schema_version = EXCLUDED.schema_version,
                    data_release_ids = EXCLUDED.data_release_ids,
                    index_release_id = EXCLUDED.index_release_id,
                    build_status = 'building',
                    source_chunk_count = EXCLUDED.source_chunk_count,
                    build_report = EXCLUDED.build_report
                """,
                (
                    result.graph_release_id,
                    result.graph_schema_version,
                    sorted(result.data_release_ids),
                    index_release_id,
                    result.source_chunk_count,
                    json.dumps(build_report, ensure_ascii=False),
                ),
            )
            for table in (
                "graph_build_quarantine",
                "graph_community_member",
                "graph_community",
                "graph_relation_edge",
                "graph_entity_alias",
                "graph_entity_node",
                "graph_evidence_projection",
            ):
                cursor.execute(f"DELETE FROM {table} WHERE graph_release_id = %s", (result.graph_release_id,))

            execute_values(
                cursor,
                """
                INSERT INTO graph_evidence_projection (
                    graph_release_id, evidence_id, chunk_id, doc_id, source_id, content,
                    section_path, data_release_id, product_line, visibility_scope
                ) VALUES %s
                """,
                [
                    (
                        result.graph_release_id,
                        chunk.evidence_id,
                        chunk.chunk_id,
                        chunk.doc_id,
                        chunk.source_id,
                        chunk.content,
                        f"Week13 source > {chunk.chunk_id}",
                        chunk.data_release_id,
                        chunk.product_line,
                        chunk.visibility_scope,
                    )
                    for chunk in chunks
                ],
            )
            execute_values(
                cursor,
                """
                INSERT INTO graph_entity_node (
                    graph_release_id, entity_id, entity_type, canonical_name, normalized_name,
                    properties, chunk_ids, evidence_ids, data_release_id, product_line,
                    visibility_scope, confidence
                ) VALUES %s
                """,
                [
                    (
                        item.graph_release_id,
                        item.entity_id,
                        item.entity_type,
                        item.canonical_name,
                        item.normalized_name,
                        json.dumps(item.properties, ensure_ascii=False),
                        sorted(item.chunk_ids),
                        sorted(item.evidence_ids),
                        item.data_release_id,
                        item.product_line,
                        item.visibility_scope,
                        item.confidence,
                    )
                    for item in result.entities
                ],
            )
            alias_rows = [
                (
                    item.graph_release_id,
                    item.entity_id,
                    alias,
                    normalize_name(alias),
                )
                for item in result.entities
                for alias in sorted(item.aliases)
            ]
            if alias_rows:
                execute_values(
                    cursor,
                    """INSERT INTO graph_entity_alias
                       (graph_release_id, entity_id, alias, normalized_alias) VALUES %s""",
                    alias_rows,
                )
            execute_values(
                cursor,
                """
                INSERT INTO graph_relation_edge (
                    graph_release_id, edge_id, relation_type, source_entity_id,
                    target_entity_id, properties, chunk_ids, evidence_ids,
                    data_release_id, confidence
                ) VALUES %s
                """,
                [
                    (
                        item.graph_release_id,
                        item.edge_id,
                        item.relation_type,
                        item.source_entity_id,
                        item.target_entity_id,
                        json.dumps(item.properties, ensure_ascii=False),
                        sorted(item.chunk_ids),
                        sorted(item.evidence_ids),
                        item.data_release_id,
                        item.confidence,
                    )
                    for item in result.edges
                ],
            )
            execute_values(
                cursor,
                """INSERT INTO graph_community (
                       graph_release_id, community_id, level, summary, member_count,
                       evidence_ids, product_lines, visibility_scopes
                     ) VALUES %s""",
                [
                    (
                        item.graph_release_id,
                        item.community_id,
                        item.level,
                        item.summary,
                        len(item.member_entity_ids),
                        list(item.evidence_ids),
                        list(item.product_lines),
                        list(item.visibility_scopes),
                    )
                    for item in result.communities
                ],
            )
            member_rows = [
                (item.graph_release_id, item.community_id, entity_id)
                for item in result.communities
                for entity_id in item.member_entity_ids
            ]
            if member_rows:
                execute_values(
                    cursor,
                    """INSERT INTO graph_community_member
                       (graph_release_id, community_id, entity_id) VALUES %s""",
                    member_rows,
                )
            quarantine_rows = [
                (
                    result.graph_release_id,
                    item.get("kind", "unknown"),
                    item.get("reason", "unspecified"),
                    json.dumps(item, ensure_ascii=False),
                )
                for item in result.quarantined + result.rejected
            ]
            if quarantine_rows:
                execute_values(
                    cursor,
                    """INSERT INTO graph_build_quarantine
                       (graph_release_id, kind, reason, payload) VALUES %s""",
                    quarantine_rows,
                )
            cursor.execute(
                """
                UPDATE graph_release SET
                    build_status = %s,
                    entity_count = %s,
                    edge_count = %s,
                    community_count = %s,
                    quarantine_count = %s,
                    activated_at = CASE WHEN %s = 'active' THEN NOW() ELSE activated_at END
                WHERE graph_release_id = %s
                """,
                (
                    "active" if result.status == "pass" else "warn",
                    len(result.entities),
                    len(result.edges),
                    len(result.communities),
                    len(result.quarantined) + len(result.rejected),
                    "active" if result.status == "pass" else "warn",
                    result.graph_release_id,
                ),
            )
