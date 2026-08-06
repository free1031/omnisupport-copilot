# ruff: noqa: E402 - service path is installed before app imports

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import jsonschema

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "rag_api"))

from app.query_rewrite import QueryRewriteService

from evals.query_rewrite.run_eval import evaluate_cases, load_cases


def test_deterministic_query_rewrite_release_gate_passes_contract():
    cases = load_cases(ROOT / "evals/fixtures/query_rewrite_cases_v1.jsonl")
    config = SimpleNamespace(
        query_rewrite_enabled=True,
        query_rewrite_strategy="deterministic",
        query_rewrite_prompt_release_id="query-rewrite-test-v1",
        query_rewrite_timeout_seconds=1.0,
        query_rewrite_max_attempts=1,
        query_rewrite_max_output_chars=512,
        query_rewrite_max_tokens=128,
        query_rewrite_context_tokens=2048,
        query_rewrite_temperature=0.0,
        query_rewrite_hyde_enabled=False,
        query_rewrite_redact_pii=True,
        query_rewrite_cache_ttl_seconds=0.0,
        query_rewrite_cache_max_entries=0,
        query_rewrite_circuit_failure_threshold=2,
        query_rewrite_circuit_recovery_seconds=30.0,
    )
    report = asyncio.run(
        evaluate_cases(
            cases,
            QueryRewriteService(config=config),
            strategy="deterministic",
        )
    )

    schema = json.loads(
        (ROOT / "contracts/evals/query_rewrite_eval_report.schema.json").read_text()
    )
    jsonschema.Draft202012Validator(schema).validate(report)
    assert report["gate"]["status"] == "pass"
    assert report["metrics"]["protected_term_retention_rate"] == 1.0
    assert report["metrics"]["invented_protected_term_rate"] == 0.0
    assert all("query" not in row for row in report["cases"])
