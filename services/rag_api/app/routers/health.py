"""RAG service readiness checks backed by the active release state."""

import asyncpg
from fastapi import APIRouter

from app.config import settings
from app.llm import resolve_llm_runtime, resolve_query_rewrite_runtime
from app.models.rag_models import HealthResponse

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse, summary="服务健康检查")
async def health_check() -> HealthResponse:
    """
    检查 RAG API 各依赖组件的状态。

    - **status**: ok / degraded / down
    - **checks**: 各组件的健康状态
    """
    database_status, index_status = await _check_storage()
    llm_runtime = resolve_llm_runtime()
    rewrite_runtime = resolve_query_rewrite_runtime()
    rewrite_requires_llm = (
        settings.query_rewrite_enabled and settings.query_rewrite_strategy == "llm"
    )
    rewrite_status = (
        "disabled"
        if not settings.query_rewrite_enabled or settings.query_rewrite_strategy == "disabled"
        else "llm_ready"
        if rewrite_runtime.configured and settings.query_rewrite_strategy in {"auto", "llm"}
        else "deterministic"
    )
    checks: dict[str, str] = {
        "api": "ok",
        "database": database_status,
        "vector_index": index_status,
        "llm": "external" if llm_runtime.configured else "deterministic_fallback",
        "llm_provider": llm_runtime.provider,
        "llm_model": llm_runtime.model,
        "query_rewrite": rewrite_status,
        "query_rewrite_provider": rewrite_runtime.provider,
        "query_rewrite_model": rewrite_runtime.model,
        "query_rewrite_prompt_release_id": settings.query_rewrite_prompt_release_id,
    }

    overall = (
        "ok"
        if (
            database_status == "ok"
            and index_status == "ok"
            and (not rewrite_requires_llm or rewrite_runtime.configured)
        )
        else "degraded"
    )

    return HealthResponse(
        status=overall,
        service="rag_api",
        version="0.1.0",
        release_id=settings.release_id,
        checks=checks,
    )


async def _check_storage() -> tuple[str, str]:
    """Check PostgreSQL and the exact data/index release served by this API."""
    conn: asyncpg.Connection | None = None
    try:
        conn = await asyncpg.connect(
            settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
        )
        row = await conn.fetchrow(
            """
            SELECT
                im.quality_gate,
                COUNT(ks.section_id) FILTER (WHERE ks.embedding IS NOT NULL) AS ready_chunks
            FROM index_manifest im
            LEFT JOIN knowledge_section ks
              ON ks.index_release_id = im.index_release_id
             AND ks.data_release_id = im.data_release_id
            WHERE im.index_release_id = $1
              AND im.data_release_id = $2
            GROUP BY im.quality_gate
            """,
            settings.index_release_id,
            settings.data_release_id,
        )
        index_ready = bool(
            row
            and row["quality_gate"] == "pass"
            and int(row["ready_chunks"] or 0) > 0
        )
        return "ok", "ok" if index_ready else "empty"
    except Exception:
        return "down", "unknown"
    finally:
        if conn is not None:
            await conn.close()
