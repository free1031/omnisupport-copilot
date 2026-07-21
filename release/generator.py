"""Build a reproducible Week14 release manifest from a reviewed release spec."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from release.integrity import file_digest, finalize_manifest
from release.policy import validate_release_policy
from release.schema import validate_manifest_schema

RELEASE_ID_RE = re.compile(r"^omni-(dev|staging|prod)-v(\d{4}\.\d{2}\.\d{2})-(\d{3})$")


def load_document(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    value = yaml.safe_load(text) if path.suffix.lower() in {".yaml", ".yml"} else json.loads(text)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def current_git_sha(project_root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=project_root,
        check=True,
        capture_output=True,
        text=True,
    )
    sha = result.stdout.strip()
    if not re.fullmatch(r"[a-f0-9]{40}", sha):
        raise ValueError(f"unexpected git SHA: {sha!r}")
    return sha


def allocate_release_id(environment: str, when: datetime, output_dir: Path) -> str:
    day = when.astimezone(timezone.utc).strftime("%Y.%m.%d")
    prefix = f"omni-{environment}-v{day}-"
    sequences = []
    if output_dir.exists():
        for path in output_dir.glob(f"{prefix}*.json"):
            match = RELEASE_ID_RE.fullmatch(path.stem)
            if match:
                sequences.append(int(match.group(3)))
    return f"{prefix}{max(sequences, default=0) + 1:03d}"


def _resolve_artifact_digests(value: Any, project_root: Path) -> Any:
    if isinstance(value, list):
        return [_resolve_artifact_digests(item, project_root) for item in value]
    if not isinstance(value, dict):
        return value
    result = {key: _resolve_artifact_digests(item, project_root) for key, item in value.items()}
    source_paths = result.pop("source_paths", None)
    if source_paths is not None:
        if not isinstance(source_paths, list) or not source_paths:
            raise ValueError("source_paths must be a non-empty list")
        digests: dict[str, str] = {}
        for raw_path in source_paths:
            path = (project_root / str(raw_path)).resolve()
            try:
                relative = path.relative_to(project_root.resolve())
            except ValueError as exc:
                raise ValueError(f"artifact path escapes project root: {raw_path}") from exc
            if not path.is_file():
                raise FileNotFoundError(f"release artifact does not exist: {relative}")
            digests[str(relative)] = file_digest(path)
        result["artifact_digests"] = digests
    return result


def build_manifest(
    spec: dict[str, Any],
    *,
    project_root: Path,
    output_dir: Path,
    environment: str,
    created_by: str,
    approved_by: str | None = None,
    previous_manifest: dict[str, Any] | None = None,
    signing_key: bytes | None = None,
    signing_key_id: str | None = None,
    git_sha: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    release_id = allocate_release_id(environment, now, output_dir)
    previous_metadata = previous_manifest.get("metadata", {}) if previous_manifest else {}
    previous_integrity = previous_manifest.get("integrity", {}) if previous_manifest else {}
    manifest = {
        "api_version": "omnisupport.ai/v2",
        "kind": "GovernedRelease",
        "metadata": {
            "release_id": release_id,
            "environment": environment,
            "created_at": now.astimezone(timezone.utc).isoformat(),
            "created_by": created_by,
            "approved_by": approved_by,
            "git_sha": git_sha or current_git_sha(project_root),
            "previous_release_id": previous_metadata.get("release_id"),
            "previous_manifest_digest": previous_integrity.get("manifest_digest"),
        },
        "spec": _resolve_artifact_digests(deepcopy(spec), project_root),
    }
    result = finalize_manifest(manifest, signing_key=signing_key, key_id=signing_key_id)
    validate_manifest_schema(result)
    validate_release_policy(result)
    return result


def validate_schema(manifest: dict[str, Any], schema_path: Path) -> None:
    validate_manifest_schema(manifest, schema_path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate an immutable Week14 release manifest")
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/releases"))
    parser.add_argument("--environment", choices=["dev", "staging", "prod"], default="dev")
    parser.add_argument("--created-by", required=True)
    parser.add_argument("--approved-by")
    parser.add_argument("--previous-manifest", type=Path)
    parser.add_argument("--signing-key-env", default="WEEK14_RELEASE_SIGNING_KEY")
    parser.add_argument("--signing-key-id", default="week14-local")
    parser.add_argument("--git-sha", default=os.getenv("GIT_SHA"))
    parser.add_argument(
        "--schema",
        type=Path,
        default=Path("contracts/release/release_manifest_v2.schema.json"),
    )
    args = parser.parse_args(argv)

    project_root = Path.cwd().resolve()
    previous = load_document(args.previous_manifest) if args.previous_manifest else None
    signing_value = os.getenv(args.signing_key_env, "")
    signing_key = signing_value.encode("utf-8") if signing_value else None
    manifest = build_manifest(
        load_document(args.spec),
        project_root=project_root,
        output_dir=args.output_dir,
        environment=args.environment,
        created_by=args.created_by,
        approved_by=args.approved_by,
        previous_manifest=previous,
        signing_key=signing_key,
        signing_key_id=args.signing_key_id,
        git_sha=args.git_sha,
    )
    validate_schema(manifest, args.schema)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = args.output_dir / f"{manifest['metadata']['release_id']}.json"
    try:
        with output.open("x", encoding="utf-8") as stream:
            json.dump(manifest, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    except FileExistsError as exc:
        raise FileExistsError(f"release manifest is immutable and already exists: {output}") from exc
    print(json.dumps({"release_id": manifest["metadata"]["release_id"], "manifest_digest": manifest["integrity"]["manifest_digest"], "path": str(output)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
