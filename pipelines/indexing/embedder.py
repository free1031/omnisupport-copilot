"""Embedding + pgvector 索引构建

从 knowledge_section 读取待索引的 chunks，
调用 Embedding API 生成向量，写回 pgvector 列，
更新 index_release_id 与 knowledge_doc.chunk_count。

使用方式:
    python -m pipelines.indexing.embedder \
        --index-release-id index-v0.1.0 \
        --batch-size 64
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import math
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from pipelines.indexing.index_manifest import build_manifest
from pipelines.indexing.reporting import write_index_build_outputs

logger = logging.getLogger(__name__)

EMBEDDING_DIM = 1536   # text-embedding-3-small / voyage-2 default


async def ensure_week08_index_schema(conn) -> None:
    """Keep existing local PostgreSQL volumes compatible with Week08 indexing."""

    await conn.execute(
        """
        ALTER TABLE knowledge_doc
            ADD COLUMN IF NOT EXISTS visibility_scope TEXT DEFAULT 'internal',
            ADD COLUMN IF NOT EXISTS entitlement_tier TEXT DEFAULT 'standard',
            ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'active',
            ADD COLUMN IF NOT EXISTS quality_status TEXT DEFAULT 'pass'
        """
    )
    await conn.execute(
        """
        ALTER TABLE knowledge_section
            ADD COLUMN IF NOT EXISTS chunk_strategy_version TEXT,
            ADD COLUMN IF NOT EXISTS embedding_model TEXT,
            ADD COLUMN IF NOT EXISTS embedding_dim INT,
            ADD COLUMN IF NOT EXISTS indexed_at TIMESTAMPTZ
        """
    )
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS index_manifest (
            index_release_id       TEXT PRIMARY KEY,
            data_release_id        TEXT NOT NULL,
            chunk_strategy_version TEXT NOT NULL,
            embedding_model        TEXT NOT NULL,
            embedding_dim          INT NOT NULL,
            provider               TEXT NOT NULL,
            built_at               TIMESTAMPTZ DEFAULT NOW(),
            source_table           TEXT NOT NULL DEFAULT 'knowledge_section',
            total_chunks           INT DEFAULT 0,
            embedded_chunks        INT DEFAULT 0,
            skipped_chunks         INT DEFAULT 0,
            error_count            INT DEFAULT 0,
            quality_gate           TEXT DEFAULT 'warn',
            notes                  TEXT,
            warnings               JSONB DEFAULT '[]'::jsonb
        )
        """
    )
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS index_build_log (
            build_id               TEXT PRIMARY KEY DEFAULT gen_random_uuid()::TEXT,
            index_release_id       TEXT REFERENCES index_manifest(index_release_id),
            data_release_id        TEXT,
            chunk_strategy_version TEXT,
            dry_run                BOOLEAN DEFAULT FALSE,
            status                 TEXT DEFAULT 'started',
            total_chunks           INT DEFAULT 0,
            embedded_chunks        INT DEFAULT 0,
            skipped_chunks         INT DEFAULT 0,
            error_count            INT DEFAULT 0,
            report_path            TEXT,
            created_at             TIMESTAMPTZ DEFAULT NOW()
        )
        """
    )
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS rag_audit_log (
            audit_id               TEXT PRIMARY KEY DEFAULT gen_random_uuid()::TEXT,
            request_id             TEXT,
            trace_id               TEXT,
            question               TEXT NOT NULL,
            actor_role             TEXT,
            filters                JSONB DEFAULT '{}'::jsonb,
            retrieved_evidence_ids TEXT[] DEFAULT ARRAY[]::TEXT[],
            scores                 JSONB DEFAULT '[]'::jsonb,
            answer                 TEXT,
            confidence             DOUBLE PRECISION,
            abstain_reason         TEXT,
            release_id             TEXT,
            data_release_id        TEXT,
            index_release_id       TEXT,
            prompt_release_id      TEXT,
            latency_ms             DOUBLE PRECISION,
            created_at             TIMESTAMPTZ DEFAULT NOW()
        )
        """
    )
    await conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_kdoc_week08_filters
            ON knowledge_doc (product_line, visibility_scope, entitlement_tier, status, quality_status)
        """
    )
    await conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_ksection_release_data
            ON knowledge_section (index_release_id, data_release_id)
        """
    )
    await conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_rag_audit_trace
            ON rag_audit_log (trace_id)
        """
    )
    await conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_rag_audit_created
            ON rag_audit_log (created_at DESC)
        """
    )


# ── Embedding 提供者 ──────────────────────────────────────────────────────────

class EmbeddingProvider:
    """
    多后端嵌入提供者。按优先级尝试：
    1. Voyage AI (voyage-2, Anthropic 推荐)
    2. OpenAI text-embedding-3-small
    3. 本地 sentence-transformers (离线 fallback)
    """

    def __init__(self, model: str | None = None):
        self._model = model or os.environ.get("EMBEDDING_MODEL", "auto")
        self._backend = None

    def _init_backend(self):
        if self._backend:
            return

        model = self._model
        if model == "auto":
            # 按优先级探测可用后端
            for try_model in ["voyage-2", "text-embedding-3-small", "deterministic"]:
                backend = self._try_init(try_model)
                if backend:
                    self._backend = backend
                    return
            raise RuntimeError("No embedding backend available")

        self._backend = self._try_init(model)
        if not self._backend:
            raise RuntimeError(f"Embedding backend '{model}' unavailable")

    def _try_init(self, model: str):
        if model == "voyage-2":
            return self._init_voyage()
        if model.startswith("text-embedding"):
            return self._init_openai(model)
        if model in {"deterministic", "local-hash", "course-local"}:
            return self._init_deterministic()
        if model == "local":
            return self._init_local()
        return None

    def _init_voyage(self):
        try:
            if not os.environ.get("VOYAGE_API_KEY"):
                return None
            import voyageai
            client = voyageai.Client(api_key=os.environ.get("VOYAGE_API_KEY", ""))
            # 测试连通性
            logger.info("Using Voyage AI embeddings (voyage-2, dim=1024)")
            return ("voyage", client, "voyage-2", 1024)
        except Exception:
            return None

    def _init_openai(self, model: str):
        try:
            if not os.environ.get("OPENAI_API_KEY"):
                return None
            from openai import OpenAI
            client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))
            logger.info(f"Using OpenAI embeddings ({model}, dim=1536)")
            return ("openai", client, model, 1536)
        except Exception:
            return None

    def _init_local(self):
        try:
            from sentence_transformers import SentenceTransformer
            model = SentenceTransformer("all-MiniLM-L6-v2")
            logger.info("Using local sentence-transformers (all-MiniLM-L6-v2, dim=384)")
            return ("local", model, "all-MiniLM-L6-v2", 384)
        except Exception:
            return None

    def _init_deterministic(self):
        logger.info("Using deterministic course-local embeddings (dim=1536)")
        return ("deterministic", None, "deterministic-hash-embedding-v1", EMBEDDING_DIM)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """批量生成嵌入向量，返回 list of float vectors"""
        self._init_backend()
        backend_type, client, model, dim = self._backend

        if backend_type == "voyage":
            result = client.embed(texts, model=model, input_type="document")
            return result.embeddings

        if backend_type == "openai":
            resp = client.embeddings.create(input=texts, model=model)
            return [item.embedding for item in resp.data]

        if backend_type == "local":
            embeddings = client.encode(texts, normalize_embeddings=True)
            return embeddings.tolist()

        if backend_type == "deterministic":
            return [_deterministic_embedding(text, dim) for text in texts]

        raise RuntimeError(f"Unknown backend: {backend_type}")

    @property
    def dim(self) -> int:
        self._init_backend()
        return self._backend[3]

    @property
    def provider(self) -> str:
        self._init_backend()
        return self._backend[0]

    @property
    def model(self) -> str:
        self._init_backend()
        return self._backend[2]


def _deterministic_embedding(text: str, dim: int = EMBEDDING_DIM) -> list[float]:
    """Generate a stable local embedding for classroom/offline execution.

    This is not a semantic production embedding model. It exists so Week08's
    pgvector, index manifest, retrieval, and audit paths are runnable without
    external API keys in student Docker environments.
    """

    seed = text.encode("utf-8", errors="ignore")
    values: list[float] = []
    block = 0
    while len(values) < dim:
        digest = hashlib.sha256(seed + b"\0" + str(block).encode()).digest()
        for offset in range(0, len(digest), 4):
            integer = int.from_bytes(digest[offset : offset + 4], "big", signed=False)
            values.append((integer / 2_147_483_647.5) - 1.0)
            if len(values) == dim:
                break
        block += 1

    norm = math.sqrt(sum(value * value for value in values)) or 1.0
    return [value / norm for value in values]


def format_pgvector(vector: Sequence[float]) -> str:
    """Serialize a Python vector into pgvector's text input format."""

    return "[" + ",".join(f"{float(value):.9g}" for value in vector) + "]"


# ── 索引构建器 ────────────────────────────────────────────────────────────────

@dataclass
class IndexStats:
    index_release_id: str = ""
    data_release_id: str = ""
    chunk_strategy_version: str = ""
    provider: str = "unknown"
    embedding_model: str = "unknown"
    embedding_dim: int = 0
    total_chunks: int = 0
    embedded: int = 0
    skipped: int = 0
    errors: int = 0
    elapsed_sec: float = 0.0
    warnings: list[str] = field(default_factory=list)


async def build_index(
    index_release_id: str,
    batch_size: int = 64,
    doc_id: str | None = None,         # None = 全量
    dry_run: bool = False,
    data_release_id: str = "data-week08-dev",
    chunk_strategy_version: str = "section_aware_v1",
    report_dir: str | Path = "reports/week08",
) -> IndexStats:
    """
    从 knowledge_section 读取未索引的 chunks，
    批量嵌入，写回 embedding 列，更新 index_release_id。
    """
    from pipelines.ingestion.db import acquire, close_pool

    stats = IndexStats(
        index_release_id=index_release_id,
        data_release_id=data_release_id,
        chunk_strategy_version=chunk_strategy_version,
    )
    provider = EmbeddingProvider()
    t0 = time.time()

    try:
        async with acquire() as conn:
            await ensure_week08_index_schema(conn)

            # 查询待索引 chunks（embedding IS NULL 或 index_release_id 不匹配）
            where_clauses = ["(embedding IS NULL OR index_release_id != $1)"]
            params: list = [index_release_id]

            if doc_id:
                where_clauses.append(f"doc_id = ${len(params)+1}")
                params.append(doc_id)

            rows = await conn.fetch(
                f"""
                SELECT section_id, doc_id, content
                FROM knowledge_section
                WHERE {" AND ".join(where_clauses)}
                ORDER BY doc_id, chunk_index
                """,
                *params,
            )

            stats.total_chunks = len(rows)
            logger.info(f"Found {stats.total_chunks} chunks to index (release: {index_release_id})")

            if dry_run:
                logger.info("[dry-run] Skipping actual embedding generation")
                stats.skipped = stats.total_chunks
                stats.provider = "dry_run"
                stats.embedding_model = "dry_run"
                stats.embedding_dim = EMBEDDING_DIM
                stats.warnings.append("dry_run=true; embeddings were not generated")
                return stats

            try:
                stats.provider = provider.provider
                stats.embedding_model = provider.model
                stats.embedding_dim = provider.dim
            except Exception as e:
                stats.errors = stats.total_chunks
                stats.warnings.append(f"embedding provider unavailable: {e}")
                return stats

            if stats.embedding_dim != EMBEDDING_DIM:
                stats.errors = stats.total_chunks
                stats.skipped = stats.total_chunks
                stats.warnings.append(
                    f"dimension mismatch: provider returned {stats.embedding_dim}, "
                    f"but knowledge_section.embedding is vector({EMBEDDING_DIM})"
                )
                return stats

            # 批量处理
            for i in range(0, len(rows), batch_size):
                batch = rows[i : i + batch_size]
                texts = [r["content"] for r in batch]
                ids = [r["section_id"] for r in batch]

                try:
                    vectors = provider.embed_batch(texts)
                except Exception as e:
                    logger.error(f"Embedding batch {i//batch_size} failed: {e}")
                    stats.errors += len(batch)
                    continue

                # 批量写回向量
                for row_id, vector in zip(ids, vectors):
                    try:
                        await conn.execute(
                            """
                            UPDATE knowledge_section
                            SET embedding = $1::vector,
                                embedding_model = $2,
                                embedding_dim = $3,
                                index_release_id = $4,
                                data_release_id = $5,
                                chunk_strategy_version = $6,
                                indexed_at = NOW()
                            WHERE section_id = $7
                            """,
                            format_pgvector(vector),
                            stats.embedding_model,
                            stats.embedding_dim,
                            index_release_id,
                            data_release_id,
                            chunk_strategy_version,
                            row_id,
                        )
                        stats.embedded += 1
                    except Exception as e:
                        logger.error(f"Failed to update embedding for {row_id}: {e}")
                        stats.errors += 1

                if (i // batch_size) % 10 == 0:
                    logger.info(f"Progress: {stats.embedded}/{stats.total_chunks} embedded")

            # 更新 knowledge_doc.chunk_count
            await conn.execute(
                """
                UPDATE knowledge_doc kd
                SET chunk_count = sub.cnt,
                    index_release_id = $1,
                    data_release_id = $2,
                    indexed_at = NOW()
                FROM (
                    SELECT doc_id, COUNT(*) AS cnt
                    FROM knowledge_section
                    WHERE index_release_id = $1
                    GROUP BY doc_id
                ) sub
                WHERE kd.doc_id = sub.doc_id
                """,
                index_release_id,
                data_release_id,
            )

            await conn.execute(
                """
                INSERT INTO index_manifest (
                    index_release_id, data_release_id, chunk_strategy_version,
                    embedding_model, embedding_dim, provider, source_table,
                    total_chunks, embedded_chunks, skipped_chunks, error_count,
                    quality_gate, notes, warnings
                )
                VALUES ($1, $2, $3, $4, $5, $6, 'knowledge_section',
                        $7, $8, $9, $10, $11, $12, $13::jsonb)
                ON CONFLICT (index_release_id) DO UPDATE
                SET data_release_id = EXCLUDED.data_release_id,
                    chunk_strategy_version = EXCLUDED.chunk_strategy_version,
                    embedding_model = EXCLUDED.embedding_model,
                    embedding_dim = EXCLUDED.embedding_dim,
                    provider = EXCLUDED.provider,
                    built_at = NOW(),
                    total_chunks = EXCLUDED.total_chunks,
                    embedded_chunks = EXCLUDED.embedded_chunks,
                    skipped_chunks = EXCLUDED.skipped_chunks,
                    error_count = EXCLUDED.error_count,
                    quality_gate = EXCLUDED.quality_gate,
                    notes = EXCLUDED.notes,
                    warnings = EXCLUDED.warnings
                """,
                index_release_id,
                data_release_id,
                chunk_strategy_version,
                stats.embedding_model,
                stats.embedding_dim,
                stats.provider,
                stats.total_chunks,
                stats.embedded,
                stats.skipped,
                stats.errors,
                "fail" if stats.errors else ("warn" if stats.skipped else "pass"),
                "Week8 index build completed",
                json.dumps(stats.warnings, ensure_ascii=False),
            )

            # 启用向量索引（首次构建后）
            await _ensure_vector_index(conn)

        return stats
    finally:
        stats.elapsed_sec = time.time() - t0
        logger.info(
            f"Index build complete: {stats.embedded} embedded, "
            f"{stats.errors} errors, {stats.elapsed_sec:.1f}s elapsed"
        )
        _write_report(stats, report_dir)
        await close_pool()


def _write_report(stats: IndexStats, report_dir: str | Path) -> None:
    manifest = build_manifest(
        index_release_id=stats.index_release_id,
        data_release_id=stats.data_release_id,
        chunk_strategy_version=stats.chunk_strategy_version,
        embedding_model=stats.embedding_model,
        embedding_dim=stats.embedding_dim or EMBEDDING_DIM,
        provider=stats.provider,
        source_table="knowledge_section",
        total_chunks=stats.total_chunks,
        embedded_chunks=stats.embedded,
        skipped_chunks=stats.skipped,
        error_count=stats.errors,
        warnings=stats.warnings,
        elapsed_sec=stats.elapsed_sec,
    )
    md_path, json_path = write_index_build_outputs(manifest, report_dir)
    logger.info("Index reports written: %s %s", md_path, json_path)


async def _ensure_vector_index(conn):
    """确保 IVFFlat 向量索引存在（首次索引构建后创建）"""
    try:
        idx_exists = await conn.fetchval(
            "SELECT 1 FROM pg_indexes WHERE indexname = 'idx_ksection_embedding'"
        )
        if not idx_exists:
            logger.info("Creating IVFFlat vector index...")
            # lists 参数约为 chunk 总数的平方根（至少 1）
            count = await conn.fetchval("SELECT COUNT(*) FROM knowledge_section WHERE embedding IS NOT NULL")
            lists = max(1, int(count ** 0.5))
            await conn.execute(
                f"""
                CREATE INDEX idx_ksection_embedding
                ON knowledge_section
                USING ivfflat (embedding vector_cosine_ops)
                WITH (lists = {lists})
                """
            )
            logger.info(f"Vector index created (lists={lists})")
    except Exception as e:
        logger.warning(f"Could not create vector index: {e}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="pgvector Index Builder")
    parser.add_argument("--index-release-id", default="index-v0.1.0")
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--doc-id", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--data-release-id", default=os.environ.get("WEEK08_DATA_RELEASE_ID", "data-week08-dev"))
    parser.add_argument("--chunk-strategy-version", default=os.environ.get("WEEK08_CHUNK_STRATEGY_VERSION", "section_aware_v1"))
    parser.add_argument("--report-dir", default=os.environ.get("WEEK08_REPORT_DIR", "reports/week08"))
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    stats = asyncio.run(
        build_index(
            args.index_release_id,
            args.batch_size,
            args.doc_id,
            args.dry_run,
            args.data_release_id,
            args.chunk_strategy_version,
            args.report_dir,
        )
    )
    sys.exit(1 if stats.errors > 0 else 0)


if __name__ == "__main__":
    main()
