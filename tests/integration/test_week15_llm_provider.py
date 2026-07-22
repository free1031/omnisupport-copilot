# ruff: noqa: E402 - RAG service path is installed before app imports

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/rag_api"))

from app.config import settings
from app.llm import resolve_llm_runtime


@pytest.mark.parametrize(
    ("provider", "key_field", "expected_model", "expected_base_url"),
    [
        ("anthropic", "anthropic_api_key", "claude-sonnet-4-6", None),
        ("openai", "openai_api_key", "gpt-5-mini", None),
        ("deepseek", "deepseek_api_key", "deepseek-v4-flash", "https://api.deepseek.com"),
        (
            "qwen",
            "dashscope_api_key",
            "qwen-plus",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        ),
        ("kimi", "kimi_api_key", "kimi-k2.5", "https://api.moonshot.cn/v1"),
        (
            "ollama",
            None,
            "qwen3:14b",
            "http://host.docker.internal:11434/v1",
        ),
    ],
)
def test_llm_provider_is_selected_only_by_configuration(
    monkeypatch, provider, key_field, expected_model, expected_base_url
):
    monkeypatch.setattr(settings, "llm_provider", provider)
    monkeypatch.setattr(settings, "llm_model", "")
    monkeypatch.setattr(settings, "llm_base_url", "")
    if key_field:
        monkeypatch.setattr(settings, key_field, "test-key")

    runtime = resolve_llm_runtime()

    assert runtime.configured
    assert runtime.provider == provider
    assert runtime.model == expected_model
    assert runtime.base_url == expected_base_url


def test_llm_model_and_base_url_can_be_overridden(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "deepseek")
    monkeypatch.setattr(settings, "deepseek_api_key", "test-key")
    monkeypatch.setattr(settings, "llm_model", "enterprise-model-v7")
    monkeypatch.setattr(settings, "llm_base_url", "https://llm-gateway.internal/v1")

    runtime = resolve_llm_runtime()

    assert runtime.model == "enterprise-model-v7"
    assert runtime.base_url == "https://llm-gateway.internal/v1"
