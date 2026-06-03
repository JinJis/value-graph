-- [M7-CAL-01] Extend the disclosure calendar with the learned cadence + last filing,
-- and make it one row per company so estimates upsert cleanly.

ALTER TABLE disclosure_calendar ADD COLUMN IF NOT EXISTS last_filing_date date;
ALTER TABLE disclosure_calendar ADD COLUMN IF NOT EXISTS cadence_days integer;

CREATE UNIQUE INDEX IF NOT EXISTS uq_disclosure_company
    ON disclosure_calendar (company_ticker);

CREATE INDEX IF NOT EXISTS idx_disclosure_next
    ON disclosure_calendar (next_filing_estimate);
