import json
from pathlib import Path

import jsonschema
import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_query_rewrite_operational_assets_cover_safety_resilience_and_rollback():
    slo = yaml.safe_load((ROOT / "observability/slo/query_rewrite_slo.yaml").read_text())
    dashboard = yaml.safe_load(
        (ROOT / "observability/dashboards/query_rewrite_panels.yaml").read_text()
    )
    alerts = yaml.safe_load((ROOT / "observability/alerts/query_rewrite.yaml").read_text())

    assert slo["objectives"]["protected_term_retention_rate"]["target"] == 1.0
    assert slo["objectives"]["invented_protected_term_rate"]["target"] == 0.0
    assert slo["objectives"]["latency_p95_ms"] == {
        "target": 3000,
        "profile": "local_ollama",
    }
    assert {panel["name"] for panel in dashboard["panels"]} == {
        "query_rewrite_overview",
        "query_rewrite_resilience",
        "query_rewrite_safety",
    }
    alert_names = {rule["alert"] for rule in alerts["groups"][0]["rules"]}
    assert alert_names == {
        "QueryRewriteFallbackRatioHigh",
        "QueryRewriteCircuitOpen",
        "QueryRewriteLatencyHigh",
    }
    runbook = (ROOT / "runbooks/query-rewrite-production.md").read_text()
    assert "QUERY_REWRITE_STRATEGY=deterministic" in runbook
    assert "QUERY_REWRITE_ENABLED=false" in runbook


def test_query_rewrite_contract_rejects_raw_query_fields():
    schema = json.loads(
        (ROOT / "contracts/service/query_rewrite.schema.json").read_text()
    )
    payload = {
        "mode": "llm",
        "provider": "ollama",
        "model": "qwen3:4b",
        "prompt_release_id": "query-rewrite-v1",
        "rewrite_reasons": ["intent_clarified"],
        "fallback_reason": None,
        "original_query_sha256": "sha256:" + "a" * 64,
        "semantic_query_sha256": "sha256:" + "b" * 64,
        "original_query_length": 20,
        "semantic_query_length": 30,
        "lexical_term_count": 1,
        "hyde_used": False,
        "attempts": 1,
        "safety_repairs": [],
        "cache_hit": False,
        "coalesced": False,
        "circuit_state": "closed",
        "latency_ms": 3.2,
        "semantic_query": "raw content must not cross this contract",
    }
    errors = list(jsonschema.Draft202012Validator(schema).iter_errors(payload))
    assert any(error.validator == "additionalProperties" for error in errors)
