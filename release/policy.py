"""Environment-aware release policy checks."""

from __future__ import annotations

from typing import Any

REQUIRED_COMPONENTS = {"data", "index", "prompt", "model", "skills", "graph"}


def validate_release_policy(manifest: dict[str, Any]) -> None:
    metadata = manifest["metadata"]
    components = manifest["spec"]["components"]
    missing = sorted(REQUIRED_COMPONENTS - components.keys())
    if missing:
        raise ValueError(f"release manifest is missing components: {', '.join(missing)}")

    environment = metadata["environment"]
    if not metadata["release_id"].startswith(f"omni-{environment}-"):
        raise ValueError("release_id environment does not match metadata.environment")
    previous_id = metadata.get("previous_release_id")
    previous_digest = metadata.get("previous_manifest_digest")
    if bool(previous_id) != bool(previous_digest):
        raise ValueError(
            "previous_release_id and previous_manifest_digest must be set together"
        )
    if components["index"]["data_release_id"] != components["data"]["release_id"]:
        raise ValueError("index data_release_id must match the governed data release_id")

    eval_gate = manifest["spec"]["quality"]["eval"]["gate_status"]
    if eval_gate != "pass":
        raise ValueError(f"evaluation gate must pass before registration, got {eval_gate!r}")
    slo_status = manifest["spec"]["business_slo"]["status"]
    if slo_status != "pass":
        raise ValueError(f"business SLO must pass before registration, got {slo_status!r}")

    rollout = manifest["spec"]["rollout"]
    stage_order = [int(item["traffic_percent"]) for item in rollout["stages"]]
    if stage_order != [5, 25, 50, 100]:
        raise ValueError("rollout stages must be ordered exactly as 5, 25, 50, 100")
    if not rollout.get("red_lines"):
        raise ValueError("at least one compliance or safety red line is required")

    if environment == "prod":
        created_by = metadata["created_by"]
        approved_by = metadata.get("approved_by")
        if not approved_by:
            raise ValueError("production release requires approved_by")
        if approved_by == created_by:
            raise ValueError("production release requires four-eyes approval")
        signature = manifest["integrity"]["signature"]
        if signature["algorithm"] == "none":
            raise ValueError("production release must be signed")
        data_ref = components["data"]["lakefs_ref"]
        if not data_ref.startswith("refs/tags/"):
            raise ValueError("production data release must use an immutable lakeFS tag")
        model_snapshot = components["model"]["snapshot"].lower()
        if model_snapshot.endswith(":latest") or model_snapshot.endswith("@latest"):
            raise ValueError("production model snapshot cannot use a mutable latest alias")


def release_is_promotable(manifest: dict[str, Any]) -> bool:
    try:
        validate_release_policy(manifest)
    except (KeyError, TypeError, ValueError):
        return False
    return True
