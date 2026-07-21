"""Dependency-light OpenLineage event builder and HTTP/file emitter."""

from __future__ import annotations

import argparse
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from release.integrity import verify_manifest_digest
from release.schema import validate_manifest_schema


def build_release_event(
    manifest: dict[str, Any],
    *,
    event_type: str,
    run_id: str | None = None,
) -> dict[str, Any]:
    metadata = manifest["metadata"]
    validate_manifest_schema(manifest)
    verify_manifest_digest(manifest)
    components = manifest["spec"]["components"]
    inputs = [
        _dataset("omnisupport.data", components["data"]["release_id"], components["data"]),
        _dataset("omnisupport.index", components["index"]["release_id"], components["index"]),
        _dataset("omnisupport.prompt", components["prompt"]["release_id"], components["prompt"]),
        _dataset("omnisupport.model", components["model"]["release_id"], components["model"]),
        _dataset("omnisupport.skills", components["skills"]["release_id"], components["skills"]),
        _dataset("omnisupport.graph", components["graph"]["release_id"], components["graph"]),
    ]
    return {
        "eventType": event_type,
        "eventTime": datetime.now(timezone.utc).isoformat(),
        "run": {"runId": run_id or str(uuid.uuid4())},
        "job": {"namespace": "omnisupport.governance", "name": "week14.governed_release"},
        "inputs": inputs,
        "outputs": [
            _dataset(
                f"omnisupport.release.{metadata['environment']}",
                metadata["release_id"],
                {"manifest_digest": manifest["integrity"]["manifest_digest"]},
            )
        ],
        "producer": "https://github.com/dataPro-lgtm/omnisupport-copilot",
        "schemaURL": "https://openlineage.io/spec/1-0-2/OpenLineage.json#/$defs/RunEvent",
    }


def _dataset(namespace: str, name: str, version: dict[str, Any]) -> dict[str, Any]:
    return {
        "namespace": namespace,
        "name": name,
        "facets": {"version": {"_producer": "https://github.com/dataPro-lgtm/omnisupport-copilot", "_schemaURL": "https://openlineage.io/spec/facets/1-0-0/DatasetVersionDatasetFacet.json", "datasetVersion": json.dumps(version, sort_keys=True, ensure_ascii=False)}},
    }


def emit_event(event: dict[str, Any], *, endpoint: str | None = None, output: Path | None = None) -> None:
    payload = json.dumps(event, ensure_ascii=False).encode("utf-8")
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(payload + b"\n")
    if endpoint:
        request = Request(endpoint, data=payload, headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(request, timeout=10) as response:  # noqa: S310 - endpoint is operator configured.
            if response.status >= 300:
                raise RuntimeError(f"OpenLineage endpoint returned HTTP {response.status}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Emit an OpenLineage event for a governed release")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--event-type", choices=["START", "RUNNING", "COMPLETE", "ABORT", "FAIL", "OTHER"], default="COMPLETE")
    parser.add_argument("--run-id")
    parser.add_argument("--endpoint")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if not args.endpoint and not args.output:
        raise SystemExit("At least one of --endpoint or --output is required")
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    event = build_release_event(manifest, event_type=args.event_type, run_id=args.run_id)
    emit_event(event, endpoint=args.endpoint, output=args.output)
    print(json.dumps({"run_id": event["run"]["runId"], "event_type": event["eventType"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
