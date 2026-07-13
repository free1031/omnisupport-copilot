"""Deterministic SLO and error-budget evaluation for Week12 labs and CI."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import yaml


def load_observations(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_policy(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(int(round((len(ordered) - 1) * fraction)), len(ordered) - 1)
    return round(float(ordered[index]), 3)


def evaluate_slo(observations: list[dict[str, Any]], policy: dict[str, Any]) -> dict[str, Any]:
    roots = [item for item in observations if item.get("span_name") == "rag.query"]
    total = len(roots)
    failures = [
        item
        for item in roots
        if item.get("status_code") == "ERROR" or item.get("business_status") == "failed"
    ]
    availability = (total - len(failures)) / max(total, 1)
    latencies = [float(item.get("latency_ms", 0.0)) for item in roots]
    cited = [item for item in roots if int(item.get("evidence_count", 0)) > 0]
    citation_coverage = len(cited) / max(total, 1)
    avg_cost = sum(float(item.get("cost_usd", 0.0)) for item in roots) / max(total, 1)
    pii_leaks = sum(int(item.get("pii_leak_count", 0)) for item in roots)

    objectives = policy["objectives"]
    availability_target = float(objectives["availability"]["target"])
    allowed_error = max(1.0 - availability_target, 0.000001)
    observed_error = len(failures) / max(total, 1)
    burn_rate = observed_error / allowed_error
    remaining = 1.0 - min(observed_error / allowed_error, 1.0)

    failing_trace_ids = [item.get("trace_id", "") for item in failures if item.get("trace_id")]
    error_types = Counter(item.get("error_type", "unknown") for item in failures)
    common_context = {
        "sample_trace_ids": failing_trace_ids[:5],
        "top_error_types": [f"{key}:{value}" for key, value in error_types.most_common(5)],
    }
    alerts: list[dict[str, Any]] = []
    if pii_leaks > 0:
        alerts.append(
            {
                "name": "copilot_pii_leak",
                "severity": "P0",
                "current": pii_leaks,
                "target": 0,
                **common_context,
            }
        )

    burn = policy["burn_rate"]
    if burn_rate >= float(burn["fast_threshold"]):
        alerts.append(
            {
                "name": "copilot_availability_burn_fast",
                "severity": "P1",
                "current": round(availability, 6),
                "target": availability_target,
                "burn_rate": round(burn_rate, 3),
                **common_context,
            }
        )
    elif burn_rate >= float(burn["slow_threshold"]):
        alerts.append(
            {
                "name": "copilot_availability_burn_slow",
                "severity": "P2",
                "current": round(availability, 6),
                "target": availability_target,
                "burn_rate": round(burn_rate, 3),
                **common_context,
            }
        )

    p99 = _percentile(latencies, 0.99)
    latency_target = float(objectives["latency_p99_ms"]["target"])
    if p99 > latency_target:
        alerts.append(
            {
                "name": "copilot_latency_p99",
                "severity": "P2",
                "current": p99,
                "target": latency_target,
                **common_context,
            }
        )

    citation_target = float(objectives["citation_coverage"]["target"])
    if citation_coverage < citation_target:
        alerts.append(
            {
                "name": "copilot_citation_coverage",
                "severity": "P2",
                "current": round(citation_coverage, 6),
                "target": citation_target,
                **common_context,
            }
        )

    cost_target = float(objectives["cost_per_query_usd"]["target"])
    if avg_cost > cost_target:
        alerts.append(
            {
                "name": "copilot_cost_per_query",
                "severity": "P3",
                "current": round(avg_cost, 6),
                "target": cost_target,
                **common_context,
            }
        )

    return {
        "policy_version": str(policy["version"]),
        "window": {"sample_count": total},
        "sli": {
            "availability": round(availability, 6),
            "latency_p50_ms": _percentile(latencies, 0.50),
            "latency_p99_ms": p99,
            "citation_coverage": round(citation_coverage, 6),
            "cost_per_query_usd": round(avg_cost, 6),
            "pii_leak_count": pii_leaks,
        },
        "error_budget": {
            "allowed_error_ratio": round(allowed_error, 6),
            "observed_error_ratio": round(observed_error, 6),
            "remaining_ratio": round(max(remaining, 0.0), 6),
            "burn_rate": round(burn_rate, 3),
        },
        "alerts": alerts,
    }
