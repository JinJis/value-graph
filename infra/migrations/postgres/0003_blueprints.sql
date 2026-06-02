-- [M1-BLU-02] Blueprints — the LLM-analyzed plan of what to build for a theme.
-- Versioned per theme (iterative refinement adds versions in M1-BLU-03). The
-- companies/relationship_types/notes payload is stored as jsonb.

CREATE TABLE IF NOT EXISTS blueprints (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    theme_id     uuid NOT NULL REFERENCES themes_meta(id) ON DELETE CASCADE,
    version      integer NOT NULL,
    content      jsonb NOT NULL,
    generated_by text,
    created_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (theme_id, version)
);

CREATE INDEX IF NOT EXISTS idx_blueprints_theme ON blueprints (theme_id);
