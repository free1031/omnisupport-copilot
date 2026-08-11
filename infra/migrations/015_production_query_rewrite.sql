-- Production Query Rewrite audit metadata.
-- Raw rewritten query content is intentionally not persisted; the application
-- stores hashes, lengths, model/release decisions and degradation reasons.

ALTER TABLE rag_audit_log
    ADD COLUMN IF NOT EXISTS query_rewrite JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE INDEX IF NOT EXISTS idx_rag_audit_rewrite_release_created
    ON rag_audit_log ((query_rewrite->>'prompt_release_id'), created_at DESC);

CREATE INDEX IF NOT EXISTS idx_rag_audit_rewrite_mode_created
    ON rag_audit_log ((query_rewrite->>'mode'), created_at DESC);
