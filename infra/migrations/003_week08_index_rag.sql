-- Week08 index and RAG contract support.
-- Safe additive migration; does not rename existing Week01-Week07 tables.

ALTER TABLE knowledge_doc
    ADD COLUMN IF NOT EXISTS visibility_scope TEXT DEFAULT 'internal',
    ADD COLUMN IF NOT EXISTS entitlement_tier TEXT DEFAULT 'standard',
    ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'active',
    ADD COLUMN IF NOT EXISTS quality_status TEXT DEFAULT 'pass';

ALTER TABLE knowledge_section
    ADD COLUMN IF NOT EXISTS chunk_strategy_version TEXT,
    ADD COLUMN IF NOT EXISTS embedding_dim INT,
    ADD COLUMN IF NOT EXISTS indexed_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS index_manifest (
    index_release_id       TEXT PRIMARY KEY,
    data_release_id        TEXT NOT NULL,
    chunk_strategy_version TEXT NOT NULL,
    embedding_model        TEXT NOT NULL,
    embedding_dim          INT NOT NULL,
    provider               TEXT NOT NULL,
    built_at               TIMESTAMPTZ DEFAULT NOW(),
    source_table           TEXT NOT NULL DEFAULT 'knowledge_section',
    total_chunks           INT DEFAULT 0,
    embedded_chunks        INT DEFAULT 0,
    skipped_chunks         INT DEFAULT 0,
    error_count            INT DEFAULT 0,
    quality_gate           TEXT DEFAULT 'warn',
    notes                  TEXT,
    warnings               JSONB DEFAULT '[]'::jsonb
);

CREATE TABLE IF NOT EXISTS index_build_log (
    build_id               TEXT PRIMARY KEY DEFAULT gen_random_uuid()::TEXT,
    index_release_id       TEXT REFERENCES index_manifest(index_release_id),
    data_release_id        TEXT,
    chunk_strategy_version TEXT,
    dry_run                BOOLEAN DEFAULT FALSE,
    status                 TEXT DEFAULT 'started',
    total_chunks           INT DEFAULT 0,
    embedded_chunks        INT DEFAULT 0,
    skipped_chunks         INT DEFAULT 0,
    error_count            INT DEFAULT 0,
    report_path            TEXT,
    created_at             TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS rag_audit_log (
    audit_id               TEXT PRIMARY KEY DEFAULT gen_random_uuid()::TEXT,
    request_id             TEXT,
    trace_id               TEXT,
    question               TEXT NOT NULL,
    actor_role             TEXT,
    filters                JSONB DEFAULT '{}'::jsonb,
    retrieved_evidence_ids TEXT[] DEFAULT ARRAY[]::TEXT[],
    scores                 JSONB DEFAULT '[]'::jsonb,
    answer                 TEXT,
    confidence             DOUBLE PRECISION,
    abstain_reason         TEXT,
    release_id             TEXT,
    data_release_id        TEXT,
    index_release_id       TEXT,
    prompt_release_id      TEXT,
    latency_ms             DOUBLE PRECISION,
    created_at             TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_kdoc_week08_filters
    ON knowledge_doc (product_line, visibility_scope, entitlement_tier, status, quality_status);

CREATE INDEX IF NOT EXISTS idx_ksection_release_data
    ON knowledge_section (index_release_id, data_release_id);

CREATE INDEX IF NOT EXISTS idx_rag_audit_trace
    ON rag_audit_log (trace_id);

CREATE INDEX IF NOT EXISTS idx_rag_audit_created
    ON rag_audit_log (created_at DESC);
