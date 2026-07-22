-- Week15 enterprise capstone product control plane.
-- Additive only: Week01-Week14 tables and teaching flows remain compatible.

ALTER TABLE customer_dim
    ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'northstar-demo';

ALTER TABLE ticket_fact
    ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'northstar-demo';

CREATE INDEX IF NOT EXISTS idx_customer_tenant
    ON customer_dim (tenant_id, customer_id);

CREATE INDEX IF NOT EXISTS idx_ticket_tenant_queue
    ON ticket_fact (tenant_id, status, priority, updated_at DESC);

CREATE TABLE IF NOT EXISTS app_user (
    user_id            TEXT PRIMARY KEY,
    tenant_id          TEXT NOT NULL,
    email              TEXT NOT NULL,
    display_name       TEXT NOT NULL,
    role               TEXT NOT NULL CHECK (
        role IN ('support_agent', 'support_lead', 'support_ops', 'billing_ops', 'admin', 'auditor')
    ),
    password_hash      TEXT NOT NULL,
    active             BOOLEAN NOT NULL DEFAULT TRUE,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_login_at      TIMESTAMPTZ,
    UNIQUE (tenant_id, email)
);

CREATE TABLE IF NOT EXISTS support_conversation (
    conversation_id    TEXT PRIMARY KEY,
    tenant_id          TEXT NOT NULL,
    ticket_id          TEXT NOT NULL REFERENCES ticket_fact(ticket_id),
    title               TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'resolved', 'archived')),
    created_by          TEXT NOT NULL REFERENCES app_user(user_id),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_conversation_ticket
    ON support_conversation (tenant_id, ticket_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS support_message (
    message_id          TEXT PRIMARY KEY,
    conversation_id    TEXT NOT NULL REFERENCES support_conversation(conversation_id),
    tenant_id           TEXT NOT NULL,
    actor_id            TEXT,
    role                TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system', 'tool')),
    content             TEXT NOT NULL,
    citations           JSONB NOT NULL DEFAULT '[]'::JSONB,
    evidence_ids        TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    confidence          DOUBLE PRECISION,
    abstain_reason      TEXT,
    trace_id            TEXT,
    release_id          TEXT,
    data_release_id     TEXT,
    index_release_id    TEXT,
    prompt_release_id   TEXT,
    graph_release_id    TEXT,
    latency_ms          INTEGER,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_message_conversation
    ON support_message (conversation_id, created_at);

CREATE INDEX IF NOT EXISTS idx_message_trace
    ON support_message (trace_id);

CREATE TABLE IF NOT EXISTS copilot_feedback (
    feedback_id         TEXT PRIMARY KEY,
    tenant_id           TEXT NOT NULL,
    message_id          TEXT NOT NULL REFERENCES support_message(message_id),
    actor_id            TEXT NOT NULL REFERENCES app_user(user_id),
    rating              SMALLINT NOT NULL CHECK (rating IN (-1, 1)),
    reason_code         TEXT,
    comment             TEXT,
    promoted_to_eval    BOOLEAN NOT NULL DEFAULT FALSE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (message_id, actor_id)
);

CREATE TABLE IF NOT EXISTS financial_adjustment (
    adjustment_id       TEXT PRIMARY KEY,
    tenant_id           TEXT NOT NULL,
    ticket_id           TEXT NOT NULL REFERENCES ticket_fact(ticket_id),
    operation           TEXT NOT NULL CHECK (operation IN ('grant_service_credit', 'refund_payment')),
    amount_cents        INTEGER NOT NULL CHECK (amount_cents >= 0),
    currency            TEXT NOT NULL CHECK (currency IN ('USD', 'CNY')),
    reason              TEXT NOT NULL,
    actor_id            TEXT NOT NULL,
    approval_id         TEXT,
    trace_id            TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'completed',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS product_audit_event (
    event_id            TEXT PRIMARY KEY,
    tenant_id           TEXT NOT NULL,
    actor_id            TEXT,
    actor_role          TEXT,
    event_type          TEXT NOT NULL,
    resource_type       TEXT NOT NULL,
    resource_id         TEXT,
    outcome             TEXT NOT NULL,
    request_id          TEXT,
    trace_id            TEXT,
    release_id          TEXT,
    details             JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_product_audit_tenant_time
    ON product_audit_event (tenant_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_product_audit_trace
    ON product_audit_event (trace_id);

ALTER TABLE hitl_approval_request
    ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'northstar-demo';

ALTER TABLE hitl_approval_request
    ADD COLUMN IF NOT EXISTS actor_id TEXT;

ALTER TABLE agent_action_lineage
    ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'northstar-demo';
