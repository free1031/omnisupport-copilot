import json
from pathlib import Path

import jsonschema
import pytest
from referencing import Registry, Resource

PROJECT_ROOT = Path(__file__).parent.parent.parent
SERVICE_CONTRACTS = PROJECT_ROOT / "contracts" / "service"
RELEASE_CONTRACTS = PROJECT_ROOT / "contracts" / "release"
FIXTURES = Path(__file__).parent / "fixtures" / "week08"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text())


def validator(schema_name: str) -> jsonschema.Draft202012Validator:
    schema = load_json(SERVICE_CONTRACTS / schema_name)
    referenced = [
        load_json(SERVICE_CONTRACTS / "citation.schema.json"),
        load_json(SERVICE_CONTRACTS / "retrieval_debug.schema.json"),
        load_json(SERVICE_CONTRACTS / "query_rewrite.schema.json"),
    ]
    registry = Registry().with_resources(
        (document["$id"], Resource.from_contents(document)) for document in referenced
    )
    return jsonschema.Draft202012Validator(
        schema,
        registry=registry,
    )


def test_rag_request_fixture_valid():
    validator("rag_request.schema.json").validate(load_json(FIXTURES / "rag_request.valid.json"))


@pytest.mark.parametrize(
    "fixture_name",
    ["rag_response.valid.json", "rag_response.no_answer.json"],
)
def test_rag_response_fixtures_valid(fixture_name: str):
    validator("rag_response.schema.json").validate(load_json(FIXTURES / fixture_name))


def test_rag_response_requires_citations_and_release_ids():
    payload = load_json(FIXTURES / "rag_response.valid.json")
    payload.pop("citations")
    with pytest.raises(jsonschema.ValidationError):
        validator("rag_response.schema.json").validate(payload)


def test_index_manifest_fixture_valid():
    schema = load_json(RELEASE_CONTRACTS / "index_manifest.schema.json")
    jsonschema.Draft202012Validator(schema).validate(
        load_json(FIXTURES / "index_manifest.valid.json")
    )


def test_no_answer_has_abstain_reason_and_no_evidence():
    payload = load_json(FIXTURES / "rag_response.no_answer.json")
    assert payload["abstain_reason"]
    assert payload["citations"] == []
    assert payload["evidence_ids"] == []


def test_rag_response_accepts_privacy_safe_query_rewrite_debug():
    payload = load_json(FIXTURES / "rag_response.valid.json")
    payload["query_rewrite_debug"] = {
        "mode": "llm",
        "provider": "ollama",
        "model": "qwen3:4b",
        "prompt_release_id": "query-rewrite-v1",
        "rewrite_reasons": ["intent_clarified"],
        "fallback_reason": None,
        "original_query_sha256": "sha256:" + "a" * 64,
        "semantic_query_sha256": "sha256:" + "b" * 64,
        "original_query_length": 40,
        "semantic_query_length": 55,
        "lexical_term_count": 2,
        "hyde_used": False,
        "attempts": 1,
        "safety_repairs": [],
        "cache_hit": False,
        "coalesced": False,
        "circuit_state": "closed",
        "latency_ms": 12.4,
    }

    validator("rag_response.schema.json").validate(payload)
    assert "semantic_query" not in payload["query_rewrite_debug"]
