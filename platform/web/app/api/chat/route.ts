import { auth } from "@/auth";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// BFF: attach the session, call studio-api /chat/stream with the trusted service
// token + the user's email, and pipe the SSE back. The platform key never reaches
// the browser.
export async function POST(req: Request) {
  const session = await auth();
  const email = session?.user?.email;
  if (!email) return new Response("unauthorized", { status: 401 });

  const upstream = await fetch(`${process.env.STUDIO_API_URL ?? "http://127.0.0.1:8004"}/chat/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Service-Token": process.env.SERVICE_TOKEN ?? "dev-service-token",
      "X-User-Email": email,
    },
    body: await req.text(),
  });

  return new Response(upstream.body, {
    headers: { "Content-Type": "text/event-stream", "Cache-Control": "no-cache" },
  });
}
