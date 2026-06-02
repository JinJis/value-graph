-- [M1-BLU-03] Per-round refinement metadata (round/added/updated/delta/converged).
-- Each refinement round persists a new blueprint version; round_meta on that row is
-- the round log. The sequence of versions for a theme = the full refinement log.

ALTER TABLE blueprints ADD COLUMN IF NOT EXISTS round_meta jsonb;
