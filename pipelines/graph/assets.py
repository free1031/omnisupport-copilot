"""Dagster assets for the Week13 graph derived layer."""

from __future__ import annotations

import os
from pathlib import Path

from dagster import asset

from pipelines.graph.build import build_graph_from_jsonl


@asset(group_name="week13_graphrag")
def week13_graph_release(context) -> dict:
    release = {
        "graph_release_id": os.getenv("WEEK13_GRAPH_RELEASE_ID", "graph-week13-dev-v1"),
        "source_path": os.getenv(
            "WEEK13_GRAPH_SOURCE_PATH", "data/week13/graph_source_chunks_v1.jsonl"
        ),
        "schema_version": "graph_schema_v1",
    }
    context.add_output_metadata(release)
    return release


@asset(group_name="week13_graphrag", deps=[week13_graph_release])
def week13_graph_build(context) -> dict:
    graph_release_id = os.getenv("WEEK13_GRAPH_RELEASE_ID", "graph-week13-dev-v1")
    source_path = Path(
        os.getenv("WEEK13_GRAPH_SOURCE_PATH", "data/week13/graph_source_chunks_v1.jsonl")
    )
    result = build_graph_from_jsonl(source_path, graph_release_id=graph_release_id)
    metadata = {
        "graph_release_id": graph_release_id,
        "source_chunk_count": result.source_chunk_count,
        "entity_count": len(result.entities),
        "edge_count": len(result.edges),
        "community_count": len(result.communities),
        "status": result.status,
    }
    context.add_output_metadata(metadata)
    return metadata
