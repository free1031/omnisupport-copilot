import asyncio
import importlib
import json
import sys
from pathlib import Path

from observability.runtime.privacy import hash_text, safe_preview
from observability.week12.badcase import prepare_regression_assets
from observability.week12.incident import load_incident, render_postmortem
from observability.week12.slo import evaluate_slo, load_observations, load_policy

ROOT = Path(__file__).resolve().parents[2]


def test_trace_privacy_helpers_redact_pii_and_keep_stable_hashes():
    source = "phone=13800138000 email=owner@example.com token=secret-value"
    preview = safe_preview(source)
    assert "13800138000" not in preview
    assert "owner@example.com" not in preview
    assert "secret-value" not in preview
    assert preview == safe_preview(source)
    assert hash_text(source).startswith("sha256:")
    assert len(hash_text(source)) == 71


def test_slo_window_produces_actionable_alert_context():
    observations = load_observations(ROOT / "tests/fixtures/week12/telemetry_window_bad.jsonl")
    policy = load_policy(ROOT / "observability/slo/week12_slo.yaml")
    report = evaluate_slo(observations, policy)
    alert_names = {item["name"] for item in report["alerts"]}
    assert report["window"]["sample_count"] == 10
    assert "copilot_availability_burn_fast" in alert_names
    availability = next(
        item for item in report["alerts"] if item["name"] == "copilot_availability_burn_fast"
    )
    assert availability["sample_trace_ids"]
    assert "TOOL_TIMEOUT:1" in availability["top_error_types"]


def test_incident_becomes_non_mutating_week11_regression_assets(tmp_path):
    incident = load_incident(
        ROOT / "tests/fixtures/week12/incident_bad_citation.json",
        ROOT / "contracts/observability/incident.schema.json",
    )
    original = (ROOT / "evals/sets/rag_qa_golden_v2_3_0.jsonl").read_bytes()
    eval_path, predictions_path, sample = prepare_regression_assets(
        incident=incident,
        base_eval_set=ROOT / "evals/sets/rag_qa_golden_v2_3_0.jsonl",
        base_predictions=ROOT / "evals/fixtures/week11/rag_predictions_good.jsonl",
        output_dir=tmp_path,
    )
    assert (ROOT / "evals/sets/rag_qa_golden_v2_3_0.jsonl").read_bytes() == original
    assert sample["metadata"]["incident_id"] == incident["incident_id"]
    assert sample["metadata"]["trace_id"] == incident["trace_id"]
    assert sample["metadata"]["actual_bad_answer"] == incident["actual_bad_answer"]
    assert sample["case_id"] in eval_path.read_text(encoding="utf-8")
    assert sample["case_id"] in predictions_path.read_text(encoding="utf-8")

    postmortem = render_postmortem(incident)
    assert incident["trace_id"] in postmortem
    assert "Week11 regression" in postmortem


def test_week12_fixture_has_no_raw_secrets():
    payload = json.loads(
        (ROOT / "tests/fixtures/week12/incident_bad_citation.json").read_text(encoding="utf-8")
    )
    assert "password" not in json.dumps(payload).lower()


def test_hybrid_retrieval_does_not_overlap_one_asyncpg_connection(monkeypatch):
    rag_path = str(ROOT / "services/rag_api")
    saved_app_modules = {
        name: module
        for name, module in sys.modules.items()
        if name == "app" or name.startswith("app.")
    }
    for name in saved_app_modules:
        sys.modules.pop(name, None)
    sys.path.insert(0, rag_path)
    try:
        retrieval = importlib.import_module("app.retrieval")
    finally:
        sys.path.remove(rag_path)

    active = False

    async def guarded_vector(*_args, **_kwargs):
        nonlocal active
        assert not active
        active = True
        await asyncio.sleep(0)
        active = False
        return []

    async def guarded_fts(*_args, **_kwargs):
        nonlocal active
        assert not active
        active = True
        await asyncio.sleep(0)
        active = False
        return []

    try:
        monkeypatch.setattr(retrieval, "vector_search", guarded_vector)
        monkeypatch.setattr(retrieval, "fts_search", guarded_fts)
        result = asyncio.run(retrieval.hybrid_retrieve(object(), "query", rerank=False))
    finally:
        for name in list(sys.modules):
            if name == "app" or name.startswith("app."):
                sys.modules.pop(name, None)
        sys.modules.update(saved_app_modules)
    assert result == []
