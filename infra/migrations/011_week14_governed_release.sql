-- Week14 immutable release registry, atomic environment pointer and audit chain.
-- Additive and idempotent: Week01-Week13 tables remain unchanged.

CREATE TABLE IF NOT EXISTS governed_release_manifest (
    release_id                TEXT PRIMARY KEY,
    environment               TEXT NOT NULL CHECK (environment IN ('dev', 'staging', 'prod')),
    manifest_digest           TEXT NOT NULL UNIQUE CHECK (manifest_digest ~ '^sha256:[a-f0-9]{64}$'),
    previous_release_id       TEXT REFERENCES governed_release_manifest(release_id),
    previous_manifest_digest  TEXT CHECK (
        previous_manifest_digest IS NULL
        OR previous_manifest_digest ~ '^sha256:[a-f0-9]{64}$'
    ),
    git_sha                   CHAR(40) NOT NULL CHECK (git_sha ~ '^[a-f0-9]{40}$'),
    created_by                TEXT NOT NULL,
    approved_by               TEXT,
    signature_algorithm       TEXT NOT NULL,
    signature_key_id          TEXT,
    signature_value           TEXT,
    manifest_body             JSONB NOT NULL,
    created_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (
        (previous_release_id IS NULL AND previous_manifest_digest IS NULL)
        OR (previous_release_id IS NOT NULL AND previous_manifest_digest IS NOT NULL)
    ),
    CHECK (
        environment <> 'prod'
        OR (
            approved_by IS NOT NULL
            AND approved_by IS DISTINCT FROM created_by
            AND signature_algorithm <> 'none'
        )
    )
);

CREATE TABLE IF NOT EXISTS release_environment_pointer (
    environment        TEXT PRIMARY KEY CHECK (environment IN ('dev', 'staging', 'prod')),
    active_release_id  TEXT NOT NULL REFERENCES governed_release_manifest(release_id),
    generation         BIGINT NOT NULL CHECK (generation > 0),
    updated_by         TEXT NOT NULL,
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS release_rollout_event (
    event_id             UUID PRIMARY KEY,
    release_id           TEXT NOT NULL REFERENCES governed_release_manifest(release_id),
    manifest_digest      TEXT NOT NULL CHECK (manifest_digest ~ '^sha256:[a-f0-9]{64}$'),
    stage_percent        INTEGER NOT NULL CHECK (stage_percent IN (5, 25, 50, 100)),
    decision             TEXT NOT NULL CHECK (decision IN ('promote', 'hold', 'rollback')),
    reason_codes         TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    observation          JSONB NOT NULL,
    actor                TEXT NOT NULL,
    occurred_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS release_audit_event (
    event_id               UUID PRIMARY KEY,
    environment            TEXT NOT NULL,
    event_type             TEXT NOT NULL,
    actor                  TEXT NOT NULL,
    from_release_id        TEXT REFERENCES governed_release_manifest(release_id),
    to_release_id          TEXT REFERENCES governed_release_manifest(release_id),
    reason                 TEXT NOT NULL,
    details                JSONB NOT NULL DEFAULT '{}'::JSONB,
    previous_event_digest  TEXT,
    event_digest           TEXT NOT NULL UNIQUE CHECK (event_digest ~ '^sha256:[a-f0-9]{64}$'),
    occurred_at            TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_governed_release_environment
    ON governed_release_manifest (environment, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_release_rollout_release
    ON release_rollout_event (release_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_release_audit_environment
    ON release_audit_event (environment, occurred_at DESC);

CREATE OR REPLACE FUNCTION prevent_governed_release_mutation()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'governed release records are immutable';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_governed_release_immutable ON governed_release_manifest;
CREATE TRIGGER trg_governed_release_immutable
BEFORE UPDATE OR DELETE ON governed_release_manifest
FOR EACH ROW EXECUTE FUNCTION prevent_governed_release_mutation();

DROP TRIGGER IF EXISTS trg_release_audit_immutable ON release_audit_event;
CREATE TRIGGER trg_release_audit_immutable
BEFORE UPDATE OR DELETE ON release_audit_event
FOR EACH ROW EXECUTE FUNCTION prevent_governed_release_mutation();

DROP TRIGGER IF EXISTS trg_release_rollout_immutable ON release_rollout_event;
CREATE TRIGGER trg_release_rollout_immutable
BEFORE UPDATE OR DELETE ON release_rollout_event
FOR EACH ROW EXECUTE FUNCTION prevent_governed_release_mutation();
