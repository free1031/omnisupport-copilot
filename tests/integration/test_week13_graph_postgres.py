import asyncio
import os
from pathlib import Path

import pytest

from pipelines.graph.build import build_graph, load_chunks
from pipelines.graph.store import persist_graph_build
from services.graph.retrieval import GraphRetriever
from services.graph.store import AsyncPostgresGraphStore

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data/week13/graph_source_chunks_v1.jsonl"
MIGRATION = ROOT / "infra/migrations/010_week13_graphrag.sql"
RELEASE = "graph-week13-integration-test"


def test_week13_real_postgres_build_and_multihop_query():
    psycopg2 = pytest.importorskip("psycopg2")
    asyncpg = pytest.importorskip("asyncpg")
    database_url = os.getenv("DATABASE_URL", "")
    if not database_url:
        pytest.skip("DATABASE_URL is required for the real PostgreSQL GraphRAG test")
    dsn = database_url.replace("postgresql+psycopg2://", "postgresql://", 1)
    dsn = dsn.replace("postgresql+asyncpg://", "postgresql://", 1)
    try:
        connection = psycopg2.connect(dsn)
    except psycopg2.OperationalError as exc:
        pytest.skip(f"PostgreSQL is not reachable: {exc}")

    chunks = load_chunks(SOURCE)
    result = build_graph(chunks, graph_release_id=RELEASE)
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(MIGRATION.read_text(encoding="utf-8"))
        persist_graph_build(dsn, result, chunks, index_release_id="index-week08-dev")
        persist_graph_build(dsn, result, chunks, index_release_id="index-week08-dev")
        with pytest.raises(ValueError, match="use a new graph_release_id"):
            persist_graph_build(dsn, result, chunks, index_release_id="index-week08-changed")

        async def query_graph():
            conn = await asyncpg.connect(dsn)
            try:
                return await GraphRetriever(AsyncPostgresGraphStore(conn)).retrieve(
                    "Northstar Workspace SSO login loop 的问题、症状和解决方案关系链",
                    mode="graph_multihop",
                    graph_release_id=RELEASE,
                    max_hops=3,
                    top_k=5,
                )
            finally:
                await conn.close()

        query_result = asyncio.run(query_graph())
        assert query_result.paths
        assert query_result.chunks
        assert all(chunk.evidence_id for chunk in query_result.chunks)
    finally:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM graph_release WHERE graph_release_id = %s", (RELEASE,))
        connection.close()
