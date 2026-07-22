"""Dagster materializations for the real capstone product path.

Each asset invokes the same idempotent bootstrap stage available from the CLI.
Dagster is therefore the orchestrator of the production-shaped path, not a UI
that observes unrelated scripts.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from dagster import MaterializeResult, MetadataValue, asset

from scripts.capstone.bootstrap import run
from scripts.capstone.generate_demo_data import generate


def _root() -> Path:
    return Path(os.environ.get("WEEK15_PROJECT_ROOT", "/workspace"))


def _count() -> int:
    return int(os.environ.get("CAPSTONE_TICKET_COUNT", "240"))


@asset(
    group_name="week15_capstone",
    description="Generate privacy-safe Northstar tickets and governed document manifests.",
    tags={"layer": "source", "execution": "real"},
)
def capstone_source_pack(context) -> MaterializeResult:
    result = generate(_root(), count=_count())
    context.log.info("Generated %s capstone ticket records", result["ticket_count"])
    return MaterializeResult(
        metadata={
            "ticket_count": result["ticket_count"],
            "ticket_path": MetadataValue.path(result["tickets_path"]),
            "manifest_count": len(result["manifest_paths"]),
            "seed": result["seed"],
        }
    )


@asset(
    group_name="week15_capstone",
    deps=[capstone_source_pack],
    description="Run contract-validated ticket and document ingest into PostgreSQL and MinIO.",
    tags={"layer": "bronze_silver", "execution": "real"},
)
def capstone_operational_data(context) -> MaterializeResult:
    result = asyncio.run(run(_root(), "ingest", _count()))
    tickets = result["ingest"]["tickets"]
    documents = result["ingest"]["documents"]
    context.log.info(
        "Ingested %s tickets and %s document records",
        tickets["silver_upserted"],
        sum(item["db_inserted"] for item in documents),
    )
    return MaterializeResult(
        metadata={
            "ticket_rows": tickets["silver_upserted"],
            "bronze_new": tickets["bronze_inserted"],
            "document_rows": sum(item["db_inserted"] for item in documents),
            "document_uploads": sum(item["uploaded"] for item in documents),
        }
    )


@asset(
    group_name="week15_capstone",
    deps=[capstone_operational_data],
    description="Parse multimodal assets, enforce evidence gates, and build the pgvector index.",
    tags={"layer": "retrieval", "execution": "real"},
)
def capstone_knowledge_index(context) -> MaterializeResult:
    result = asyncio.run(run(_root(), "knowledge", _count()))["knowledge"]
    index = result["index"]
    ready = sum(1 for item in result["parse"] if item["week8_ready"])
    context.log.info("Indexed %s chunks; %s manifests passed the Week08 gate", index["embedded"], ready)
    return MaterializeResult(
        metadata={
            "parsed_manifests": len(result["parse"]),
            "week8_ready_manifests": ready,
            "embedded_chunks": index["embedded"],
            "index_errors": index["errors"],
            "index_release_id": index["index_release_id"],
        }
    )


@asset(
    group_name="week15_capstone",
    deps=[capstone_operational_data],
    description="Build governed dbt staging, intermediate, marts, and safety tests.",
    tags={"layer": "analytics", "execution": "real"},
)
def capstone_analytics_marts(context) -> MaterializeResult:
    result = asyncio.run(run(_root(), "analytics", _count()))["analytics"]
    context.log.info("dbt build completed")
    return MaterializeResult(metadata={"status": result["status"], "command": result["command"]})


@asset(
    group_name="week15_capstone",
    deps=[capstone_knowledge_index],
    description="Build and persist the versioned GraphRAG derived layer.",
    tags={"layer": "graph", "execution": "real"},
)
def capstone_graph_projection(context) -> MaterializeResult:
    result = asyncio.run(run(_root(), "graph", _count()))["graph"]
    context.log.info("Persisted graph with %s entities and %s edges", result["entities"], result["edges"])
    return MaterializeResult(metadata=result)


@asset(
    group_name="week15_capstone",
    deps=[capstone_knowledge_index, capstone_analytics_marts, capstone_graph_projection],
    description="Promote immutable data/index/prompt/graph bindings for the product runtime.",
    tags={"layer": "release", "execution": "real"},
)
def capstone_product_release(context) -> MaterializeResult:
    result = asyncio.run(run(_root(), "release", _count()))["release"]
    context.log.info("Activated governed release %s", result["release_id"])
    return MaterializeResult(metadata=result)
