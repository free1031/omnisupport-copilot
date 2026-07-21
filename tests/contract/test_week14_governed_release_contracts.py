from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import jsonschema
import pytest

from governance.openlineage import build_release_event
from release.compliance.generator import build_evidence_pack
from release.generator import build_manifest, load_document, validate_schema
from release.integrity import verify_manifest
from release.policy import validate_release_policy
from tools.impact_analysis import analyze_impact

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "release/specs/week14_local.yaml"
SCHEMA = ROOT / "contracts/release/release_manifest_v2.schema.json"


def _manifest(tmp_path: Path, *, environment: str = "dev", signing_key: bytes | None = None):
    return build_manifest(
        load_document(SPEC),
        project_root=ROOT,
        output_dir=tmp_path,
        environment=environment,
        created_by="ci/week14",
        approved_by="release-owner" if environment == "prod" else None,
        signing_key=signing_key,
        git_sha="139d8db68293e0763bef823b6b48308ba1acbf8d",
        now=datetime(2026, 7, 20, 10, 0, tzinfo=timezone.utc),
    )


def test_week14_manifest_is_generated_from_real_artifacts_and_validates(tmp_path):
    manifest = _manifest(tmp_path)
    validate_schema(manifest, SCHEMA)
    verify_manifest(manifest)
    assert manifest["metadata"]["release_id"] == "omni-dev-v2026.07.20-001"
    assert manifest["spec"]["components"]["data"]["artifact_digests"]
    assert len(manifest["spec"]["components"]) == 6


def test_week14_manifest_detects_tampering_and_enforces_prod_approval(tmp_path):
    manifest = _manifest(tmp_path)
    tampered = deepcopy(manifest)
    tampered["spec"]["components"]["index"]["release_id"] = "changed-after-signing"
    with pytest.raises(ValueError, match="digest mismatch"):
        verify_manifest(tampered)

    unsigned_prod = deepcopy(manifest)
    unsigned_prod["metadata"]["environment"] = "prod"
    unsigned_prod["metadata"]["release_id"] = "omni-prod-v2026.07.20-001"
    unsigned_prod["metadata"]["approved_by"] = "ci/week14"
    with pytest.raises(ValueError, match="four-eyes"):
        validate_release_policy(unsigned_prod)
    signed_prod = _manifest(tmp_path / "prod", environment="prod", signing_key=b"test-key")
    verify_manifest(signed_prod, signing_key=b"test-key")

    mismatched_index = deepcopy(manifest)
    mismatched_index["spec"]["components"]["index"]["data_release_id"] = "other-data"
    with pytest.raises(ValueError, match="data_release_id"):
        validate_release_policy(mismatched_index)

    incomplete_chain = deepcopy(manifest)
    incomplete_chain["metadata"]["previous_release_id"] = "omni-dev-v2026.07.19-001"
    with pytest.raises(ValueError, match="must be set together"):
        validate_release_policy(incomplete_chain)


def test_week14_impact_lineage_and_compliance_use_the_same_manifest(tmp_path):
    manifest = _manifest(tmp_path)
    previous = deepcopy(manifest)
    previous["metadata"]["release_id"] = "omni-dev-v2026.07.19-001"
    previous["spec"]["components"]["prompt"]["release_id"] = "prompt-old"
    report = analyze_impact(previous, manifest)
    impact_schema = json.loads((ROOT / "contracts/release/release_impact_report.schema.json").read_text())
    jsonschema.Draft202012Validator(impact_schema).validate(report)
    assert report["changed_components"] == ["prompt"]
    assert "week11" in report["required_test_suites"]

    event = build_release_event(manifest, event_type="COMPLETE", run_id="week14-test")
    assert len(event["inputs"]) == 6
    assert event["outputs"][0]["name"] == manifest["metadata"]["release_id"]

    impact_path = tmp_path / "impact-report.json"
    eval_path = tmp_path / "eval-report.json"
    impact_path.write_text(json.dumps(report), encoding="utf-8")
    eval_path.write_text('{"gate":"pass"}\n', encoding="utf-8")
    pack = build_evidence_pack(manifest, evidence_paths=[impact_path, eval_path])
    pack_schema = json.loads((ROOT / "contracts/release/compliance_evidence_pack.schema.json").read_text())
    jsonschema.Draft202012Validator(pack_schema).validate(pack)
    assert pack["completeness"]["status"] == "pass"
