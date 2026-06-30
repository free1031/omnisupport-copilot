-- Week10 controlled Agent runtime tables.
-- These tables are additive and do not modify Week01-Week09 schemas.

CREATE TABLE IF NOT EXISTS tool_idempotency (
    tool_name          TEXT NOT NULL,
    idempotency_key    TEXT NOT NULL,
    args_digest        TEXT NOT NULL,
    result_payload     JSONB NOT NULL,
    trace_id           TEXT,
    release_id         TEXT,
    created_at         TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (tool_name, idempotency_key)
);

CREATE INDEX IF NOT EXISTS idx_tool_idempotency_trace
    ON tool_idempotency (trace_id);

CREATE TABLE IF NOT EXISTS hitl_approval_request (
    approval_id        TEXT PRIMARY KEY,
    trace_id           TEXT NOT NULL,
    tool_name          TEXT NOT NULL,
    action             TEXT NOT NULL,
    status             TEXT NOT NULL DEFAULT 'pending',
    reason_codes       TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    payload_digest     TEXT NOT NULL,
    payload            JSONB NOT NULL,
    reviewer           TEXT,
    decision_reason    TEXT,
    release_id         TEXT,
    created_at         TIMESTAMPTZ DEFAULT NOW(),
    decided_at         TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_hitl_status
    ON hitl_approval_request (status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_hitl_trace
    ON hitl_approval_request (trace_id);

CREATE TABLE IF NOT EXISTS agent_action_lineage (
    event_id           TEXT PRIMARY KEY,
    trace_id           TEXT NOT NULL,
    actor_id           TEXT,
    tool_name          TEXT NOT NULL,
    tool_version       TEXT NOT NULL,
    status             TEXT NOT NULL,
    approval_id        TEXT,
    audit_id           TEXT,
    data_snapshot_id   TEXT,
    evidence_ids       TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    prompt_release_id  TEXT,
    model_version      TEXT,
    skill_release_id   TEXT,
    payload_digest     TEXT NOT NULL,
    output_ref         TEXT,
    release_id         TEXT,
    created_at         TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_lineage_trace
    ON agent_action_lineage (trace_id);

CREATE INDEX IF NOT EXISTS idx_agent_lineage_tool
    ON agent_action_lineage (tool_name, created_at DESC);
