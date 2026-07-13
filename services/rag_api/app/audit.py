"""Week8 RAG audit helpers."""

from __future__ import annotations

import json
import logging
from time import perf_counter

logger = logging.getLogger(__name__)


class Timer:
    def __init__(self) -> None:
        self.start = perf_counter()

    @property
    def elapsed_ms(self) -> float:
        return round((perf_counter() - self.start) * 1000, 2)


async def write_rag_audit_log(
    *,
    conn,
    request_id: str,
    trace_id: str,
    question: str,
    actor_role: str | None,
    filters: dict,
    retrieved_evidence_ids: list[str],
    scores: list[dict],
    answer: str,
    confidence: float,
    abstain_reason: str | None,
    release_id: str,
    data_release_id: str | None,
    index_release_id: str,
    prompt_release_id: str,
    latency_ms: float,
) -> bool:
    try:
        await conn.execute(
            """
            INSERT INTO rag_audit_log (
                request_id, trace_id, question, actor_role, filters,
                retrieved_evidence_ids, scores, answer, confidence,
                abstain_reason, release_id, data_release_id, index_release_id,
                prompt_release_id, latency_ms
            )
            VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7::jsonb, $8, $9,
                    $10, $11, $12, $13, $14, $15)
            """,
            request_id,
            trace_id,
            question,
            actor_role,
            json.dumps(filters, ensure_ascii=False),
            retrieved_evidence_ids,
            json.dumps(scores, ensure_ascii=False),
            answer,
            confidence,
            abstain_reason,
            release_id,
            data_release_id,
            index_release_id,
            prompt_release_id,
            latency_ms,
        )
        return True
    except Exception as exc:
        logger.warning("RAG audit log write failed (non-fatal): %s", exc)
        return False
