-- Per-company financials (the complementary side of the CVE "two ledgers" math):
-- revenue + cost buckets (COGS/CAPEX/R&D/SG&A) let a supplier-side disclosure be
-- converted to the customer-side share and cross-checked. Admin-entered for now; a
-- licensed market-data feed wires into the same store later (MARKET_DATA_API_KEY).

CREATE TABLE IF NOT EXISTS company_financials (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    company_ticker text NOT NULL UNIQUE,
    revenue double precision,
    cogs double precision,
    capex double precision,
    rnd double precision,
    sga double precision,
    currency text,
    as_of_date date,
    source text,
    updated_at timestamptz NOT NULL DEFAULT now()
);
