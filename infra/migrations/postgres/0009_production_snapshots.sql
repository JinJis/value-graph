-- [M4-PUB-04] Production (read-only) snapshots. Publish writes an immutable,
-- versioned snapshot per theme; Terminal reads the current (latest) one. Staging
-- edits never mutate a published snapshot — the next publish writes a NEW version.

CREATE TABLE IF NOT EXISTS production_snapshots (
    id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    theme_id             uuid NOT NULL,
    snapshot_version     integer NOT NULL,
    source_build_version integer NOT NULL,
    published_by         text NOT NULL,
    content              jsonb NOT NULL,
    published_at         timestamptz NOT NULL DEFAULT now(),
    UNIQUE (theme_id, snapshot_version)
);

CREATE INDEX IF NOT EXISTS idx_prod_snapshot_theme
    ON production_snapshots (theme_id, snapshot_version DESC);
