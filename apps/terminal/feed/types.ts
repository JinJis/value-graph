// [M6-FEED-04] Live Context Feed item (mirrors the engine FeedItem). Raw context —
// there is no score / momentum / forecast field, by design.

export interface FeedItem {
  id: string;
  theme_id: string;
  title: string;
  url: string;
  source_type: string; // news | interview | filing
  publisher: string | null;
  published_at: string;
  snippet: string | null;
  entities: string[]; // linked tickers
  created_at: string;
}
