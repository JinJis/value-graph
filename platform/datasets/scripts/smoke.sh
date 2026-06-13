#!/usr/bin/env bash
# Smoke-test the running datasets API. Usage: BASE=http://127.0.0.1:8000 scripts/smoke.sh
# Keyless checks (Yahoo + SEC) should all be 200; keyed checks (DART/FRED/ECOS) are
# 200 only when the corresponding key is configured, else a clear 400/503.
set -u
BASE="${BASE:-http://127.0.0.1:8000}"

hit() {  # hit <path> <label>
  code=$(curl -s -o /tmp/smoke.json -w "%{http_code}" "$BASE$1")
  printf "%-4s %-46s %s\n" "$code" "$2" "$(head -c 90 /tmp/smoke.json)"
}

echo "== keyless =="
hit "/health" "health"
hit "/prices?ticker=AAPL&market=US&interval=day&start_date=2024-01-02&end_date=2024-01-08" "US prices (yahoo)"
hit "/prices/snapshot?ticker=AAPL&market=US" "US snapshot"
hit "/prices?ticker=005930&market=KR&interval=day&start_date=2024-05-02&end_date=2024-05-08" "KR prices (yahoo)"
hit "/prices/snapshot?ticker=005930&market=KR" "KR snapshot"
hit "/company/facts?ticker=AAPL&market=US" "US company facts (SEC)"
hit "/filings?ticker=AAPL&market=US&limit=3" "US filings (SEC)"
hit "/financials/income-statements?ticker=AAPL&market=US&period=annual&limit=2" "US income (SEC XBRL)"
hit "/financial-metrics/snapshot?ticker=AAPL&market=US" "US metrics (derived)"
hit "/news" "scaffold -> 501"

echo "== keyed (need OPENDART_API_KEY / FRED_API_KEY / ECOS_API_KEY) =="
hit "/company/facts?ticker=005930&market=KR" "KR company facts (DART)"
hit "/financials/income-statements?ticker=005930&market=KR&period=annual&limit=2" "KR income (DART)"
hit "/filings?ticker=005930&market=KR&limit=3" "KR filings (DART)"
hit "/financial-metrics/snapshot?ticker=005930&market=KR" "KR metrics (DART+price)"
hit "/macro/interest-rates/snapshot?bank=FED&market=US" "US macro (FRED)"
hit "/macro/interest-rates/snapshot?bank=BOK&market=KR" "KR macro (ECOS)"
