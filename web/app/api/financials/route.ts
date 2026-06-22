import { proxyStudio } from "@/lib/studio";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Income-statement history for the revenue chart — proxied through studio-api → gateway.
export async function GET(req: Request) {
  const qs = new URL(req.url).search; // ?ticker=&market=&period=&limit=
  return proxyStudio(`/financials${qs}`);
}
