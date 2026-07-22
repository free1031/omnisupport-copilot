-- Harden the Capstone runtime after the product control plane is available.
-- Existing course rows remain available but cannot share idempotency or audit
-- state with a product tenant.

ALTER TABLE tool_idempotency
    ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'course-legacy';

UPDATE tool_idempotency idempotency
SET tenant_id = ticket.tenant_id
FROM ticket_fact ticket
WHERE idempotency.result_payload->>'ticket_id' = ticket.ticket_id;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'tool_idempotency'::regclass
          AND conname = 'tool_idempotency_pkey'
          AND pg_get_constraintdef(oid) <> 'PRIMARY KEY (tenant_id, tool_name, idempotency_key)'
    ) THEN
        ALTER TABLE tool_idempotency DROP CONSTRAINT tool_idempotency_pkey;
    END IF;
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'tool_idempotency'::regclass
          AND contype = 'p'
    ) THEN
        ALTER TABLE tool_idempotency
            ADD CONSTRAINT tool_idempotency_pkey
            PRIMARY KEY (tenant_id, tool_name, idempotency_key);
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS idx_tool_idempotency_tenant_created
    ON tool_idempotency (tenant_id, created_at DESC);

ALTER TABLE audit_log
    ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'course-legacy';

CREATE INDEX IF NOT EXISTS idx_audit_log_tenant_created
    ON audit_log (tenant_id, created_at DESC);

ALTER TABLE rag_audit_log
    ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'course-legacy';

CREATE INDEX IF NOT EXISTS idx_rag_audit_tenant_created
    ON rag_audit_log (tenant_id, created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_app_user_login_email
    ON app_user (lower(email));

ALTER TABLE financial_adjustment
    DROP CONSTRAINT IF EXISTS financial_adjustment_amount_cents_check;

ALTER TABLE financial_adjustment
    ADD CONSTRAINT financial_adjustment_amount_cents_check
    CHECK (amount_cents > 0);

UPDATE hitl_approval_request approval
SET tenant_id = COALESCE(
    (
        SELECT ticket.tenant_id
        FROM ticket_fact ticket
        WHERE ticket.ticket_id = approval.payload->>'ticket_id'
    ),
    'course-legacy'
);

UPDATE agent_action_lineage lineage
SET tenant_id = COALESCE(
    (
        SELECT approval.tenant_id
        FROM hitl_approval_request approval
        WHERE approval.approval_id = lineage.approval_id
    ),
    (
        SELECT ticket.tenant_id
        FROM ticket_fact ticket
        WHERE ticket.ticket_id = lineage.output_ref
    ),
    'course-legacy'
);
