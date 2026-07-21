import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/rag_api"))
sys.path.insert(0, str(ROOT))
os.environ.setdefault("OTEL_ENABLED", "false")

from app.main import app  # noqa: E402

from pipelines.graph.build import build_graph, load_chunks  # noqa: E402
from pipelines.graph.store import persist_graph_build  # noqa: E402

SOURCE = ROOT / "data/week13/graph_source_chunks_v1.jsonl"
MIGRATION = ROOT / "infra/migrations/010_week13_graphrag.sql"
RELEASE = "graph-week13-api-integration"


def test_week13_rag_endpoint_returns_real_graph_paths_and_citations():
    psycopg2 = pytest.importorskip("psycopg2")
    database_url = os.getenv("DATABASE_URL", "")
    if not database_url:
        pytest.skip("DATABASE_URL is required for the real GraphRAG API test")
    dsn = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    dsn = dsn.replace("postgresql+psycopg2://", "postgresql://", 1)
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

        with TestClient(app, raise_server_exceptions=True) as client:
            response = client.post(
                "/rag/answer",
                json={
                    "question": "Northstar Workspace SSO login loop 的问题、症状和解决方案关系链",
                    "retrieval_mode": "graph_multihop",
                    "graph_release_id": RELEASE,
                    "max_graph_hops": 3,
                    "include_debug": True,
                },
            )

        assert response.status_code == 200
        payload = response.json()
        assert payload["retrieval_mode"] == "graph_multihop"
        assert payload["graph_release_id"] == RELEASE
        assert payload["citations"]
        assert payload["evidence_ids"]
        assert payload["graph_debug"]["paths"]
        assert payload["graph_debug"]["fallback_reason"] is None
    finally:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM graph_release WHERE graph_release_id = %s", (RELEASE,))
        connection.close()
