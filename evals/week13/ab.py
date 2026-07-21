"""Per-category GraphRAG vs hybrid comparison and release decision."""

from __future__ import annotations

import json
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any

SUPPORTED_CATEGORIES = {"factual", "local", "global", "multi_hop"}


def load_paired_cases(path: Path) -> list[dict[str, Any]]:
    cases = []
    seen = set()
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        data = json.loads(line)
        required = {
            "case_id", "category", "vector_quality", "graph_quality",
            "vector_cost_usd", "graph_cost_usd",
        }
        missing = required - set(data)
        if missing:
            raise ValueError(f"{path}:{line_no}: missing {', '.join(sorted(missing))}")
        if data["case_id"] in seen:
            raise ValueError(f"{path}:{line_no}: duplicate case_id {data['case_id']}")
        if data["category"] not in SUPPORTED_CATEGORIES:
            raise ValueError(f"{path}:{line_no}: unsupported category {data['category']}")
        for field in ("vector_quality", "graph_quality"):
            if not 0 <= float(data[field]) <= 1:
                raise ValueError(f"{path}:{line_no}: {field} must be in [0, 1]")
        seen.add(data["case_id"])
        cases.append(data)
    return cases


def compare_by_category(
    cases: list[dict[str, Any]],
    *,
    vector_release_id: str,
    graph_release_id: str,
    min_samples: int = 2,
    min_graph_delta: float = 0.08,
    max_graph_cost_ratio: float = 5.0,
) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for case in cases:
        grouped[case["category"]].append(case)
    categories = {}
    routing_policy = {}
    blockers = []
    for category in sorted(SUPPORTED_CATEGORIES):
        rows = grouped.get(category, [])
        if not rows:
            blockers.append(f"missing_category:{category}")
            continue
        vector_quality = _avg([float(row["vector_quality"]) for row in rows])
        graph_quality = _avg([float(row["graph_quality"]) for row in rows])
        delta = graph_quality - vector_quality
        vector_cost = _avg([float(row["vector_cost_usd"]) for row in rows])
        graph_cost = _avg([float(row["graph_cost_usd"]) for row in rows])
        cost_ratio = graph_cost / max(vector_cost, 1e-9)
        if len(rows) < min_samples:
            decision = "need_more_data"
            blockers.append(f"insufficient_samples:{category}:{len(rows)}<{min_samples}")
        elif delta >= min_graph_delta and cost_ratio <= max_graph_cost_ratio:
            decision = "graph"
        elif delta <= 0.02:
            decision = "vector"
        else:
            decision = "need_more_data"
            blockers.append(f"inconclusive_category:{category}")
        categories[category] = {
            "sample_count": len(rows),
            "vector_quality": round(vector_quality, 6),
            "graph_quality": round(graph_quality, 6),
            "quality_delta": round(delta, 6),
            "cost_ratio": round(cost_ratio, 6),
            "decision": decision,
        }
        routing_policy[category] = {
            "graph": {
                "local": "graph_local",
                "global": "graph_global",
                "multi_hop": "graph_multihop",
                "factual": "hybrid",
            }[category],
            "vector": "hybrid",
            "need_more_data": "hybrid",
        }[decision]
    return {
        "schema_version": "graphrag_ab_report_v1",
        "experiment_id": f"week13-ab-{uuid.uuid4().hex[:12]}",
        "vector_release_id": vector_release_id,
        "graph_release_id": graph_release_id,
        "categories": categories,
        "routing_policy": routing_policy,
        "gate": {"status": "pass" if not blockers else "fail", "blocking_reasons": blockers},
    }


def _avg(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0
