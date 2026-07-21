"""Deterministic red-line-first canary decision engine."""

from __future__ import annotations

import argparse
import json
import operator
from pathlib import Path
from typing import Any, Callable

from release.integrity import verify_manifest_digest
from release.schema import validate_canary_decision, validate_manifest_schema

COMPARATORS: dict[str, Callable[[float, float], bool]] = {
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
    "==": operator.eq,
}


def _compare(actual: float, rule: dict[str, Any]) -> bool:
    comparator = COMPARATORS.get(str(rule["operator"]))
    if comparator is None:
        raise ValueError(f"unsupported comparator: {rule['operator']!r}")
    return comparator(actual, float(rule["threshold"]))


def evaluate_canary(
    rollout: dict[str, Any],
    observation: dict[str, Any],
    *,
    release_id: str | None = None,
    manifest_digest: str | None = None,
) -> dict[str, Any]:
    observed_release_id = observation.get("release_id")
    if release_id and observed_release_id and observed_release_id != release_id:
        raise ValueError("canary observation release_id does not match the manifest")
    bound_release_id = release_id or observed_release_id
    if not bound_release_id:
        raise ValueError("canary evaluation requires a release_id binding")
    if not manifest_digest:
        raise ValueError("canary evaluation requires a manifest_digest binding")
    stage_percent = int(observation["stage_percent"])
    stages = {int(item["traffic_percent"]): item for item in rollout["stages"]}
    if stage_percent not in stages:
        raise ValueError(f"stage {stage_percent}% is not declared in the release manifest")
    stage = stages[stage_percent]
    metrics = {key: float(value) for key, value in observation.get("metrics", {}).items()}
    reasons: list[str] = []

    # Compliance and safety red lines always override product-quality improvements.
    for rule in rollout.get("red_lines", []):
        metric = rule["metric"]
        if metric not in metrics:
            reasons.append(f"missing_red_line_metric:{metric}")
            continue
        if _compare(metrics[metric], rule):
            reasons.append(f"red_line_breached:{metric}:{metrics[metric]}")
    if reasons:
        return _decision(
            bound_release_id,
            manifest_digest,
            stage_percent,
            "rollback",
            reasons,
            observation,
        )

    if int(observation.get("sample_size", 0)) < int(stage["min_samples"]):
        reasons.append("minimum_sample_not_reached")
    if float(observation.get("observation_minutes", 0)) < float(stage["min_observation_minutes"]):
        reasons.append("minimum_observation_window_not_reached")
    if reasons:
        return _decision(
            bound_release_id,
            manifest_digest,
            stage_percent,
            "hold",
            reasons,
            observation,
        )

    for rule in stage.get("gates", []):
        metric = rule["metric"]
        if metric not in metrics:
            reasons.append(f"missing_gate_metric:{metric}")
        elif not _compare(metrics[metric], rule):
            reasons.append(f"gate_failed:{metric}:{metrics[metric]}")

    baseline = {key: float(value) for key, value in observation.get("baseline", {}).items()}
    for rule in stage.get("baseline_guards", []):
        metric = rule["metric"]
        if metric not in metrics or metric not in baseline:
            reasons.append(f"missing_baseline_metric:{metric}")
            continue
        delta = metrics[metric] - baseline[metric]
        if not _compare(delta, rule):
            reasons.append(f"baseline_guard_failed:{metric}:{delta:.6f}")

    return _decision(
        bound_release_id,
        manifest_digest,
        stage_percent,
        "hold" if reasons else "promote",
        reasons,
        observation,
    )


def _decision(
    release_id: str,
    manifest_digest: str,
    stage_percent: int,
    decision: str,
    reasons: list[str],
    observation: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": "canary_decision_v1",
        "release_id": release_id,
        "manifest_digest": manifest_digest,
        "stage_percent": stage_percent,
        "decision": decision,
        "reason_codes": reasons,
        "sample_size": int(observation.get("sample_size", 0)),
        "observation_minutes": float(observation.get("observation_minutes", 0)),
        "metrics": observation.get("metrics", {}),
        "baseline": observation.get("baseline", {}),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate one Week14 canary stage")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--observation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    validate_manifest_schema(manifest)
    verify_manifest_digest(manifest)
    observation = json.loads(args.observation.read_text(encoding="utf-8"))
    decision = evaluate_canary(
        manifest["spec"]["rollout"],
        observation,
        release_id=manifest["metadata"]["release_id"],
        manifest_digest=manifest["integrity"]["manifest_digest"],
    )
    validate_canary_decision(decision)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(decision, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(decision, ensure_ascii=False, indent=2))
    return 0 if decision["decision"] == "promote" else 2


if __name__ == "__main__":
    raise SystemExit(main())
