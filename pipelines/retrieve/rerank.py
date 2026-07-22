"""PPT-compatible rerank entrypoints for Week08."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAG_API_PATH = PROJECT_ROOT / "services" / "rag_api"
if str(RAG_API_PATH) not in sys.path:
    sys.path.insert(0, str(RAG_API_PATH))

from app.retrieval import CrossEncoderReranker, RetrievalResult  # noqa: E402


def rerank(query: str, results: list[RetrievalResult]) -> list[RetrievalResult]:
    """Rerank with the same fallback semantics as the RAG API service."""

    return CrossEncoderReranker().rerank(query, results)


__all__ = ["CrossEncoderReranker", "RetrievalResult", "rerank"]

