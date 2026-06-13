-- Deep Research ticket resolution: a found answer is persisted as a reviewable
-- proposal (value + cited source URL) on the OPEN ticket. The admin accepts it
-- (attaches the cited Source -> SUBMITTED) or rejects it (clears the column).
-- Failures auto-resolve via reason_code and leave this NULL.

ALTER TABLE tickets ADD COLUMN IF NOT EXISTS research_proposal jsonb;
