"""Canonical hashing and optional signing for immutable release manifests."""

from __future__ import annotations

import copy
import hashlib
import hmac
import json
from pathlib import Path
from typing import Any


def canonical_json(value: Any) -> bytes:
    """Return stable UTF-8 JSON bytes suitable for hashing and signing."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_digest(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return f"sha256:{digest.hexdigest()}"


def manifest_payload(manifest: dict[str, Any]) -> dict[str, Any]:
    """Return the signed body; integrity metadata never signs itself."""

    payload = copy.deepcopy(manifest)
    payload.pop("integrity", None)
    return payload


def finalize_manifest(
    manifest: dict[str, Any],
    *,
    signing_key: bytes | None = None,
    key_id: str | None = None,
) -> dict[str, Any]:
    result = copy.deepcopy(manifest_payload(manifest))
    digest = sha256_digest(canonical_json(result))
    if signing_key:
        signature = hmac.new(signing_key, digest.encode("ascii"), hashlib.sha256).hexdigest()
        signing = {
            "algorithm": "hmac-sha256",
            "key_id": key_id or "local-week14",
            "value": signature,
        }
    else:
        signing = {"algorithm": "none", "key_id": None, "value": None}
    result["integrity"] = {"manifest_digest": digest, "signature": signing}
    return result


def verify_manifest_digest(manifest: dict[str, Any]) -> None:
    integrity = manifest.get("integrity") or {}
    expected = integrity.get("manifest_digest")
    actual = sha256_digest(canonical_json(manifest_payload(manifest)))
    if not expected or not hmac.compare_digest(str(expected), actual):
        raise ValueError("release manifest digest mismatch")


def verify_manifest(manifest: dict[str, Any], *, signing_key: bytes | None = None) -> None:
    verify_manifest_digest(manifest)
    integrity = manifest["integrity"]
    actual = integrity["manifest_digest"]

    signature = integrity.get("signature") or {}
    algorithm = signature.get("algorithm")
    if algorithm == "none":
        if signing_key is not None:
            raise ValueError("release manifest is unsigned")
        return
    if algorithm != "hmac-sha256":
        raise ValueError(f"unsupported signature algorithm: {algorithm!r}")
    if signing_key is None:
        raise ValueError("signing key is required to verify this release manifest")
    expected_signature = hmac.new(signing_key, actual.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(str(signature.get("value") or ""), expected_signature):
        raise ValueError("release manifest signature mismatch")
