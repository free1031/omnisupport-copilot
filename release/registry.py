"""Transactional PostgreSQL registry and atomic environment release pointer."""

from __future__ import annotations

import argparse
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from release.integrity import (
    canonical_json,
    sha256_digest,
    verify_manifest,
    verify_manifest_digest,
)
from release.policy import validate_release_policy
from release.schema import validate_canary_decision, validate_manifest_schema


def _dsn(database_url: str) -> str:
    return database_url.replace("postgresql+psycopg2://", "postgresql://", 1).replace(
        "postgresql+asyncpg://", "postgresql://", 1
    )


class ReleaseRegistry:
    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise ValueError("database_url is required")
        self.database_url = _dsn(database_url)

    def register(self, manifest: dict[str, Any], *, signing_key: bytes | None = None) -> bool:
        import psycopg2

        validate_manifest_schema(manifest)
        verify_manifest(manifest, signing_key=signing_key)
        validate_release_policy(manifest)
        metadata = manifest["metadata"]
        release_id = metadata["release_id"]
        digest = manifest["integrity"]["manifest_digest"]
        with psycopg2.connect(self.database_url) as conn, conn.cursor() as cursor:
            cursor.execute("SELECT manifest_digest FROM governed_release_manifest WHERE release_id = %s FOR UPDATE", (release_id,))
            row = cursor.fetchone()
            if row:
                if row[0] == digest:
                    return False
                raise ValueError(f"release_id {release_id!r} already exists with different content")

            previous_release_id = metadata.get("previous_release_id")
            previous_digest = metadata.get("previous_manifest_digest")
            if previous_release_id:
                cursor.execute("SELECT environment, manifest_digest FROM governed_release_manifest WHERE release_id = %s", (previous_release_id,))
                previous = cursor.fetchone()
                if not previous or previous[0] != metadata["environment"] or previous[1] != previous_digest:
                    raise ValueError("previous release digest chain is missing or invalid")

            cursor.execute(
                """
                INSERT INTO governed_release_manifest (
                    release_id, environment, manifest_digest, previous_release_id,
                    previous_manifest_digest, git_sha, created_by, approved_by,
                    signature_algorithm, signature_key_id, signature_value, manifest_body
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                """,
                (
                    release_id,
                    metadata["environment"],
                    digest,
                    previous_release_id,
                    previous_digest,
                    metadata["git_sha"],
                    metadata["created_by"],
                    metadata.get("approved_by"),
                    manifest["integrity"]["signature"]["algorithm"],
                    manifest["integrity"]["signature"].get("key_id"),
                    manifest["integrity"]["signature"].get("value"),
                    json.dumps(manifest, ensure_ascii=False),
                ),
            )
            self._append_audit(cursor, metadata["environment"], "release.registered", metadata["created_by"], None, release_id, "manifest_registered", {"manifest_digest": digest})
        return True

    def active_release(self, environment: str) -> dict[str, Any] | None:
        import psycopg2

        with psycopg2.connect(self.database_url) as conn, conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT p.active_release_id, p.generation, m.manifest_body
                FROM release_environment_pointer p
                JOIN governed_release_manifest m ON m.release_id = p.active_release_id
                WHERE p.environment = %s
                """,
                (environment,),
            )
            row = cursor.fetchone()
        if not row:
            return None
        return {"release_id": row[0], "generation": row[1], "manifest": row[2]}

    def promote(
        self,
        release_id: str,
        *,
        actor: str,
        expected_current_release_id: str | None,
        reason: str = "canary_passed",
    ) -> int:
        return self._switch_pointer(
            release_id,
            actor=actor,
            expected_current_release_id=expected_current_release_id,
            reason=reason,
            event_type="release.promoted",
            require_direct_ancestor=False,
        )

    def rollback(
        self,
        target_release_id: str,
        *,
        actor: str,
        expected_current_release_id: str,
        reason: str,
    ) -> int:
        if not reason.strip():
            raise ValueError("rollback reason is required")
        return self._switch_pointer(
            target_release_id,
            actor=actor,
            expected_current_release_id=expected_current_release_id,
            reason=reason,
            event_type="release.rolled_back",
            require_direct_ancestor=True,
        )

    def record_rollout_decision(
        self, release_id: str, decision: dict[str, Any], *, actor: str
    ) -> str:
        import psycopg2

        validate_canary_decision(decision)
        if decision["release_id"] != release_id:
            raise ValueError("canary decision release_id does not match the target release")
        event_id = str(uuid.uuid4())
        with psycopg2.connect(self.database_url) as conn, conn.cursor() as cursor:
            cursor.execute(
                "SELECT environment, manifest_body FROM governed_release_manifest "
                "WHERE release_id = %s",
                (release_id,),
            )
            row = cursor.fetchone()
            if not row:
                raise ValueError(f"unknown release_id: {release_id}")
            environment, manifest = row
            manifest_digest = manifest["integrity"]["manifest_digest"]
            if decision["manifest_digest"] != manifest_digest:
                raise ValueError(
                    "canary decision manifest_digest does not match the registered release"
                )
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"release-rollout:{release_id}",),
            )
            stage_order = [
                int(stage["traffic_percent"])
                for stage in manifest["spec"]["rollout"]["stages"]
            ]
            stage_percent = int(decision["stage_percent"])
            if stage_percent not in stage_order:
                raise ValueError(
                    f"stage {stage_percent}% is not declared by release {release_id}"
                )
            cursor.execute(
                """
                SELECT DISTINCT ON (stage_percent) stage_percent, decision
                FROM release_rollout_event
                WHERE release_id = %s
                ORDER BY stage_percent, occurred_at DESC, event_id DESC
                """,
                (release_id,),
            )
            latest = {int(stage): status for stage, status in cursor.fetchall()}
            stage_index = stage_order.index(stage_percent)
            missing_prerequisites = [
                stage
                for stage in stage_order[:stage_index]
                if latest.get(stage) != "promote"
            ]
            if missing_prerequisites:
                raise ValueError(
                    "rollout stages must be recorded in order; missing promoted stages: "
                    + ", ".join(f"{stage}%" for stage in missing_prerequisites)
                )
            if any(stage > stage_percent for stage in latest):
                raise ValueError("cannot rewrite an earlier rollout stage after a later stage")
            cursor.execute(
                """
                INSERT INTO release_rollout_event (
                    event_id, release_id, manifest_digest, stage_percent, decision, reason_codes,
                    observation, actor
                ) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                """,
                (
                    event_id,
                    release_id,
                    manifest_digest,
                    decision["stage_percent"],
                    decision["decision"],
                    decision.get("reason_codes", []),
                    json.dumps(decision, ensure_ascii=False),
                    actor,
                ),
            )
            self._append_audit(
                cursor,
                environment,
                "rollout.decision",
                actor,
                None,
                release_id,
                decision["decision"],
                {
                    "rollout_event_id": event_id,
                    "stage_percent": decision["stage_percent"],
                    "reason_codes": decision.get("reason_codes", []),
                },
            )
        return event_id

    def _switch_pointer(
        self,
        release_id: str,
        *,
        actor: str,
        expected_current_release_id: str | None,
        reason: str,
        event_type: str,
        require_direct_ancestor: bool,
    ) -> int:
        import psycopg2

        with psycopg2.connect(self.database_url) as conn, conn.cursor() as cursor:
            cursor.execute("SELECT environment, manifest_body FROM governed_release_manifest WHERE release_id = %s", (release_id,))
            target = cursor.fetchone()
            if not target:
                raise ValueError(f"unknown release_id: {release_id}")
            environment, target_manifest = target
            validate_manifest_schema(target_manifest)
            verify_manifest_digest(target_manifest)
            validate_release_policy(target_manifest)
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"release-rollout:{release_id}",),
            )
            if event_type == "release.promoted" and environment == "prod":
                self._require_complete_rollout(cursor, release_id, target_manifest)
            cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (f"release-pointer:{environment}",))
            cursor.execute("SELECT active_release_id, generation FROM release_environment_pointer WHERE environment = %s FOR UPDATE", (environment,))
            current = cursor.fetchone()
            current_release_id = current[0] if current else None
            generation = int(current[1]) if current else 0
            if current_release_id != expected_current_release_id:
                raise ValueError(f"stale release pointer: expected {expected_current_release_id!r}, found {current_release_id!r}")
            if event_type == "release.promoted" and target_manifest["metadata"].get("previous_release_id") != current_release_id:
                raise ValueError("candidate release must directly extend the active release")
            if require_direct_ancestor:
                cursor.execute("SELECT previous_release_id FROM governed_release_manifest WHERE release_id = %s", (current_release_id,))
                current_manifest = cursor.fetchone()
                if not current_manifest or current_manifest[0] != release_id:
                    raise ValueError("rollback target must be the direct previous release")
            new_generation = generation + 1
            cursor.execute(
                """
                INSERT INTO release_environment_pointer (
                    environment, active_release_id, generation, updated_by, updated_at
                ) VALUES (%s, %s, %s, %s, NOW())
                ON CONFLICT (environment) DO UPDATE SET
                    active_release_id = EXCLUDED.active_release_id,
                    generation = EXCLUDED.generation,
                    updated_by = EXCLUDED.updated_by,
                    updated_at = NOW()
                """,
                (environment, release_id, new_generation, actor),
            )
            self._append_audit(cursor, environment, event_type, actor, current_release_id, release_id, reason, {"generation": new_generation})
        return new_generation

    @staticmethod
    def _require_complete_rollout(
        cursor: Any, release_id: str, manifest: dict[str, Any]
    ) -> None:
        cursor.execute(
            """
            SELECT DISTINCT ON (stage_percent) stage_percent, decision
            FROM release_rollout_event
            WHERE release_id = %s
            ORDER BY stage_percent, occurred_at DESC, event_id DESC
            """,
            (release_id,),
        )
        latest = {int(stage): decision for stage, decision in cursor.fetchall()}
        required = [
            int(stage["traffic_percent"])
            for stage in manifest["spec"]["rollout"]["stages"]
        ]
        incomplete = [stage for stage in required if latest.get(stage) != "promote"]
        if incomplete:
            raise ValueError(
                "production promotion requires promoted canary evidence for stages: "
                + ", ".join(f"{stage}%" for stage in incomplete)
            )

    @staticmethod
    def _append_audit(
        cursor: Any,
        environment: str,
        event_type: str,
        actor: str,
        from_release_id: str | None,
        to_release_id: str | None,
        reason: str,
        details: dict[str, Any],
    ) -> str:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (f"release-audit:{environment}",))
        cursor.execute("SELECT event_digest FROM release_audit_event WHERE environment = %s ORDER BY occurred_at DESC, event_id DESC LIMIT 1", (environment,))
        previous_row = cursor.fetchone()
        previous_digest = previous_row[0] if previous_row else None
        occurred_at = datetime.now(timezone.utc).isoformat()
        event_id = str(uuid.uuid4())
        body = {
            "event_id": event_id,
            "environment": environment,
            "event_type": event_type,
            "actor": actor,
            "from_release_id": from_release_id,
            "to_release_id": to_release_id,
            "reason": reason,
            "details": details,
            "occurred_at": occurred_at,
            "previous_event_digest": previous_digest,
        }
        event_digest = sha256_digest(canonical_json(body))
        cursor.execute(
            """
            INSERT INTO release_audit_event (
                event_id, environment, event_type, actor, from_release_id,
                to_release_id, reason, details, previous_event_digest,
                event_digest, occurred_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s)
            """,
            (event_id, environment, event_type, actor, from_release_id, to_release_id, reason, json.dumps(details, ensure_ascii=False), previous_digest, event_digest, occurred_at),
        )
        return event_id


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Operate the Week14 governed release registry")
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL", ""))
    subparsers = parser.add_subparsers(dest="command", required=True)
    register_parser = subparsers.add_parser("register")
    register_parser.add_argument("--manifest", required=True)
    register_parser.add_argument("--signing-key-env", default="WEEK14_RELEASE_SIGNING_KEY")
    promote_parser = subparsers.add_parser("promote")
    promote_parser.add_argument("--release-id", required=True)
    promote_parser.add_argument("--expected-current-release-id")
    promote_parser.add_argument("--actor", required=True)
    active_parser = subparsers.add_parser("active")
    active_parser.add_argument("--environment", choices=["dev", "staging", "prod"], required=True)
    rollout_parser = subparsers.add_parser("record-rollout")
    rollout_parser.add_argument("--release-id", required=True)
    rollout_parser.add_argument("--decision", type=Path, required=True)
    rollout_parser.add_argument("--actor", required=True)
    args = parser.parse_args(argv)
    registry = ReleaseRegistry(args.database_url)
    if args.command == "register":
        manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
        signing_value = os.getenv(args.signing_key_env, "")
        created = registry.register(
            manifest,
            signing_key=signing_value.encode("utf-8") if signing_value else None,
        )
        result = {"status": "registered" if created else "already_registered", "release_id": manifest["metadata"]["release_id"]}
    elif args.command == "promote":
        generation = registry.promote(
            args.release_id,
            actor=args.actor,
            expected_current_release_id=args.expected_current_release_id,
        )
        result = {"status": "promoted", "release_id": args.release_id, "generation": generation}
    elif args.command == "record-rollout":
        decision = json.loads(args.decision.read_text(encoding="utf-8"))
        event_id = registry.record_rollout_decision(
            args.release_id, decision, actor=args.actor
        )
        result = {
            "status": "recorded",
            "release_id": args.release_id,
            "rollout_event_id": event_id,
        }
    else:
        result = registry.active_release(args.environment) or {"status": "not_found", "environment": args.environment}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
