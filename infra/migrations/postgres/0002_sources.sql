-- [M1-THEME-01] Sources (uploaded Additional Context) + theme context columns.
-- A Source row is created for every uploaded file; the blob itself lives in object
-- storage, referenced by storage_key. Mirrors the graph-schema Source shape (PRD §5.1).

ALTER TABLE themes_meta ADD COLUMN IF NOT EXISTS description text;
ALTER TABLE themes_meta ADD COLUMN IF NOT EXISTS seed_tickers text[] NOT NULL DEFAULT '{}';

CREATE TABLE IF NOT EXISTS sources (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    theme_id            uuid REFERENCES themes_meta(id) ON DELETE CASCADE,
    type                text NOT NULL,                       -- filing/IR/report/news/interview
    url                 text,                                -- for link sources
    publisher           text,
    as_of_date          date,
    language            text,
    verification_status text NOT NULL DEFAULT 'unverified',
    storage_key         text,                                -- object-storage key for uploaded blobs
    original_filename   text,
    content_type        text,
    created_at          timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sources_theme ON sources (theme_id);
