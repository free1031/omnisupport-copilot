"""Week10 fallback path demo.

Run from the project root:

    python demos/e2e_fallback_path.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.copilot import ControlledAgent
from tools.fallback import FallbackChain


def _payload() -> dict:
    return {
        "query": "How do I recover a Northstar Workspace connector after a failed upgrade?",
        "product_line": "northstar_workspace",
        "modalities": ["document"],
        "top_k": 3,
        "min_score": 0.6,
        "trace_id": "trace_week10_fallback_demo",
    }


def _primary(_payload: dict) -> dict:
    raise RuntimeError("vector index timeout")


def _lexical_cache(payload: dict) -> dict:
    return {
        "results": [
            {
                "chunk_id": "chk_week08_cache_001",
                "content": "Restart the connector, verify credentials, and replay the recovery job.",
                "score": 0.67,
                "evidence_anchor": {
                    "source_id": "workspace_recovery_manual",
                    "source_url": "s3://omni-raw-documents/workspace/recovery/manual.pdf",
                    "page_no": 3,
                    "section_path": "Recovery > Connector restart",
                    "doc_version": "v1",
                },
            }
        ],
        "trace_id": payload["trace_id"],
        "release_id": "dev-local",
    }


async def run_demo() -> dict:
    agent = ControlledAgent()
    chain = FallbackChain(
        steps=[
            ("primary_vector_search", _primary),
            ("lexical_cache", _lexical_cache),
        ],
        graceful_response={
            "results": [],
            "trace_id": "trace_week10_fallback_demo",
            "release_id": "dev-local",
            "message": "Search is temporarily unavailable. A human support agent has been notified.",
        },
    )
    result = await agent.invoke(
        "knowledge_search",
        _payload(),
        actor_role="support_agent",
        executor=chain,
    )
    assert result["fallback_level"] == "lexical_cache"
    return {
        "answer": result,
        "lineage_events": [event.to_dict() for event in agent.lineage_events],
    }


if __name__ == "__main__":
    print(json.dumps(asyncio.run(run_demo()), ensure_ascii=False, indent=2))
