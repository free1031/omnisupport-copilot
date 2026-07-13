import json
from pathlib import Path

import jsonschema
import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_week12_incident_fixture_matches_contract():
    schema = json.loads(
        (ROOT / "contracts/observability/incident.schema.json").read_text(encoding="utf-8")
    )
    incident = json.loads(
        (ROOT / "tests/fixtures/week12/incident_bad_citation.json").read_text(encoding="utf-8")
    )
    jsonschema.Draft202012Validator(schema).validate(incident)


def test_week12_slo_and_dashboard_cover_course_control_planes():
    policy = yaml.safe_load((ROOT / "observability/slo/week12_slo.yaml").read_text())
    dashboard = yaml.safe_load(
        (ROOT / "observability/dashboards/week12_panels.yaml").read_text()
    )
    alerts = yaml.safe_load((ROOT / "observability/alerts/burn_rate.yaml").read_text())

    assert set(policy["objectives"]) == {
        "availability",
        "latency_p99_ms",
        "citation_coverage",
        "cost_per_query_usd",
        "pii_leak_count",
    }
    assert [panel["name"] for panel in dashboard["panels"]] == [
        "overview",
        "quality",
        "performance",
        "cost",
        "errors",
    ]
    alert_names = {item["alert"] for item in alerts["groups"][0]["rules"]}
    assert "CopilotAvailabilityFastBurn" in alert_names
    assert "CopilotPIILeak" in alert_names


def test_week12_span_names_exist_in_runtime_paths():
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in [
            ROOT / "services/rag_api/app/routers/rag.py",
            ROOT / "services/rag_api/app/retrieval.py",
            ROOT / "agent/copilot.py",
            ROOT / "tools/fallback.py",
        ]
    )
    required = {
        "rag.query",
        "rag.intent.route",
        "rag.retrieve.hybrid",
        "rag.retrieve.vector",
        "rag.retrieve.lexical",
        "rag.retrieve.rrf",
        "rag.rerank.cross",
        "llm.generate",
        "rag.audit.persist",
        "agent.invoke",
        "hitl.wait",
        "tool.idempotency.check",
        "tool.fallback.attempt",
        "agent.lineage.persist",
    }
    assert all(name in source for name in required)
