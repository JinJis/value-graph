import { studioFetch } from "@/lib/studio";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// PH-PROV3: stream the cached source-filing PDF (→ studio-api → gateway → datasets) with the
// session's tenant key, for "원문 열기". 204 → the UI keeps the official source-page link.
export async function GET(req: Request) {
  const { searchParams } = new URL(req.url);
  const r = await studioFetch(`/evidence/doc?${searchParams.toString()}`);
  if (!r || r.status !== 200) return new Response(null, { status: 204 });
  const buf = await r.arrayBuffer();
  return new Response(buf, {
    status: 200,
    headers: {
      "content-type": r.headers.get("content-type") ?? "application/pdf",
      "cache-control": "private, max-age=86400",
    },
  });
}
