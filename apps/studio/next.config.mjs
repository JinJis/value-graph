/** @type {import('next').NextConfig} */

// The engine proxy lives in app/engine/[...path]/route.ts (a streaming Route Handler),
// NOT a rewrite: next.config rewrites buffer the upstream response, which breaks the
// blueprint Server-Sent Events progress stream (it arrived all at once instead of live).
// Transpile the shared workspace UI package (raw TS/TSX, incl. the source-highlight viewer).
const nextConfig = {
  transpilePackages: ["@valuegraph/ui"],
};

export default nextConfig;
