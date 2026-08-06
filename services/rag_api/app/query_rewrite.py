"""Governed online query rewrite with validation, fallback and resilience.

Correctness does not depend on an LLM: deterministic rewriting is always
available.  LLM output is treated as untrusted data and admitted only after
strict JSON, length and protected-identifier validation.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections import OrderedDict
from dataclasses import dataclass, replace
from pathlib import Path
from time import monotonic
from typing import Awaitable, Callable, Literal

from app.config import settings
from app.llm import LLMCompletion, complete, resolve_query_rewrite_runtime
from observability.runtime import hash_text
from observability.runtime.privacy import redact_text
from pipelines.query.rewriter import (
    build_hyde_document,
    extract_protected_terms,
    invented_protected_terms,
    normalize_query,
    preserve_protected_terms,
    remove_invented_protected_terms,
    rewrite_query,
)

logger = logging.getLogger(__name__)

RewriteMode = Literal["disabled", "deterministic", "llm", "fallback"]
ALLOWED_REWRITE_REASONS = {
    "identity_rewrite",
    "intent_clarified",
    "context_compacted",
    "synonyms_added",
    "procedural_expansion",
    "ambiguity_reduced",
}

QUERY_REWRITE_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "semantic_query": {"type": "string", "minLength": 1},
        "hyde_document": {"type": ["string", "null"]},
        "rewrite_reasons": {
            "type": "array",
            "items": {"type": "string", "enum": sorted(ALLOWED_REWRITE_REASONS)},
            "minItems": 1,
            "maxItems": 4,
            "uniqueItems": True,
        },
    },
    "required": ["semantic_query", "hyde_document", "rewrite_reasons"],
    "additionalProperties": False,
}


class InvalidRewriteOutputError(ValueError):
    """Raised when model output fails the query rewrite admission policy."""


@dataclass(frozen=True)
class QueryRewriteResult:
    normalized_query: str
    semantic_query: str
    lexical_query: str
    lexical_terms: tuple[str, ...]
    hyde_document: str | None
    mode: RewriteMode
    provider: str
    model: str
    prompt_release_id: str
    rewrite_reasons: tuple[str, ...]
    fallback_reason: str | None
    latency_ms: float
    attempts: int
    safety_repairs: tuple[str, ...] = ()
    cache_hit: bool = False
    coalesced: bool = False
    circuit_state: str = "closed"

    @property
    def vector_query(self) -> str:
        """HyDE is opt-in; when present it becomes the embedding query only."""

        return self.hyde_document or self.semantic_query

    def audit_metadata(self, original_query: str) -> dict[str, object]:
        """Return an audit-safe record containing no raw customer query."""

        return {
            "schema_version": "1.0",
            "mode": self.mode,
            "provider": self.provider,
            "model": self.model,
            "prompt_release_id": self.prompt_release_id,
            "rewrite_reasons": list(self.rewrite_reasons),
            "fallback_reason": self.fallback_reason,
            "original_query_sha256": hash_text(original_query),
            "semantic_query_sha256": hash_text(self.semantic_query),
            "original_query_length": len(original_query),
            "semantic_query_length": len(self.semantic_query),
            "lexical_term_count": len(self.lexical_terms),
            "hyde_used": bool(self.hyde_document),
            "attempts": self.attempts,
            "safety_repairs": list(self.safety_repairs),
            "cache_hit": self.cache_hit,
            "coalesced": self.coalesced,
            "circuit_state": self.circuit_state,
            "latency_ms": self.latency_ms,
        }


@dataclass
class _CacheEntry:
    expires_at: float
    result: QueryRewriteResult


class _TTLRewriteCache:
    def __init__(self, *, max_entries: int, ttl_seconds: float) -> None:
        self.max_entries = max_entries
        self.ttl_seconds = ttl_seconds
        self._values: OrderedDict[str, _CacheEntry] = OrderedDict()

    def get(self, key: str, now: float) -> QueryRewriteResult | None:
        entry = self._values.get(key)
        if entry is None:
            return None
        if entry.expires_at <= now:
            self._values.pop(key, None)
            return None
        self._values.move_to_end(key)
        return entry.result

    def set(self, key: str, result: QueryRewriteResult, now: float) -> None:
        if self.max_entries <= 0 or self.ttl_seconds <= 0:
            return
        self._values[key] = _CacheEntry(now + self.ttl_seconds, result)
        self._values.move_to_end(key)
        while len(self._values) > self.max_entries:
            self._values.popitem(last=False)

    def clear(self) -> None:
        self._values.clear()


class _AsyncCircuitBreaker:
    def __init__(self, *, failure_threshold: int, recovery_seconds: float) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_seconds = recovery_seconds
        self._failure_count = 0
        self._opened_at = 0.0
        self._half_open_probe = False
        self._state = "closed"
        self._lock = asyncio.Lock()

    async def allow_request(self, now: float) -> tuple[bool, str]:
        async with self._lock:
            if self._state == "open":
                if now - self._opened_at < self.recovery_seconds:
                    return False, "open"
                if self._half_open_probe:
                    return False, "half_open"
                self._state = "half_open"
                self._half_open_probe = True
                return True, "half_open"
            if self._state == "half_open" and self._half_open_probe:
                return False, "half_open"
            return True, self._state

    async def record_success(self) -> None:
        async with self._lock:
            self._failure_count = 0
            self._opened_at = 0.0
            self._half_open_probe = False
            self._state = "closed"

    async def record_failure(self, now: float) -> str:
        async with self._lock:
            self._failure_count += 1
            if self._state == "half_open" or self._failure_count >= self.failure_threshold:
                self._state = "open"
                self._opened_at = now
                self._half_open_probe = False
            return self._state

    async def reset(self) -> None:
        async with self._lock:
            self._failure_count = 0
            self._opened_at = 0.0
            self._half_open_probe = False
            self._state = "closed"


CompletionFunction = Callable[..., Awaitable[LLMCompletion]]


class QueryRewriteService:
    def __init__(
        self,
        *,
        config=settings,
        completion: CompletionFunction = complete,
        runtime_resolver=resolve_query_rewrite_runtime,
    ) -> None:
        self.config = config
        self.completion = completion
        self.runtime_resolver = runtime_resolver
        self.system_prompt = self._load_prompt()
        self.cache = _TTLRewriteCache(
            max_entries=config.query_rewrite_cache_max_entries,
            ttl_seconds=config.query_rewrite_cache_ttl_seconds,
        )
        self.circuit = _AsyncCircuitBreaker(
            failure_threshold=config.query_rewrite_circuit_failure_threshold,
            recovery_seconds=config.query_rewrite_circuit_recovery_seconds,
        )
        self._inflight: dict[str, asyncio.Future[QueryRewriteResult]] = {}
        self._inflight_lock = asyncio.Lock()

    @staticmethod
    def _load_prompt() -> str:
        path = Path(__file__).parent / "prompts" / "query_rewrite_v1.md"
        return path.read_text(encoding="utf-8").strip()

    async def rewrite(self, query: str, *, tenant_id: str) -> QueryRewriteResult:
        started = monotonic()
        strategy = self.config.query_rewrite_strategy
        if not self.config.query_rewrite_enabled or strategy == "disabled":
            identity = self._deterministic_result(query, redact_pii=False)
            return replace(
                identity,
                semantic_query=identity.normalized_query,
                lexical_query=identity.normalized_query,
                hyde_document=None,
                mode="disabled",
                rewrite_reasons=("identity_rewrite",),
                latency_ms=self._elapsed_ms(started),
            )
        deterministic = self._deterministic_result(query)
        if strategy == "deterministic":
            return replace(deterministic, latency_ms=self._elapsed_ms(started))

        try:
            runtime = self.runtime_resolver()
        except Exception as exc:
            return self._fallback(
                deterministic,
                started,
                reason=f"runtime_config_error:{type(exc).__name__}",
            )
        if not runtime.configured:
            return self._fallback(deterministic, started, reason="llm_not_configured")

        cache_key = self._cache_key(query, tenant_id, runtime.provider, runtime.model)
        cached = self.cache.get(cache_key, monotonic())
        if cached is not None:
            return replace(cached, cache_hit=True, latency_ms=self._elapsed_ms(started))

        owner, future = await self._reserve_inflight(cache_key)
        if not owner:
            shared = await future
            return replace(
                shared,
                coalesced=True,
                latency_ms=self._elapsed_ms(started),
            )

        try:
            result = await self._rewrite_uncached(query, deterministic, runtime, started)
            if result.mode == "llm":
                self.cache.set(cache_key, result, monotonic())
        except asyncio.CancelledError:
            async with self._inflight_lock:
                reserved = self._inflight.pop(cache_key, None)
                if reserved is not None and not reserved.done():
                    reserved.cancel()
            raise
        except Exception as exc:  # defensive boundary: rewrite must never take down RAG
            logger.exception("Unexpected query rewrite failure; using deterministic fallback")
            result = self._fallback(
                deterministic,
                started,
                reason=f"internal_error:{type(exc).__name__}",
            )
        async with self._inflight_lock:
            reserved = self._inflight.pop(cache_key, None)
            if reserved is not None and not reserved.done():
                reserved.set_result(result)
        return result

    async def _rewrite_uncached(self, query, deterministic, runtime, started):
        allowed, circuit_state = await self.circuit.allow_request(monotonic())
        if not allowed:
            return self._fallback(
                deterministic,
                started,
                reason="circuit_open",
                circuit_state=circuit_state,
            )

        user_prompt = json.dumps(
            {
                "original_query": deterministic.normalized_query,
                "baseline_query": deterministic.semantic_query,
                "protected_terms": extract_protected_terms(deterministic.normalized_query),
                "hyde_enabled": self.config.query_rewrite_hyde_enabled,
                "max_output_characters": self.config.query_rewrite_max_output_chars,
            },
            ensure_ascii=False,
        )
        deadline = monotonic() + self.config.query_rewrite_timeout_seconds
        last_reason = "rewrite_failed"
        attempts = 0
        for attempt in range(1, self.config.query_rewrite_max_attempts + 1):
            attempts = attempt
            remaining = deadline - monotonic()
            if remaining <= 0:
                last_reason = "rewrite_timeout"
                break
            try:
                completion = await asyncio.wait_for(
                    self.completion(
                        system_prompt=self.system_prompt,
                        user_prompt=user_prompt,
                        runtime=runtime,
                        max_tokens=self.config.query_rewrite_max_tokens,
                        context_tokens=self.config.query_rewrite_context_tokens,
                        temperature=self.config.query_rewrite_temperature,
                        timeout_seconds=remaining,
                        max_retries=0,
                        json_mode=True,
                        json_schema=QUERY_REWRITE_OUTPUT_SCHEMA,
                    ),
                    timeout=remaining,
                )
                semantic_query, hyde_document, reasons, safety_repairs = self._parse_output(
                    deterministic.normalized_query,
                    deterministic.semantic_query,
                    completion.text,
                )
                await self.circuit.record_success()
                return QueryRewriteResult(
                    normalized_query=deterministic.normalized_query,
                    semantic_query=semantic_query,
                    lexical_query=self._lexical_query(
                        deterministic.normalized_query,
                        semantic_query,
                    ),
                    lexical_terms=deterministic.lexical_terms,
                    hyde_document=hyde_document,
                    mode="llm",
                    provider=completion.provider,
                    model=completion.model,
                    prompt_release_id=self.config.query_rewrite_prompt_release_id,
                    rewrite_reasons=reasons,
                    fallback_reason=None,
                    latency_ms=self._elapsed_ms(started),
                    attempts=attempts,
                    safety_repairs=safety_repairs,
                    circuit_state="closed",
                )
            except asyncio.TimeoutError:
                last_reason = "rewrite_timeout"
            except InvalidRewriteOutputError as exc:
                last_reason = f"invalid_llm_output:{str(exc)}"
            except Exception as exc:
                last_reason = f"llm_error:{type(exc).__name__}"

            remaining = deadline - monotonic()
            if attempt < self.config.query_rewrite_max_attempts and remaining > 0.05:
                await asyncio.sleep(min(0.05 * (2 ** (attempt - 1)), remaining / 2))

        state = await self.circuit.record_failure(monotonic())
        logger.warning(
            "Query rewrite degraded provider=%s model=%s reason=%s attempts=%s",
            runtime.provider,
            runtime.model,
            last_reason,
            attempts,
        )
        return self._fallback(
            deterministic,
            started,
            reason=last_reason,
            provider=runtime.provider,
            model=runtime.model,
            attempts=attempts,
            circuit_state=state,
        )

    def _parse_output(self, original_query: str, baseline_query: str, text: str):
        if len(text) > self.config.query_rewrite_max_output_chars * 4:
            raise InvalidRewriteOutputError("response_too_large")
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise InvalidRewriteOutputError("invalid_json") from exc
        if not isinstance(payload, dict):
            raise InvalidRewriteOutputError("root_not_object")
        expected = {"semantic_query", "hyde_document", "rewrite_reasons"}
        if set(payload) != expected:
            raise InvalidRewriteOutputError("unexpected_fields")

        semantic = payload["semantic_query"]
        if not isinstance(semantic, str):
            raise InvalidRewriteOutputError("semantic_query_not_string")
        semantic = normalize_query(semantic)
        if not semantic:
            raise InvalidRewriteOutputError("semantic_query_empty")
        if len(semantic) > self.config.query_rewrite_max_output_chars:
            raise InvalidRewriteOutputError("semantic_query_too_large")
        semantic, removed_terms = remove_invented_protected_terms(original_query, semantic)
        semantic = preserve_protected_terms(original_query, semantic)
        semantic_folded = semantic.casefold()
        baseline_folded = baseline_query.casefold()
        if semantic_folded in baseline_folded:
            semantic = baseline_query
        elif baseline_folded not in semantic_folded:
            # The deterministic expansion is the recall floor. LLM output may
            # enrich it, but may never remove its validated retrieval concepts.
            semantic = normalize_query(f"{baseline_query} {semantic}")
        if len(semantic) > self.config.query_rewrite_max_output_chars:
            raise InvalidRewriteOutputError("semantic_query_too_large_after_recall_floor")

        hyde = payload["hyde_document"]
        if not self.config.query_rewrite_hyde_enabled:
            if hyde is not None:
                raise InvalidRewriteOutputError("hyde_not_enabled")
            hyde = None
        elif hyde is not None:
            if not isinstance(hyde, str):
                raise InvalidRewriteOutputError("hyde_document_not_string")
            hyde = normalize_query(hyde)
            if not hyde or len(hyde) > self.config.query_rewrite_max_output_chars:
                raise InvalidRewriteOutputError("invalid_hyde_length")
            if invented_protected_terms(original_query, hyde):
                raise InvalidRewriteOutputError("hyde_invented_protected_term")
            hyde = preserve_protected_terms(original_query, hyde)
            if len(hyde) > self.config.query_rewrite_max_output_chars:
                raise InvalidRewriteOutputError("hyde_too_large_after_term_preservation")

        raw_reasons = payload["rewrite_reasons"]
        if not isinstance(raw_reasons, list) or not raw_reasons:
            raise InvalidRewriteOutputError("rewrite_reasons_invalid")
        if any(not isinstance(reason, str) for reason in raw_reasons):
            raise InvalidRewriteOutputError("rewrite_reason_not_string")
        reasons = tuple(dict.fromkeys(raw_reasons))
        if any(reason not in ALLOWED_REWRITE_REASONS for reason in reasons):
            raise InvalidRewriteOutputError("rewrite_reason_not_allowed")
        safety_repairs = ("removed_invented_protected_terms",) if removed_terms else ()
        return semantic, hyde, reasons, safety_repairs

    def _deterministic_result(
        self,
        query: str,
        *,
        redact_pii: bool | None = None,
    ) -> QueryRewriteResult:
        should_redact = (
            self.config.query_rewrite_redact_pii if redact_pii is None else redact_pii
        )
        governed_query = redact_text(query) if should_redact else query
        plan = (
            build_hyde_document(governed_query)
            if self.config.query_rewrite_hyde_enabled
            else rewrite_query(governed_query)
        )
        return QueryRewriteResult(
            normalized_query=plan.normalized_query,
            semantic_query=plan.semantic_query,
            lexical_query=self._lexical_query(plan.normalized_query, plan.semantic_query),
            lexical_terms=tuple(plan.lexical_terms),
            hyde_document=plan.hyde_document,
            mode="deterministic",
            provider="deterministic",
            model="rules-v1",
            prompt_release_id=self.config.query_rewrite_prompt_release_id,
            rewrite_reasons=tuple(plan.rewrite_reasons),
            fallback_reason=None,
            latency_ms=0.0,
            attempts=0,
        )

    def _fallback(
        self,
        deterministic: QueryRewriteResult,
        started: float,
        *,
        reason: str,
        provider: str = "deterministic",
        model: str = "rules-v1",
        attempts: int = 0,
        circuit_state: str = "closed",
    ) -> QueryRewriteResult:
        return replace(
            deterministic,
            mode="fallback",
            provider=provider,
            model=model,
            fallback_reason=reason[:160],
            latency_ms=self._elapsed_ms(started),
            attempts=attempts,
            circuit_state=circuit_state,
        )

    async def _reserve_inflight(self, key: str):
        async with self._inflight_lock:
            existing = self._inflight.get(key)
            if existing is not None:
                return False, existing
            future = asyncio.get_running_loop().create_future()
            self._inflight[key] = future
            return True, future

    def _cache_key(self, query: str, tenant_id: str, provider: str, model: str) -> str:
        material = "\x1f".join(
            [
                tenant_id,
                normalize_query(query),
                provider,
                model,
                self.config.query_rewrite_prompt_release_id,
                str(self.config.query_rewrite_hyde_enabled),
            ]
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    @staticmethod
    def _lexical_query(normalized_query: str, semantic_query: str) -> str:
        # Original terms come first because FTS intentionally caps token count.
        return normalize_query(f"{normalized_query} {semantic_query}")

    @staticmethod
    def _elapsed_ms(started: float) -> float:
        return round((monotonic() - started) * 1000, 2)

    async def reset_runtime_state(self) -> None:
        """Test/operations hook; does not alter configured policy."""

        self.cache.clear()
        await self.circuit.reset()


query_rewrite_service = QueryRewriteService()
