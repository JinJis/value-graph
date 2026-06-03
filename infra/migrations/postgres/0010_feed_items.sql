-- [M6-FEED-04] Live Context Feed items: raw news / interviews / filings, entity-linked
-- to companies (tickers in the `entities` jsonb array). Context only — no score,
-- momentum, or forecast columns exist by design.

CREATE TABLE IF NOT EXISTS feed_items (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    theme_id     uuid NOT NULL,
    title        text NOT NULL,
    url          text NOT NULL,
    source_type  text NOT NULL DEFAULT 'news',
    publisher    text,
    published_at timestamptz NOT NULL,
    snippet      text,
    entities     jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_feed_theme_time
    ON feed_items (theme_id, published_at DESC);

-- GIN index supports the `entities ? ticker` node-select filter.
CREATE INDEX IF NOT EXISTS idx_feed_entities ON feed_items USING gin (entities);
