import asyncio
import json
from pathlib import Path

import jsonschema
import pytest

from evals.week13.ab import compare_by_category, load_paired_cases
from pipelines.graph.build import build_graph, build_graph_from_jsonl, load_chunks
from pipelines.graph.models import SourceChunk
from services.graph.classifier import classify_query
from services.graph.models import (
    GraphCommunityRecord,
    GraphEntityRecord,
    GraphEvidenceChunk,
    GraphPathRecord,
    GraphRelationRecord,
)
from services.graph.retrieval import GraphRetriever
from services.graph.serialize import serialize_graph_context
from services.graph.store import InMemoryGraphStore

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data/week13/graph_source_chunks_v1.jsonl"
AB_CASES = ROOT / "evals/fixtures/week13/graphrag_ab_cases_v1.jsonl"


def test_week13_build_is_deterministic_and_aliases_are_merged():
    first = build_graph_from_jsonl(SOURCE, graph_release_id="graph-week13-test-v1")
    second = build_graph_from_jsonl(SOURCE, graph_release_id="graph-week13-test-v1")

    assert first.to_dict() == second.to_dict()
    workspace = [
        item for item in first.entities
        if item.entity_type == "PRODUCT" and item.canonical_name == "Northstar Workspace"
    ]
    assert len(workspace) == 1
    assert {"Workspace", "Northstar Workspace"}.issubset(workspace[0].aliases)
    assert len(first.communities) == 2
    assert not first.quarantined
    assert not first.rejected


def test_week13_classifier_routes_only_graph_main_field_queries():
    assert classify_query("怎么重置密码").mode == "hybrid"
    assert classify_query("SSO login loop 的原因和解决方案是什么").mode == "graph_local"
    assert classify_query("过去半年所有故障的共性是什么").mode == "graph_global"
    assert classify_query("哪些问题导致哪些症状并由什么方案解决").mode == "graph_multihop"


def test_week13_local_global_multihop_and_drift_share_evidence():
    result = build_graph_from_jsonl(SOURCE, graph_release_id="graph-week13-test-v1")
    chunks = load_chunks(SOURCE)
    store = InMemoryGraphStore(
        entities=[
            GraphEntityRecord(
                item.entity_id, item.entity_type, item.canonical_name,
                item.confidence, tuple(sorted(item.evidence_ids)),
                item.product_line, item.visibility_scope,
            )
            for item in result.entities
        ],
        relations=[
            GraphRelationRecord(
                item.edge_id, item.relation_type, item.source_entity_id,
                item.target_entity_id, item.confidence, tuple(sorted(item.evidence_ids)),
            )
            for item in result.edges
        ],
        communities=[
            GraphCommunityRecord(
                item.community_id, item.summary, len(item.member_entity_ids),
                item.evidence_ids, 1.0, item.product_lines, item.visibility_scopes,
            )
            for item in result.communities
        ],
        evidence=[
            GraphEvidenceChunk(
                chunk_id=item.chunk_id,
                evidence_id=item.evidence_id,
                doc_id=item.doc_id,
                source_id=item.source_id,
                content=item.content,
                section_path=f"Week13 source > {item.chunk_id}",
                final_score=0.9,
                product_line=item.product_line,
                visibility_scope=item.visibility_scope,
            )
            for item in chunks
        ],
    )
    retriever = GraphRetriever(store)

    async def run_modes():
        local = await retriever.retrieve(
            "Northstar Workspace SSO login loop 的原因和解决方案",
            mode="graph_local", graph_release_id=result.graph_release_id,
        )
        global_result = await retriever.retrieve(
            "所有产品故障的共性是什么",
            mode="graph_global", graph_release_id=result.graph_release_id,
        )
        multihop = await retriever.retrieve(
            "Northstar Workspace 的问题到症状和解决方案的关系链",
            mode="graph_multihop", graph_release_id=result.graph_release_id, max_hops=3,
        )
        drift = await retriever.retrieve(
            "Northstar Workspace 故障的原因和总体共性",
            mode="graph_drift", graph_release_id=result.graph_release_id, max_hops=2,
        )
        return local, global_result, multihop, drift

    local, global_result, multihop, drift = asyncio.run(run_modes())
    assert local.paths and local.chunks
    assert global_result.communities and global_result.chunks
    assert any(len(path.relations) >= 2 for path in multihop.paths)
    assert drift.paths and drift.communities and drift.serialized_context
    assert all(item.evidence_id.startswith("w13-ev-") for item in drift.chunks)


def test_week13_scope_is_part_of_entity_identity():
    base = load_chunks(SOURCE)[0]
    restricted = SourceChunk(
        chunk_id="restricted-chunk",
        evidence_id="restricted-evidence",
        doc_id="restricted-doc",
        source_id="restricted-source",
        content=base.content,
        data_release_id=base.data_release_id,
        product_line=base.product_line,
        visibility_scope="restricted",
        annotations=base.annotations,
    )
    result = build_graph([base, restricted], graph_release_id="graph-scope-test")
    products = [item for item in result.entities if item.entity_type == "PRODUCT"]

    assert len(products) == 2
    assert len({item.entity_id for item in products}) == 2
    assert {item.visibility_scope for item in products} == {"internal", "restricted"}


def test_week13_retrieval_rejects_non_active_release():
    store = InMemoryGraphStore(
        entities=[],
        relations=[],
        communities=[],
        evidence=[],
        release_status="deprecated",
    )

    with pytest.raises(ValueError, match="is not active: deprecated"):
        asyncio.run(
            GraphRetriever(store).retrieve(
                "所有故障的共性",
                mode="graph_global",
                graph_release_id="graph-retired-v1",
            )
        )


def test_week13_serialized_context_only_claims_allowed_evidence():
    source = GraphEntityRecord("entity-source", "ISSUE", "Login loop", 1.0)
    target = GraphEntityRecord("entity-target", "RESOLUTION", "Rotate token", 1.0)
    relation = GraphRelationRecord(
        "edge-1",
        "RESOLVED_BY",
        source.entity_id,
        target.entity_id,
        1.0,
        ("evidence-allowed",),
    )
    path = GraphPathRecord((source, target), (relation,), 1.0)

    included = serialize_graph_context(
        [path], [], allowed_evidence_ids={"evidence-allowed"}
    )
    excluded = serialize_graph_context(
        [path], [], allowed_evidence_ids={"evidence-other"}
    )

    assert "evidence-allowed" in included
    assert excluded == ""


def test_week13_graph_path_prefers_relation_evidence():
    entity = GraphEntityRecord(
        "entity-1", "ISSUE", "Login loop", 1.0, ("evidence-broad",)
    )
    relation = GraphRelationRecord(
        "edge-1", "RESOLVED_BY", "entity-1", "entity-2", 1.0, ("evidence-edge",)
    )
    path = GraphPathRecord((entity,), (relation,), 1.0)

    assert path.evidence_ids == ("evidence-edge",)


def test_week13_ab_gate_routes_by_category_instead_of_overall_average():
    report = compare_by_category(
        load_paired_cases(AB_CASES),
        vector_release_id="index-week08-dev",
        graph_release_id="graph-week13-test-v1",
    )
    schema = json.loads(
        (ROOT / "contracts/graph/graphrag_ab_report.schema.json").read_text(encoding="utf-8")
    )

    jsonschema.Draft202012Validator(schema).validate(report)
    assert report["gate"]["status"] == "pass"
    assert report["routing_policy"] == {
        "factual": "hybrid",
        "global": "graph_global",
        "local": "graph_local",
        "multi_hop": "graph_multihop",
    }
