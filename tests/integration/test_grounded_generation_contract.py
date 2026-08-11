# ruff: noqa: E402 - service path is installed before app imports

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "services" / "rag_api"))

from app import generator
from app.llm import LLMCompletion, LLMRuntime


def _chunk():
    return SimpleNamespace(
        chunk_id="chunk-1",
        content="先核对身份提供商证书指纹，再验证元数据。",
        section_path="恢复步骤",
        page_no=None,
        source_url="/knowledge/recovery.html",
        final_score=0.8,
    )


def test_ollama_grounded_generation_uses_structured_final_answer(monkeypatch):
    observed = {}
    runtime = LLMRuntime(
        provider="ollama",
        model="qwen3:4b",
        api_key="ollama",
        base_url="http://localhost:11434/v1",
        configured=True,
    )

    async def fake_complete(**kwargs):
        observed.update(kwargs)
        return LLMCompletion(
            text=json.dumps({"answer": "1. 核对证书指纹。[来源1]"}, ensure_ascii=False),
            provider="ollama",
            model="qwen3:4b",
        )

    monkeypatch.setattr(generator, "resolve_llm_runtime", lambda: runtime)
    monkeypatch.setattr(generator, "complete", fake_complete)
    answer, confidence, abstain, metadata = asyncio.run(
        generator.generate_grounded_answer(
            question="如何恢复管理员访问？",
            chunks=[_chunk()],
            prompt_release_id="prompt-test",
        )
    )

    assert answer == "1. 核对证书指纹。[来源1]"
    assert confidence == 0.8
    assert abstain is None
    assert metadata["mode"] == "llm"
    assert observed["runtime"] == runtime
    assert observed["json_mode"] is True
    assert observed["json_schema"] == generator.GROUNDED_ANSWER_SCHEMA
