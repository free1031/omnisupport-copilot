# ruff: noqa: E402 - service path is installed before app imports

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "services" / "rag_api"))

from app.llm import LLMCompletion, LLMRuntime
from app.query_rewrite import QueryRewriteService


def config(**overrides):
    values = {
        "query_rewrite_enabled": True,
        "query_rewrite_strategy": "auto",
        "query_rewrite_prompt_release_id": "query-rewrite-test-v1",
        "query_rewrite_timeout_seconds": 0.2,
        "query_rewrite_max_attempts": 2,
        "query_rewrite_max_output_chars": 512,
        "query_rewrite_max_tokens": 128,
        "query_rewrite_context_tokens": 2048,
        "query_rewrite_temperature": 0.0,
        "query_rewrite_hyde_enabled": False,
        "query_rewrite_redact_pii": True,
        "query_rewrite_cache_ttl_seconds": 60.0,
        "query_rewrite_cache_max_entries": 32,
        "query_rewrite_circuit_failure_threshold": 2,
        "query_rewrite_circuit_recovery_seconds": 30.0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def runtime(*, configured=True):
    return LLMRuntime(
        provider="ollama" if configured else "fallback",
        model="qwen3:14b" if configured else "none",
        api_key="ollama" if configured else "",
        base_url="http://localhost:11434/v1" if configured else None,
        configured=configured,
    )


def completion_payload(semantic_query: str, *, reason="intent_clarified") -> str:
    return json.dumps(
        {
            "semantic_query": semantic_query,
            "hyde_document": None,
            "rewrite_reasons": [reason],
        }
    )


async def _case_llm_rewrite_preserves_identifiers_and_uses_tenant_scoped_cache():
    calls = []

    async def complete(**_kwargs):
        calls.append(1)
        return LLMCompletion(
            text=completion_payload("Edge Gateway startup recovery procedure"),
            provider="ollama",
            model="qwen3:14b",
        )

    service = QueryRewriteService(
        config=config(), completion=complete, runtime_resolver=runtime
    )
    query = "How do I recover EG-3000 after EG-BOOT-004?"

    first = await service.rewrite(query, tenant_id="tenant-a")
    cached = await service.rewrite(query, tenant_id="tenant-a")
    other_tenant = await service.rewrite(query, tenant_id="tenant-b")

    assert first.mode == "llm"
    assert "EG-3000" in first.semantic_query
    assert "EG-BOOT-004" in first.semantic_query
    assert cached.cache_hit is True
    assert other_tenant.cache_hit is False
    assert len(calls) == 2
    audit = first.audit_metadata(query)
    assert query not in json.dumps(audit)
    assert audit["provider"] == "ollama"


async def _case_invented_identifier_is_removed_and_audited():
    async def invalid_completion(**_kwargs):
        return LLMCompletion(
            text=completion_payload("Recover EG-FAKE-999 using the runbook"),
            provider="ollama",
            model="qwen3:14b",
        )

    service = QueryRewriteService(
        config=config(),
        completion=invalid_completion,
        runtime_resolver=runtime,
    )
    query = "How do I recover EG-3000?"

    repaired = await service.rewrite(query, tenant_id="tenant-a")

    assert repaired.mode == "llm"
    assert repaired.attempts == 1
    assert repaired.safety_repairs == ("removed_invented_protected_terms",)
    assert repaired.circuit_state == "closed"
    assert "EG-FAKE-999" not in repaired.semantic_query
    assert "EG-3000" in repaired.semantic_query
    assert repaired.audit_metadata(query)["safety_repairs"] == [
        "removed_invented_protected_terms"
    ]


async def _case_unrepairable_invalid_output_retries_and_opens_circuit():
    async def invalid_completion(**_kwargs):
        payload = json.loads(completion_payload("Recover the gateway"))
        payload["unexpected"] = "field"
        return LLMCompletion(
            text=json.dumps(payload),
            provider="ollama",
            model="qwen3:14b",
        )

    service = QueryRewriteService(
        config=config(query_rewrite_circuit_failure_threshold=1),
        completion=invalid_completion,
        runtime_resolver=runtime,
    )
    degraded = await service.rewrite("How do I recover EG-3000?", tenant_id="tenant-a")
    blocked = await service.rewrite("How do I reboot EG-3001?", tenant_id="tenant-a")

    assert degraded.mode == "fallback"
    assert degraded.attempts == 2
    assert degraded.fallback_reason == "invalid_llm_output:unexpected_fields"
    assert degraded.circuit_state == "open"
    assert blocked.mode == "fallback"
    assert blocked.fallback_reason == "circuit_open"


async def _case_timeout_and_missing_provider_are_lossless_fallbacks():
    async def slow_completion(**_kwargs):
        await asyncio.sleep(0.1)
        raise AssertionError("wait_for should cancel the completion")

    timeout_service = QueryRewriteService(
        config=config(query_rewrite_timeout_seconds=0.01),
        completion=slow_completion,
        runtime_resolver=runtime,
    )
    timed_out = await timeout_service.rewrite("如何恢复 EG-3000？", tenant_id="tenant-a")

    no_provider = QueryRewriteService(
        config=config(),
        completion=slow_completion,
        runtime_resolver=lambda: runtime(configured=False),
    )
    local = await no_provider.rewrite("How do I recover EG-3000?", tenant_id="tenant-a")

    assert timed_out.mode == "fallback"
    assert timed_out.fallback_reason == "rewrite_timeout"
    assert "EG-3000" in timed_out.semantic_query
    assert local.mode == "fallback"
    assert local.fallback_reason == "llm_not_configured"


async def _case_disabled_strategy_is_an_immediate_identity_rollback():
    async def should_not_run(**_kwargs):
        raise AssertionError("disabled rewrite must not call an LLM")

    service = QueryRewriteService(
        config=config(query_rewrite_strategy="disabled"),
        completion=should_not_run,
        runtime_resolver=runtime,
    )
    result = await service.rewrite("  reboot\x00   EG-3000  ", tenant_id="tenant-a")

    assert result.mode == "disabled"
    assert result.semantic_query == "reboot EG-3000"
    assert result.lexical_query == "reboot EG-3000"


async def _case_concurrent_identical_requests_are_single_flight():
    calls = 0

    async def complete(**_kwargs):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        return LLMCompletion(
            text=completion_payload("gateway recovery procedure"),
            provider="ollama",
            model="qwen3:14b",
        )

    service = QueryRewriteService(
        config=config(), completion=complete, runtime_resolver=runtime
    )
    query = "How can the gateway be recovered?"
    first, second = await asyncio.gather(
        service.rewrite(query, tenant_id="tenant-a"),
        service.rewrite(query, tenant_id="tenant-a"),
    )

    assert calls == 1
    assert {first.coalesced, second.coalesced} == {False, True}
    assert first.semantic_query == second.semantic_query


async def _case_pii_is_redacted_before_model_and_semantic_retrieval():
    observed_prompt = ""

    async def complete(**kwargs):
        nonlocal observed_prompt
        observed_prompt = kwargs["user_prompt"]
        return LLMCompletion(
            text=completion_payload("Recover the affected Edge Gateway for [EMAIL]"),
            provider="ollama",
            model="qwen3:14b",
        )

    service = QueryRewriteService(
        config=config(), completion=complete, runtime_resolver=runtime
    )
    result = await service.rewrite(
        "How do I recover EG-3000 for owner@example.com?",
        tenant_id="tenant-a",
    )

    assert "owner@example.com" not in observed_prompt
    assert "owner@example.com" not in result.semantic_query
    assert "owner@example.com" not in result.lexical_query
    assert "[EMAIL]" in result.semantic_query
    assert "EG-3000" in result.semantic_query


async def _case_cancelled_owner_releases_single_flight_waiters():
    entered = asyncio.Event()

    async def blocking_completion(**_kwargs):
        entered.set()
        await asyncio.Future()

    service = QueryRewriteService(
        config=config(query_rewrite_timeout_seconds=1.0),
        completion=blocking_completion,
        runtime_resolver=runtime,
    )
    query = "How do I recover the gateway?"
    owner = asyncio.create_task(service.rewrite(query, tenant_id="tenant-a"))
    await entered.wait()
    waiter = asyncio.create_task(service.rewrite(query, tenant_id="tenant-a"))
    await asyncio.sleep(0)
    owner.cancel()
    outcomes = await asyncio.gather(owner, waiter, return_exceptions=True)

    assert all(isinstance(outcome, asyncio.CancelledError) for outcome in outcomes)
    assert service._inflight == {}

    async def successful_completion(**_kwargs):
        return LLMCompletion(
            text=completion_payload("gateway recovery procedure"),
            provider="ollama",
            model="qwen3:4b",
        )

    service.completion = successful_completion
    recovered = await service.rewrite(query, tenant_id="tenant-a")
    assert recovered.mode == "llm"


def test_llm_rewrite_preserves_identifiers_and_uses_tenant_scoped_cache():
    asyncio.run(_case_llm_rewrite_preserves_identifiers_and_uses_tenant_scoped_cache())


def test_invented_identifier_is_removed_and_audited():
    asyncio.run(_case_invented_identifier_is_removed_and_audited())


def test_unrepairable_invalid_output_retries_and_opens_circuit():
    asyncio.run(_case_unrepairable_invalid_output_retries_and_opens_circuit())


def test_timeout_and_missing_provider_are_lossless_fallbacks():
    asyncio.run(_case_timeout_and_missing_provider_are_lossless_fallbacks())


def test_disabled_strategy_is_an_immediate_identity_rollback():
    asyncio.run(_case_disabled_strategy_is_an_immediate_identity_rollback())


def test_concurrent_identical_requests_are_single_flight():
    asyncio.run(_case_concurrent_identical_requests_are_single_flight())


def test_pii_is_redacted_before_model_and_semantic_retrieval():
    asyncio.run(_case_pii_is_redacted_before_model_and_semantic_retrieval())


def test_cancelled_owner_releases_single_flight_waiters():
    asyncio.run(_case_cancelled_owner_releases_single_flight_waiters())
