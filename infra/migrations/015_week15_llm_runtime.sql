-- Persist the actual generation runtime so product answers are auditable.

ALTER TABLE support_message
    ADD COLUMN IF NOT EXISTS generation_mode TEXT,
    ADD COLUMN IF NOT EXISTS generation_provider TEXT,
    ADD COLUMN IF NOT EXISTS generation_model TEXT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ck_support_message_generation_mode'
    ) THEN
        ALTER TABLE support_message
            ADD CONSTRAINT ck_support_message_generation_mode
            CHECK (
                generation_mode IS NULL
                OR generation_mode IN ('llm', 'deterministic_fallback', 'not_invoked')
            );
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_support_message_generation_runtime
    ON support_message (generation_provider, generation_model, created_at DESC)
    WHERE role = 'assistant';
