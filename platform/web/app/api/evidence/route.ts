import { studioFetch } from "@/lib/studio";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// PH-PROV2: stream the highlighted source-filing screenshot from studio-api (→ gateway →
// datasets → renderer) with the session's tenant key. 204 → the UI shows the text card.
export async function GET(req: Request) {
  const { searchParams } = new URL(req.url);
  const r = await studioFetch(`/evidence?${searchParams.toString()}`);
  if (!r || r.status !== 200) return new Response(null, { status: 204 });
  const buf = await r.arrayBuffer();
  return new Response(buf, {
    status: 200,
    headers: {
      "content-type": r.headers.get("content-type") ?? "image/png",
      "cache-control": "private, max-age=86400",
    },
  });
}
