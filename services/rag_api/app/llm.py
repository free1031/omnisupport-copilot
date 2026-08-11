"""Provider-neutral LLM runtime used by the grounded generation path."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.config import settings


@dataclass(frozen=True)
class LLMRuntime:
    provider: str
    model: str
    api_key: str
    base_url: str | None
    configured: bool


@dataclass(frozen=True)
class LLMCompletion:
    text: str
    provider: str
    model: str
    request_id: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


class LLMNotConfiguredError(RuntimeError):
    pass


PROVIDER_DEFAULTS = {
    "anthropic": ("claude-sonnet-4-6", None),
    "openai": ("gpt-5-mini", None),
    "deepseek": ("deepseek-v4-flash", "https://api.deepseek.com"),
    "qwen": ("qwen-plus", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
    "kimi": ("kimi-k2.5", "https://api.moonshot.cn/v1"),
    "ollama": ("qwen3:14b", "http://host.docker.internal:11434/v1"),
}


def resolve_llm_runtime(
    *,
    provider_override: str | None = None,
    model_override: str | None = None,
    base_url_override: str | None = None,
) -> LLMRuntime:
    provider = (provider_override or settings.llm_provider).strip().lower()
    keys = {
        "anthropic": settings.anthropic_api_key,
        "openai": settings.openai_api_key,
        "deepseek": settings.deepseek_api_key,
        "qwen": settings.dashscope_api_key,
        "kimi": settings.kimi_api_key or settings.moonshot_api_key,
        "ollama": "ollama",
    }
    if provider == "auto":
        provider = next(
            (name for name in ("anthropic", "openai", "deepseek", "qwen", "kimi") if keys[name]),
            "fallback",
        )
    if provider == "fallback":
        return LLMRuntime("fallback", "none", "", None, False)
    if provider not in PROVIDER_DEFAULTS:
        raise ValueError(f"unsupported LLM_PROVIDER: {provider}")
    default_model, default_base_url = PROVIDER_DEFAULTS[provider]
    api_key = keys[provider]
    return LLMRuntime(
        provider=provider,
        model=(model_override if model_override is not None else settings.llm_model).strip()
        or default_model,
        api_key=api_key,
        base_url=(
            base_url_override if base_url_override is not None else settings.llm_base_url
        ).strip()
        or default_base_url,
        configured=bool(api_key),
    )


def resolve_query_rewrite_runtime() -> LLMRuntime:
    """Resolve the latency-optimized rewrite model independently of generation."""

    return resolve_llm_runtime(
        provider_override=settings.query_rewrite_provider.strip() or None,
        model_override=settings.query_rewrite_model.strip() or None,
        base_url_override=settings.query_rewrite_base_url.strip() or None,
    )


async def complete(
    *,
    system_prompt: str,
    user_prompt: str,
    runtime: LLMRuntime | None = None,
    max_tokens: int | None = None,
    context_tokens: int | None = None,
    temperature: float | None = None,
    timeout_seconds: float | None = None,
    max_retries: int | None = None,
    json_mode: bool = False,
    json_schema: dict[str, Any] | None = None,
) -> LLMCompletion:
    runtime = runtime or resolve_llm_runtime()
    if not runtime.configured:
        raise LLMNotConfiguredError("no external LLM provider is configured")
    if runtime.provider == "anthropic":
        return await _anthropic_completion(
            runtime,
            system_prompt,
            user_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
        )
    if runtime.provider == "ollama":
        return await _ollama_completion(
            runtime,
            system_prompt,
            user_prompt,
            max_tokens=max_tokens,
            context_tokens=context_tokens,
            temperature=temperature,
            timeout_seconds=timeout_seconds,
            json_mode=json_mode,
            json_schema=json_schema,
        )
    return await _openai_compatible_completion(
        runtime,
        system_prompt,
        user_prompt,
        max_tokens=max_tokens,
        temperature=temperature,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
        json_mode=json_mode,
        json_schema=json_schema,
    )


async def _anthropic_completion(
    runtime: LLMRuntime,
    system_prompt: str,
    user_prompt: str,
    *,
    max_tokens: int | None = None,
    temperature: float | None = None,
    timeout_seconds: float | None = None,
    max_retries: int | None = None,
) -> LLMCompletion:
    import anthropic

    client = anthropic.AsyncAnthropic(
        api_key=runtime.api_key,
        base_url=runtime.base_url,
        timeout=timeout_seconds or settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries if max_retries is None else max_retries,
    )
    response = await client.messages.create(
        model=runtime.model,
        max_tokens=max_tokens or settings.llm_max_tokens,
        temperature=settings.llm_temperature if temperature is None else temperature,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    text = "".join(
        getattr(block, "text", "")
        for block in response.content
        if getattr(block, "type", "") == "text"
    )
    if not text.strip():
        raise RuntimeError("LLM returned an empty text response")
    return LLMCompletion(
        text=text.strip(),
        provider=runtime.provider,
        model=response.model or runtime.model,
        request_id=getattr(response, "id", None),
        input_tokens=getattr(response.usage, "input_tokens", None),
        output_tokens=getattr(response.usage, "output_tokens", None),
    )


async def _ollama_completion(
    runtime: LLMRuntime,
    system_prompt: str,
    user_prompt: str,
    *,
    max_tokens: int | None = None,
    context_tokens: int | None = None,
    temperature: float | None = None,
    timeout_seconds: float | None = None,
    json_mode: bool = False,
    json_schema: dict[str, Any] | None = None,
) -> LLMCompletion:
    """Call Ollama's native API so ``think=false`` is actually enforced.

    Ollama's OpenAI-compatible endpoint accepts the extra field but currently
    still emits reasoning for thinking-capable Qwen models.  That can consume
    the entire rewrite token budget and return an empty answer.  The native
    endpoint has an explicit, tested ``think`` switch and native JSON mode.
    """

    import httpx

    base_url = (runtime.base_url or "http://host.docker.internal:11434/v1").rstrip("/")
    if base_url.endswith("/v1"):
        base_url = base_url[:-3]
    request = {
        "model": runtime.model,
        "stream": False,
        "think": False,
        "options": {
            "num_predict": max_tokens or settings.llm_max_tokens,
            "num_ctx": context_tokens or settings.llm_context_tokens,
            "temperature": settings.llm_temperature
            if temperature is None
            else temperature,
        },
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    if json_mode:
        request["format"] = json_schema or "json"
    async with httpx.AsyncClient(
        timeout=timeout_seconds or settings.llm_timeout_seconds,
    ) as client:
        response = await client.post(f"{base_url}/api/chat", json=request)
        response.raise_for_status()
        payload = response.json()

    message = payload.get("message")
    text = message.get("content") if isinstance(message, dict) else None
    if not isinstance(text, str) or not text.strip():
        raise RuntimeError("Ollama returned an empty text response")
    return LLMCompletion(
        text=text.strip(),
        provider=runtime.provider,
        model=str(payload.get("model") or runtime.model),
        request_id=response.headers.get("x-request-id"),
        input_tokens=_optional_int(payload.get("prompt_eval_count")),
        output_tokens=_optional_int(payload.get("eval_count")),
    )


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


async def _openai_compatible_completion(
    runtime: LLMRuntime,
    system_prompt: str,
    user_prompt: str,
    *,
    max_tokens: int | None = None,
    temperature: float | None = None,
    timeout_seconds: float | None = None,
    max_retries: int | None = None,
    json_mode: bool = False,
    json_schema: dict[str, Any] | None = None,
) -> LLMCompletion:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(
        api_key=runtime.api_key,
        base_url=runtime.base_url,
        timeout=timeout_seconds or settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries if max_retries is None else max_retries,
    )
    request: dict[str, Any] = {
        "model": runtime.model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": max_tokens or settings.llm_max_tokens,
        "temperature": settings.llm_temperature if temperature is None else temperature,
    }
    if json_mode and json_schema and runtime.provider == "openai":
        request["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "governed_completion",
                "strict": True,
                "schema": json_schema,
            },
        }
    elif json_mode:
        request["response_format"] = {"type": "json_object"}
    response = await client.chat.completions.create(**request)
    text = response.choices[0].message.content if response.choices else None
    if not text or not text.strip():
        raise RuntimeError("LLM returned an empty text response")
    usage = response.usage
    return LLMCompletion(
        text=text.strip(),
        provider=runtime.provider,
        model=response.model or runtime.model,
        request_id=getattr(response, "id", None),
        input_tokens=getattr(usage, "prompt_tokens", None),
        output_tokens=getattr(usage, "completion_tokens", None),
    )
