"""Provider-neutral LLM runtime used by the grounded generation path."""

from __future__ import annotations

from dataclasses import dataclass

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


def resolve_llm_runtime() -> LLMRuntime:
    provider = settings.llm_provider.strip().lower()
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
        model=settings.llm_model.strip() or default_model,
        api_key=api_key,
        base_url=settings.llm_base_url.strip() or default_base_url,
        configured=bool(api_key),
    )


async def complete(*, system_prompt: str, user_prompt: str) -> LLMCompletion:
    runtime = resolve_llm_runtime()
    if not runtime.configured:
        raise LLMNotConfiguredError("no external LLM provider is configured")
    if runtime.provider == "anthropic":
        return await _anthropic_completion(runtime, system_prompt, user_prompt)
    return await _openai_compatible_completion(runtime, system_prompt, user_prompt)


async def _anthropic_completion(
    runtime: LLMRuntime, system_prompt: str, user_prompt: str
) -> LLMCompletion:
    import anthropic

    kwargs = {
        "api_key": runtime.api_key,
        "timeout": settings.llm_timeout_seconds,
        "max_retries": settings.llm_max_retries,
    }
    if runtime.base_url:
        kwargs["base_url"] = runtime.base_url
    client = anthropic.AsyncAnthropic(**kwargs)
    response = await client.messages.create(
        model=runtime.model,
        max_tokens=settings.llm_max_tokens,
        temperature=settings.llm_temperature,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    text = "".join(block.text for block in response.content if getattr(block, "type", "") == "text")
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


async def _openai_compatible_completion(
    runtime: LLMRuntime, system_prompt: str, user_prompt: str
) -> LLMCompletion:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(
        api_key=runtime.api_key,
        base_url=runtime.base_url,
        timeout=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
    )
    request = {
        "model": runtime.model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": settings.llm_max_tokens,
        "temperature": settings.llm_temperature,
    }
    if runtime.provider == "ollama":
        request["extra_body"] = {"think": False}
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
