-- [M2-PROC-03] Link evidence Sources to the ticket they resolve. Theme-level
-- uploads (M1) leave ticket_id NULL; ticket evidence sets it.

ALTER TABLE sources ADD COLUMN IF NOT EXISTS ticket_id uuid
    REFERENCES tickets(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_sources_ticket ON sources (ticket_id);
