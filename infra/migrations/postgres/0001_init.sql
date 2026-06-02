-- [M0-DB-06] Initial Postgres schema: users, themes_meta, tickets, jobs,
-- disclosure_calendar. Columns are intentionally minimal here; later milestones
-- (M2 tickets/state machine, M4 publish/jobs, M7 disclosure calendar) extend them.
-- The runner applies each migration once (tracked in schema_migrations); the
-- IF NOT EXISTS clauses make manual re-runs safe too.

CREATE TABLE IF NOT EXISTS users (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email        text NOT NULL UNIQUE,
    display_name text,
    created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS themes_meta (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name         text NOT NULL,
    version      integer NOT NULL DEFAULT 1,
    status       text NOT NULL DEFAULT 'draft',
    published_at timestamptz,
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tickets (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    theme_id         uuid REFERENCES themes_meta(id) ON DELETE CASCADE,
    target           text NOT NULL,
    metric           text NOT NULL,
    reason           text,
    status           text NOT NULL DEFAULT 'OPEN',
    reason_code      text,
    current_estimate jsonb,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS jobs (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    type       text NOT NULL,
    status     text NOT NULL DEFAULT 'PENDING',
    payload    jsonb,
    theme_id   uuid REFERENCES themes_meta(id) ON DELETE SET NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS disclosure_calendar (
    id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    company_ticker       text NOT NULL,
    fiscal_calendar      text,
    next_filing_estimate date,
    source               text,
    created_at           timestamptz NOT NULL DEFAULT now(),
    updated_at           timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_tickets_theme_status ON tickets (theme_id, status);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs (status);
CREATE INDEX IF NOT EXISTS idx_disclosure_company ON disclosure_calendar (company_ticker);
CREATE INDEX IF NOT EXISTS idx_disclosure_next_filing ON disclosure_calendar (next_filing_estimate);
