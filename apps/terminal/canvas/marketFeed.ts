// [M5-CANVAS-01] Market feed — node size binds to (live or delayed/mock) market cap.
//
// A real deployment needs a LICENSED price/market-cap feed (CLAUDE.md §6); until one
// is wired, default to a deterministic MOCK so the canvas binding is exercised. Swap
// MockMarketFeed for a LicensedMarketFeed implementing the same interface — the canvas
// reads market caps only through this seam.

export interface MarketFeed {
  // Market cap (USD) for a ticker, or null if unknown (drawn at a floor size).
  marketCap(ticker: string): number | null;
  // True when values are real-time/licensed; false for delayed/mock (shown in the UI).
  readonly live: boolean;
}

function hash(ticker: string): number {
  let h = 2166136261;
  for (let i = 0; i < ticker.length; i++) {
    h ^= ticker.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

// Deterministic pseudo-caps in a plausible range (~$10B..~$3T) so node sizes vary
// stably across reloads without a real feed.
export class MockMarketFeed implements MarketFeed {
  readonly live = false;

  marketCap(ticker: string): number | null {
    if (!ticker) return null;
    const r = hash(ticker) / 0xffffffff; // 0..1
    return 10e9 + r * r * 2_990e9;
  }
}

export const mockMarketFeed = new MockMarketFeed();
