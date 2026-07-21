-- Week13 GraphRAG derived assets.
-- Additive and idempotent: no Week01-Week12 table is renamed or dropped.

CREATE TABLE IF NOT EXISTS graph_release (
    graph_release_id       TEXT PRIMARY KEY,
    schema_version         TEXT NOT NULL,
    data_release_ids       TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    index_release_id       TEXT,
    build_status           TEXT NOT NULL DEFAULT 'building'
                           CHECK (build_status IN ('building', 'active', 'warn', 'failed', 'deprecated')),
    source_chunk_count     INTEGER NOT NULL DEFAULT 0,
    entity_count           INTEGER NOT NULL DEFAULT 0,
    edge_count             INTEGER NOT NULL DEFAULT 0,
    community_count        INTEGER NOT NULL DEFAULT 0,
    quarantine_count       INTEGER NOT NULL DEFAULT 0,
    build_report           JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    activated_at           TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS graph_evidence_projection (
    graph_release_id       TEXT NOT NULL REFERENCES graph_release(graph_release_id) ON DELETE CASCADE,
    evidence_id            TEXT NOT NULL,
    chunk_id               TEXT NOT NULL,
    doc_id                 TEXT NOT NULL,
    source_id              TEXT NOT NULL,
    content                TEXT NOT NULL,
    section_path           TEXT NOT NULL,
    page_no                INTEGER,
    title                  TEXT,
    bbox                   TEXT,
    source_url             TEXT,
    doc_version            TEXT,
    data_release_id        TEXT NOT NULL,
    product_line           TEXT NOT NULL DEFAULT 'any',
    visibility_scope       TEXT NOT NULL DEFAULT 'internal',
    created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (graph_release_id, evidence_id)
);

CREATE TABLE IF NOT EXISTS graph_entity_node (
    graph_release_id       TEXT NOT NULL REFERENCES graph_release(graph_release_id) ON DELETE CASCADE,
    entity_id              TEXT NOT NULL,
    entity_type            TEXT NOT NULL,
    canonical_name         TEXT NOT NULL,
    normalized_name        TEXT NOT NULL,
    properties             JSONB NOT NULL DEFAULT '{}'::JSONB,
    chunk_ids              TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    evidence_ids           TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    data_release_id        TEXT NOT NULL,
    product_line           TEXT NOT NULL DEFAULT 'any',
    visibility_scope       TEXT NOT NULL DEFAULT 'internal',
    confidence             DOUBLE PRECISION NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (graph_release_id, entity_id)
);

CREATE TABLE IF NOT EXISTS graph_entity_alias (
    graph_release_id       TEXT NOT NULL,
    entity_id              TEXT NOT NULL,
    alias                  TEXT NOT NULL,
    normalized_alias       TEXT NOT NULL,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (graph_release_id, entity_id, normalized_alias),
    FOREIGN KEY (graph_release_id, entity_id)
        REFERENCES graph_entity_node(graph_release_id, entity_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS graph_relation_edge (
    graph_release_id       TEXT NOT NULL REFERENCES graph_release(graph_release_id) ON DELETE CASCADE,
    edge_id                TEXT NOT NULL,
    relation_type          TEXT NOT NULL,
    source_entity_id       TEXT NOT NULL,
    target_entity_id       TEXT NOT NULL,
    properties             JSONB NOT NULL DEFAULT '{}'::JSONB,
    chunk_ids              TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    evidence_ids           TEXT[] NOT NULL,
    data_release_id        TEXT NOT NULL,
    confidence             DOUBLE PRECISION NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    valid_from             TIMESTAMPTZ,
    valid_to               TIMESTAMPTZ,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (graph_release_id, edge_id),
    FOREIGN KEY (graph_release_id, source_entity_id)
        REFERENCES graph_entity_node(graph_release_id, entity_id) ON DELETE CASCADE,
    FOREIGN KEY (graph_release_id, target_entity_id)
        REFERENCES graph_entity_node(graph_release_id, entity_id) ON DELETE CASCADE,
    CHECK (source_entity_id <> target_entity_id),
    CHECK (cardinality(evidence_ids) > 0)
);

CREATE TABLE IF NOT EXISTS graph_community (
    graph_release_id       TEXT NOT NULL REFERENCES graph_release(graph_release_id) ON DELETE CASCADE,
    community_id           TEXT NOT NULL,
    level                  INTEGER NOT NULL DEFAULT 0,
    summary                TEXT NOT NULL,
    member_count           INTEGER NOT NULL DEFAULT 0,
    evidence_ids           TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    product_lines          TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    visibility_scopes      TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    summary_strategy       TEXT NOT NULL DEFAULT 'deterministic_v1',
    created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (graph_release_id, community_id)
);

ALTER TABLE graph_community
    ADD COLUMN IF NOT EXISTS product_lines TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    ADD COLUMN IF NOT EXISTS visibility_scopes TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[];

ALTER TABLE graph_entity_node
    DROP CONSTRAINT IF EXISTS graph_entity_node_graph_release_id_entity_type_normalized_name_key;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_graph_entity_scope_name'
    ) THEN
        ALTER TABLE graph_entity_node
            ADD CONSTRAINT uq_graph_entity_scope_name
            UNIQUE (graph_release_id, entity_type, normalized_name, product_line, visibility_scope);
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS graph_community_member (
    graph_release_id       TEXT NOT NULL,
    community_id           TEXT NOT NULL,
    entity_id              TEXT NOT NULL,
    PRIMARY KEY (graph_release_id, community_id, entity_id),
    FOREIGN KEY (graph_release_id, community_id)
        REFERENCES graph_community(graph_release_id, community_id) ON DELETE CASCADE,
    FOREIGN KEY (graph_release_id, entity_id)
        REFERENCES graph_entity_node(graph_release_id, entity_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS graph_build_quarantine (
    quarantine_id         TEXT PRIMARY KEY DEFAULT gen_random_uuid()::TEXT,
    graph_release_id       TEXT NOT NULL REFERENCES graph_release(graph_release_id) ON DELETE CASCADE,
    kind                   TEXT NOT NULL,
    reason                 TEXT NOT NULL,
    payload                JSONB NOT NULL,
    review_status          TEXT NOT NULL DEFAULT 'pending'
                           CHECK (review_status IN ('pending', 'approved', 'rejected')),
    created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reviewed_at            TIMESTAMPTZ,
    reviewed_by            TEXT
);

CREATE INDEX IF NOT EXISTS idx_graph_entity_lookup
    ON graph_entity_node (graph_release_id, entity_type, normalized_name);
CREATE INDEX IF NOT EXISTS idx_graph_entity_scope
    ON graph_entity_node (graph_release_id, product_line, visibility_scope);
CREATE INDEX IF NOT EXISTS idx_graph_alias_lookup
    ON graph_entity_alias (graph_release_id, normalized_alias);
CREATE INDEX IF NOT EXISTS idx_graph_edge_source
    ON graph_relation_edge (graph_release_id, source_entity_id, relation_type);
CREATE INDEX IF NOT EXISTS idx_graph_edge_target
    ON graph_relation_edge (graph_release_id, target_entity_id, relation_type);
CREATE INDEX IF NOT EXISTS idx_graph_community_size
    ON graph_community (graph_release_id, member_count DESC);
CREATE INDEX IF NOT EXISTS idx_graph_evidence_scope
    ON graph_evidence_projection (graph_release_id, product_line, visibility_scope);
