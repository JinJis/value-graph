/** @type {import('next').NextConfig} */

// Proxy "/engine/*" through this app's own origin to the engine API (server-side), so
// the browser only ever talks to the Terminal origin — works behind any tunnel/proxy
// with no extra port exposure and no CORS. In Docker the engine is reachable as the
// compose service name; for local dev it's localhost:8000.
const ENGINE = process.env.ENGINE_INTERNAL_URL ?? "http://localhost:8000";

const nextConfig = {
  // Transpile the shared workspace UI package (raw TS/TSX, incl. the source-highlight viewer).
  transpilePackages: ["@valuegraph/ui"],
  async rewrites() {
    return [{ source: "/engine/:path*", destination: `${ENGINE}/:path*` }];
  },
};

export default nextConfig;
