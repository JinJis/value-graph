import { proxyStudio } from "@/lib/studio";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Historical OHLCV for the trader chart — proxied through studio-api → gateway (entitled).
export async function GET(req: Request) {
  const qs = new URL(req.url).search; // ?ticker=&market=&interval=&start_date=&end_date=
  return proxyStudio(`/prices${qs}`);
}
