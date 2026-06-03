-- [M2-SM-05] Ticket audit log (who/what/when). One row per status transition,
-- including creation (from_status NULL -> OPEN).

CREATE TABLE IF NOT EXISTS ticket_events (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    ticket_id   uuid NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    from_status text,
    to_status   text NOT NULL,
    actor       text NOT NULL,
    reason_code text,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ticket_events_ticket ON ticket_events (ticket_id, created_at);
