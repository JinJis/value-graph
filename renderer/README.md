# renderer — evidence screenshot service (PH-PROV2)

Internal-only microservice that turns a precomputed SEC inline-XBRL fact locator into a
**highlighted screenshot of the real filing**. Reached only from `datasets` (`RENDERER_URL`);
not exposed through the gateway directly.

- `POST /render/sec {doc_url, accession, element_id?|selector?}` → `image/png` (the element's
  row/table region with the cited figure highlighted in amber). Cache-first on `/cache`
  (volume) keyed by `(accession, locator, renderer_version)`; the headless render runs at most
  once per fact. `502` on render failure → datasets returns `204` → the UI falls back to the
  text source card. Never `500`s.
- `GET /health`.

Heavy Chromium dependency is isolated here (Playwright base image). Tests
(`uv run --extra dev pytest`) cover the cache + routing without launching a browser.
