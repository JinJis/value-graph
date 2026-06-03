-- [M2-GEN-01] One ticket per (theme, target, metric). The gap->ticket generator
-- relies on this for INSERT ... ON CONFLICT DO NOTHING (idempotent, no duplicates).

CREATE UNIQUE INDEX IF NOT EXISTS uq_tickets_target_metric
    ON tickets (theme_id, target, metric);
