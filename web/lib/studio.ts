import { auth } from "@/auth";

// Server-only helper: call studio-api with the trusted service token + the
// authenticated user's email. The platform key stays in studio-api; the browser
// only ever holds an Auth.js session.
export async function studioFetch(path: string, init: RequestInit = {}): Promise<Response | null> {
  const session = await auth();
  const email = session?.user?.email;
  if (!email) return null;
  const base = process.env.STUDIO_API_URL ?? "http://127.0.0.1:8004";
  return fetch(`${base}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      "X-Service-Token": process.env.SERVICE_TOKEN ?? "dev-service-token",
      "X-User-Email": email,
      ...(init.headers ?? {}),
    },
  });
}

// Proxy a JSON studio-api response straight back to the browser.
export async function proxyStudio(path: string, init: RequestInit = {}): Promise<Response> {
  const r = await studioFetch(path, init);
  if (!r) return new Response(JSON.stringify({ error: "unauthorized" }), { status: 401 });
  return new Response(await r.text(), {
    status: r.status,
    headers: { "Content-Type": "application/json" },
  });
}
