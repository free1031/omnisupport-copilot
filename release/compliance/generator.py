"""Generate an evidence pack from real, digest-verified release artifacts."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from release.integrity import file_digest, verify_manifest
from release.schema import validate_instance, validate_manifest_schema

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_PACK_SCHEMA = (
    ROOT / "contracts/release/compliance_evidence_pack.schema.json"
)


def build_evidence_pack(
    manifest: dict[str, Any],
    *,
    evidence_paths: list[Path],
    signing_key: bytes | None = None,
    project_root: Path | None = None,
) -> dict[str, Any]:
    validate_manifest_schema(manifest)
    verify_manifest(manifest, signing_key=signing_key)
    project_root = (project_root or Path.cwd()).resolve()
    artifacts = []
    seen: set[str] = set()
    for locked_path, locked_digest in _locked_artifacts(manifest["spec"]):
        path = (project_root / locked_path).resolve()
        try:
            path.relative_to(project_root)
        except ValueError as exc:
            raise ValueError(f"locked artifact escapes project root: {locked_path}") from exc
        if not path.is_file():
            raise FileNotFoundError(f"locked release artifact does not exist: {locked_path}")
        actual = file_digest(path)
        if actual != locked_digest:
            raise ValueError(f"locked release artifact digest mismatch: {locked_path}")
        artifacts.append({"path": locked_path, "digest": actual, "size_bytes": path.stat().st_size})
        seen.add(str(path))
    for path in evidence_paths:
        if not path.is_file():
            raise FileNotFoundError(f"evidence artifact does not exist: {path}")
        resolved = str(path.resolve())
        if resolved not in seen:
            artifacts.append({"path": str(path), "digest": file_digest(path), "size_bytes": path.stat().st_size})
            seen.add(resolved)

    environment = manifest["metadata"]["environment"]
    required_kinds = {"impact", "eval", "rollout"} if environment == "prod" else {"impact", "eval"}
    available = {"eval"} if manifest["spec"]["quality"]["eval"].get("artifact_digests") else set()
    for item in artifacts:
        name = Path(item["path"]).name.lower()
        if "impact" in name:
            available.add("impact")
        if "eval" in name or "regression" in name:
            available.add("eval")
        if "canary" in name or "rollout" in name:
            available.add("rollout")
    missing = sorted(required_kinds - available)
    pack = {
        "schema_version": "compliance_evidence_pack_v1",
        "release_id": manifest["metadata"]["release_id"],
        "manifest_digest": manifest["integrity"]["manifest_digest"],
        "previous_release_id": manifest["metadata"].get("previous_release_id"),
        "previous_manifest_digest": manifest["metadata"].get("previous_manifest_digest"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "artifacts": artifacts,
        "completeness": {"status": "pass" if not missing else "fail", "missing": missing},
    }
    validate_instance(pack, EVIDENCE_PACK_SCHEMA)
    return pack


def _locked_artifacts(value: Any):
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "artifact_digests":
                yield from item.items()
            else:
                yield from _locked_artifacts(item)
    elif isinstance(value, list):
        for item in value:
            yield from _locked_artifacts(item)


def write_pack(pack: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "compliance-evidence-pack.json"
    json_path.write_text(json.dumps(pack, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path = output_dir / "release-whitepaper.md"
    rows = "\n".join(f"| `{item['path']}` | `{item['digest']}` | {item['size_bytes']} |" for item in pack["artifacts"])
    markdown_path.write_text(
        "\n".join(
            [
                f"# Release Evidence Pack: {pack['release_id']}",
                "",
                f"- Manifest digest: `{pack['manifest_digest']}`",
                f"- Previous release: `{pack.get('previous_release_id') or 'none'}`",
                f"- Completeness: **{pack['completeness']['status']}**",
                "",
                "| Artifact | SHA-256 | Bytes |",
                "|---|---|---:|",
                rows,
                "",
                "This file is generated from checked-in or runtime evidence. Missing evidence is never synthesized.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return json_path, markdown_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a Week14 compliance evidence pack")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, action="append", default=[])
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/compliance"))
    parser.add_argument("--signing-key-env", default="WEEK14_RELEASE_SIGNING_KEY")
    args = parser.parse_args(argv)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    signing_value = os.getenv(args.signing_key_env, "")
    pack = build_evidence_pack(
        manifest,
        evidence_paths=args.evidence,
        signing_key=signing_value.encode("utf-8") if signing_value else None,
    )
    paths = write_pack(pack, args.output_dir)
    print(json.dumps({"status": pack["completeness"]["status"], "paths": [str(path) for path in paths]}, ensure_ascii=False, indent=2))
    return 0 if pack["completeness"]["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
