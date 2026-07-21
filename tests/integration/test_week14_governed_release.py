from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from release.generator import build_manifest, load_document
from release.registry import ReleaseRegistry
from rollout.canary import evaluate_canary

ROOT = Path(__file__).resolve().parents[2]
SPEC_PATH = ROOT / "release/specs/week14_local.yaml"
MIGRATION = ROOT / "infra/migrations/011_week14_governed_release.sql"
DUMMY_DIGEST = "sha256:" + "a" * 64


def test_week14_canary_is_red_line_first_and_holds_incomplete_windows():
    rollout = load_document(SPEC_PATH)["rollout"]
    passed = json.loads((ROOT / "tests/fixtures/week14/canary_5_percent_pass.json").read_text())
    assert (
        evaluate_canary(
            rollout,
            passed,
            release_id="test-release",
            manifest_digest=DUMMY_DIGEST,
        )["decision"]
        == "promote"
    )

    incomplete = dict(passed, sample_size=5)
    assert (
        evaluate_canary(
            rollout,
            incomplete,
            release_id="test-release",
            manifest_digest=DUMMY_DIGEST,
        )["decision"]
        == "hold"
    )

    breach = json.loads((ROOT / "tests/fixtures/week14/canary_red_line_breach.json").read_text())
    decision = evaluate_canary(
        rollout,
        breach,
        release_id="test-release",
        manifest_digest=DUMMY_DIGEST,
    )
    assert decision["decision"] == "rollback"
    assert decision["reason_codes"][0].startswith("red_line_breached:pii_leak_rate")


def test_week14_real_postgres_register_promote_and_atomic_rollback(tmp_path):
    psycopg2 = pytest.importorskip("psycopg2")
    database_url = os.getenv("DATABASE_URL", "")
    if not database_url:
        pytest.skip("DATABASE_URL is required for the real Week14 registry test")
    dsn = database_url.replace("postgresql+psycopg2://", "postgresql://", 1).replace("postgresql+asyncpg://", "postgresql://", 1)
    try:
        admin_connection = psycopg2.connect(dsn)
    except psycopg2.OperationalError as exc:
        pytest.skip(f"PostgreSQL is not reachable: {exc}")
    schema = f"week14_test_{uuid.uuid4().hex}"
    with admin_connection, admin_connection.cursor() as cursor:
        cursor.execute(f'CREATE SCHEMA "{schema}"')
    isolated_dsn = f"{dsn}{'&' if '?' in dsn else '?'}options=-csearch_path%3D{schema}"
    with psycopg2.connect(isolated_dsn) as connection, connection.cursor() as cursor:
        cursor.execute(MIGRATION.read_text(encoding="utf-8"))
        cursor.execute(MIGRATION.read_text(encoding="utf-8"))

    signing_key = b"week14-integration-key"
    spec = load_document(SPEC_PATH)
    first = build_manifest(
        spec,
        project_root=ROOT,
        output_dir=tmp_path,
        environment="dev",
        created_by="integration-test",
        signing_key=signing_key,
        git_sha="139d8db68293e0763bef823b6b48308ba1acbf8d",
        now=datetime(2026, 7, 21, 8, 0, tzinfo=timezone.utc),
    )
    (tmp_path / f"{first['metadata']['release_id']}.json").write_text(json.dumps(first), encoding="utf-8")
    second = build_manifest(
        spec,
        project_root=ROOT,
        output_dir=tmp_path,
        environment="dev",
        created_by="integration-test",
        previous_manifest=first,
        signing_key=signing_key,
        git_sha="139d8db68293e0763bef823b6b48308ba1acbf8d",
        now=datetime(2026, 7, 21, 9, 0, tzinfo=timezone.utc),
    )

    registry = ReleaseRegistry(isolated_dsn)
    ids = [first["metadata"]["release_id"], second["metadata"]["release_id"]]
    try:
        assert registry.register(first, signing_key=signing_key) is True
        assert registry.register(first, signing_key=signing_key) is False
        registry.promote(ids[0], actor="release-owner", expected_current_release_id=None)
        assert registry.register(second, signing_key=signing_key) is True
        observation = json.loads(
            (ROOT / "tests/fixtures/week14/canary_5_percent_pass.json").read_text()
        )
        observation["release_id"] = ids[1]
        decision = evaluate_canary(
            spec["rollout"],
            observation,
            release_id=ids[1],
            manifest_digest=second["integrity"]["manifest_digest"],
        )
        registry.record_rollout_decision(ids[1], decision, actor="release-owner")
        with pytest.raises(ValueError, match="stale release pointer"):
            registry.promote(ids[1], actor="release-owner", expected_current_release_id=None)
        generation = registry.promote(ids[1], actor="release-owner", expected_current_release_id=ids[0])
        assert generation == 2
        generation = registry.rollback(ids[0], actor="incident-commander", expected_current_release_id=ids[1], reason="canary_red_line")
        assert generation == 3
        active = registry.active_release("dev")
        assert active and active["release_id"] == ids[0]
        with psycopg2.connect(isolated_dsn) as verification, verification.cursor() as cursor:
            cursor.execute(
                "SELECT previous_event_digest, event_digest FROM release_audit_event "
                "ORDER BY occurred_at, event_id"
            )
            audit_chain = cursor.fetchall()
            assert audit_chain[0][0] is None
            assert all(
                audit_chain[index][0] == audit_chain[index - 1][1]
                for index in range(1, len(audit_chain))
            )
        with pytest.raises(psycopg2.errors.RaiseException, match="immutable"):
            with psycopg2.connect(isolated_dsn) as immutable, immutable.cursor() as cursor:
                cursor.execute(
                    "UPDATE governed_release_manifest SET created_by = 'tamper' WHERE release_id = %s",
                    (ids[0],),
                )

        prod = build_manifest(
            spec,
            project_root=ROOT,
            output_dir=tmp_path / "prod",
            environment="prod",
            created_by="release-author",
            approved_by="release-owner",
            signing_key=signing_key,
            git_sha="139d8db68293e0763bef823b6b48308ba1acbf8d",
            now=datetime(2026, 7, 21, 10, 0, tzinfo=timezone.utc),
        )
        prod_id = prod["metadata"]["release_id"]
        assert registry.register(prod, signing_key=signing_key) is True
        with pytest.raises(ValueError, match="production promotion requires"):
            registry.promote(
                prod_id,
                actor="release-owner",
                expected_current_release_id=None,
            )

        observation = json.loads(
            (ROOT / "tests/fixtures/week14/canary_5_percent_pass.json").read_text()
        )
        observation["release_id"] = prod_id
        observation["stage_percent"] = 25
        observation["sample_size"] = 100
        observation["observation_minutes"] = 30
        out_of_order = evaluate_canary(
            spec["rollout"],
            observation,
            release_id=prod_id,
            manifest_digest=prod["integrity"]["manifest_digest"],
        )
        mismatched = dict(out_of_order, release_id="omni-prod-v2026.07.21-999")
        with pytest.raises(ValueError, match="does not match"):
            registry.record_rollout_decision(
                prod_id, mismatched, actor="release-owner"
            )
        wrong_digest = dict(out_of_order, manifest_digest=DUMMY_DIGEST)
        with pytest.raises(ValueError, match="manifest_digest"):
            registry.record_rollout_decision(
                prod_id, wrong_digest, actor="release-owner"
            )
        with pytest.raises(ValueError, match="recorded in order"):
            registry.record_rollout_decision(
                prod_id, out_of_order, actor="release-owner"
            )

        for stage in spec["rollout"]["stages"]:
            observation["stage_percent"] = stage["traffic_percent"]
            observation["sample_size"] = stage["min_samples"]
            observation["observation_minutes"] = stage["min_observation_minutes"]
            decision = evaluate_canary(
                spec["rollout"],
                observation,
                release_id=prod_id,
                manifest_digest=prod["integrity"]["manifest_digest"],
            )
            assert decision["decision"] == "promote"
            registry.record_rollout_decision(
                prod_id, decision, actor="release-owner"
            )
        generation = registry.promote(
            prod_id,
            actor="release-owner",
            expected_current_release_id=None,
        )
        assert generation == 1
        with pytest.raises(psycopg2.errors.RaiseException, match="immutable"):
            with psycopg2.connect(isolated_dsn) as immutable, immutable.cursor() as cursor:
                cursor.execute(
                    "UPDATE release_rollout_event SET decision = 'hold' "
                    "WHERE release_id = %s",
                    (prod_id,),
                )
    finally:
        with admin_connection, admin_connection.cursor() as cursor:
            cursor.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        admin_connection.close()
