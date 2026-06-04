// Streaming proxy to the engine API.
//
// We route browser → this Studio origin → engine so the browser never needs the
// engine's port (works behind any tunnel/corp proxy, no CORS). Previously this was a
// next.config `rewrites()` entry, but that proxy BUFFERS the upstream response — fine
// for JSON, fatal for Server-Sent Events: the blueprint progress stream arrived all at
// once after 1–2 min instead of live. A Route Handler that returns `upstream.body`
// streams incrementally, so SSE events reach the UI as the engine emits them.
//
// In Docker the engine is the compose service name; for local dev it's localhost:8000.

import { type NextRequest } from "next/server";

const ENGINE = process.env.ENGINE_INTERNAL_URL ?? "http://localhost:8000";

// SSE must not be cached or statically optimized; always run on the Node runtime.
export const dynamic = "force-dynamic";
export const runtime = "nodejs";

async function proxy(
  req: NextRequest,
  ctx: { params: Promise<{ path: string[] }> },
): Promise<Response> {
  const { path } = await ctx.params;
  const target = `${ENGINE}/${path.join("/")}${req.nextUrl.search}`;

  const headers = new Headers(req.headers);
  headers.delete("host");
  headers.delete("connection");
  headers.delete("content-length"); // recomputed by fetch from the body stream

  const init: RequestInit & { duplex?: "half" } = {
    method: req.method,
    headers,
    redirect: "manual",
  };
  if (req.method !== "GET" && req.method !== "HEAD") {
    init.body = req.body;
    init.duplex = "half"; // required by undici to stream a request body
  }

  const upstream = await fetch(target, init);

  // Pass the body through unbuffered. Strip hop-by-hop / length headers that no longer
  // apply once we re-stream.
  const respHeaders = new Headers(upstream.headers);
  respHeaders.delete("content-encoding");
  respHeaders.delete("content-length");
  respHeaders.delete("transfer-encoding");

  return new Response(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: respHeaders,
  });
}

export {
  proxy as GET,
  proxy as POST,
  proxy as PUT,
  proxy as PATCH,
  proxy as DELETE,
};
