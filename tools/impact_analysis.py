"""Manifest-aware blast-radius analysis used before Week14 approval."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from release.integrity import verify_manifest_digest
from release.schema import validate_instance, validate_manifest_schema

ROOT = Path(__file__).resolve().parents[1]
IMPACT_SCHEMA = ROOT / "contracts/release/release_impact_report.schema.json"

IMPACT_MAP = {
    "data": {"risk": "critical", "downstream": ["index", "graph", "eval", "rag_api"], "tests": ["week04", "week07", "week08", "week11", "week13"]},
    "index": {"risk": "high", "downstream": ["eval", "rag_api"], "tests": ["week08", "week11"]},
    "prompt": {"risk": "high", "downstream": ["eval", "rag_api"], "tests": ["week08", "week11"]},
    "model": {"risk": "critical", "downstream": ["eval", "rag_api", "tool_api"], "tests": ["week08", "week10", "week11"]},
    "skills": {"risk": "high", "downstream": ["agent", "tool_api"], "tests": ["week09", "week10"]},
    "graph": {"risk": "high", "downstream": ["graphrag", "eval", "rag_api"], "tests": ["week13", "week11"]},
}
RISK_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}


def analyze_impact(previous: dict[str, Any] | None, candidate: dict[str, Any]) -> dict[str, Any]:
    old_components = (previous or {}).get("spec", {}).get("components", {})
    new_components = candidate["spec"]["components"]
    changed = [name for name in sorted(new_components) if old_components.get(name) != new_components[name]]
    impacts = [dict(component=name, **IMPACT_MAP.get(name, {"risk": "medium", "downstream": [], "tests": []})) for name in changed]
    max_risk = max((item["risk"] for item in impacts), key=lambda value: RISK_ORDER[value], default="low")
    required_approvals = ["release_owner"]
    if RISK_ORDER[max_risk] >= RISK_ORDER["high"]:
        required_approvals.append("service_owner")
    if RISK_ORDER[max_risk] >= RISK_ORDER["critical"]:
        required_approvals.append("data_or_model_owner")
    tests = sorted({test for item in impacts for test in item["tests"]})
    return {
        "schema_version": "release_impact_report_v1",
        "candidate_release_id": candidate["metadata"]["release_id"],
        "previous_release_id": (previous or {}).get("metadata", {}).get("release_id"),
        "changed_components": changed,
        "maximum_risk": max_risk,
        "impacts": impacts,
        "required_approvals": required_approvals,
        "required_test_suites": tests,
        "status": "review_required" if impacts else "no_change",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Analyze Week14 release blast radius")
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    candidate = json.loads(args.candidate.read_text(encoding="utf-8"))
    previous = json.loads(args.previous.read_text(encoding="utf-8")) if args.previous else None
    validate_manifest_schema(candidate)
    verify_manifest_digest(candidate)
    if previous:
        validate_manifest_schema(previous)
        verify_manifest_digest(previous)
    report = analyze_impact(previous, candidate)
    validate_instance(report, IMPACT_SCHEMA)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
