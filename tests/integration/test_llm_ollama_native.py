# ruff: noqa: E402 - service path is installed before app imports

import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "services" / "rag_api"))

from app.llm import LLMRuntime, complete


def test_ollama_uses_native_api_with_thinking_disabled(monkeypatch):
    observed = {}

    class FakeResponse:
        headers = {"x-request-id": "ollama-request-1"}

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "model": "qwen3:4b",
                "message": {"content": '{"semantic_query":"gateway recovery"}'},
                "prompt_eval_count": 21,
                "eval_count": 7,
            }

    class FakeClient:
        def __init__(self, *, timeout):
            observed["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, url, *, json):
            observed["url"] = url
            observed["payload"] = json
            return FakeResponse()

    monkeypatch.setattr("httpx.AsyncClient", FakeClient)
    runtime = LLMRuntime(
        provider="ollama",
        model="qwen3:4b",
        api_key="ollama",
        base_url="http://localhost:11434/v1",
        configured=True,
    )
    schema = {
        "type": "object",
        "properties": {"semantic_query": {"type": "string"}},
        "required": ["semantic_query"],
        "additionalProperties": False,
    }

    result = asyncio.run(
        complete(
            system_prompt="return json",
            user_prompt="recover gateway",
            runtime=runtime,
            max_tokens=96,
            context_tokens=2048,
            temperature=0,
            timeout_seconds=4,
            json_mode=True,
            json_schema=schema,
        )
    )

    assert observed["url"] == "http://localhost:11434/api/chat"
    assert observed["timeout"] == 4
    assert observed["payload"]["think"] is False
    assert observed["payload"]["format"] == schema
    assert observed["payload"]["options"] == {
        "num_predict": 96,
        "num_ctx": 2048,
        "temperature": 0,
    }
    assert result.text == '{"semantic_query":"gateway recovery"}'
    assert result.input_tokens == 21
    assert result.output_tokens == 7
    assert result.request_id == "ollama-request-1"
