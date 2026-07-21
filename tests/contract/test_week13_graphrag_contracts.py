import json
from pathlib import Path

import jsonschema
import pytest

from pipelines.graph.build import build_graph, build_graph_from_jsonl
from pipelines.graph.models import SourceChunk
from pipelines.graph.schema import load_graph_schema

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data/week13/graph_source_chunks_v1.jsonl"


def test_week13_graph_schema_is_typed_and_bounded():
    schema = load_graph_schema(ROOT / "pipelines/graph/schema.yaml")

    assert {"PRODUCT", "ISSUE", "SYMPTOM", "RESOLUTION", "VERSION"}.issubset(
        schema.entity_types
    )
    assert {"HAS_ISSUE", "HAS_SYMPTOM", "RESOLVED_BY"}.issubset(schema.relation_types)
    assert schema.max_query_hops == 3
    assert schema.quality_gate["require_evidence_for_edges"] is True


def test_week13_build_report_matches_contract_and_keeps_evidence():
    report = build_graph_from_jsonl(SOURCE, graph_release_id="graph-week13-contract-v1").to_dict()
    contract = json.loads(
        (ROOT / "contracts/graph/graph_build_report.schema.json").read_text(encoding="utf-8")
    )

    jsonschema.Draft202012Validator(contract).validate(report)
    assert report["status"] == "pass"
    assert report["graph_schema_version"] == "graph_schema_v1"
    assert all(edge["evidence_ids"] for edge in report["edges"])
    assert all(edge["graph_release_id"] == "graph-week13-contract-v1" for edge in report["edges"])


def test_week13_release_manifest_binds_graph_version():
    schema = json.loads(
        (ROOT / "contracts/release/release_manifest_schema.json").read_text(encoding="utf-8")
    )
    example = json.loads(
        (ROOT / "contracts/release/release_manifest_example.json").read_text(encoding="utf-8")
    )

    jsonschema.Draft202012Validator(schema).validate(example)
    assert example["graph_release_id"]
    assert example["graph"]["category_routes"]["factual"] == "hybrid"


def test_week13_unknown_relation_is_rejected_instead_of_persisted():
    chunk = SourceChunk(
        chunk_id="bad-chunk",
        evidence_id="bad-evidence",
        doc_id="bad-doc",
        source_id="bad-source",
        content="invalid graph fixture",
        data_release_id="data-test",
        annotations={
            "entities": [
                {"type": "PRODUCT", "name": "Northstar Workspace"},
                {"type": "ISSUE", "name": "Unknown issue"},
            ],
            "relations": [
                {
                    "type": "INVENTED_RELATION",
                    "source_type": "PRODUCT",
                    "source": "Northstar Workspace",
                    "target_type": "ISSUE",
                    "target": "Unknown issue",
                }
            ],
        },
    )

    result = build_graph([chunk], graph_release_id="graph-invalid-test")
    assert result.status == "warn"
    assert result.rejected
    assert result.edges == []


def test_week13_quarantine_blocks_a_pass_build_status():
    result = build_graph_from_jsonl(SOURCE, graph_release_id="graph-quarantine-test")
    result.quarantined.append({"kind": "entity", "reason": "manual_review_required"})

    assert result.status == "warn"


def test_week13_non_finite_confidence_is_rejected_before_persistence():
    chunk = SourceChunk(
        chunk_id="invalid-confidence-chunk",
        evidence_id="invalid-confidence-evidence",
        doc_id="invalid-confidence-doc",
        source_id="invalid-confidence-source",
        content="invalid confidence fixture",
        data_release_id="data-test",
        annotations={
            "entities": [
                {"type": "PRODUCT", "name": "Northstar Workspace", "confidence": "nan"}
            ]
        },
    )

    result = build_graph([chunk], graph_release_id="graph-invalid-confidence")

    assert result.status == "warn"
    assert result.entities == []
    assert result.rejected[0]["reason"].startswith("invalid_entity")


def test_week13_build_rejects_empty_duplicate_and_mixed_release_inputs():
    source = SourceChunk(
        chunk_id="source-chunk",
        evidence_id="source-evidence",
        doc_id="source-doc",
        source_id="source",
        content="Product: Workspace\nIssue: Login loop",
        data_release_id="data-v1",
    )

    with pytest.raises(ValueError, match="at least one source chunk"):
        build_graph([], graph_release_id="graph-empty")
    with pytest.raises(ValueError, match="duplicate chunk_id"):
        build_graph([source, source], graph_release_id="graph-duplicate")
    with pytest.raises(ValueError, match="exactly one data_release_id"):
        build_graph(
            [
                source,
                SourceChunk(
                    chunk_id="other-chunk",
                    evidence_id="other-evidence",
                    doc_id="other-doc",
                    source_id="other",
                    content=source.content,
                    data_release_id="data-v2",
                ),
            ],
            graph_release_id="graph-mixed-release",
        )
