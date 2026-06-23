import { auth } from "@/auth";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// BFF: tail (resume) a background chat run's SSE. Used when the user re-enters a conversation
// whose answer is still generating — replays buffered events then continues live.
export async function GET(req: Request, { params }: { params: { id: string } }) {
  const session = await auth();
  const email = session?.user?.email;
  if (!email) return new Response("unauthorized", { status: 401 });

  const from = new URL(req.url).searchParams.get("from") ?? "0";
  const base = process.env.STUDIO_API_URL ?? "http://127.0.0.1:8004";
  const upstream = await fetch(`${base}/runs/${params.id}/stream?from_index=${from}`, {
    headers: {
      "X-Service-Token": process.env.SERVICE_TOKEN ?? "dev-service-token",
      "X-User-Email": email,
    },
  });
  if (!upstream.ok || !upstream.body) {
    return new Response("run not found", { status: upstream.status || 404 });
  }
  return new Response(upstream.body, {
    headers: { "Content-Type": "text/event-stream", "Cache-Control": "no-cache" },
  });
}
