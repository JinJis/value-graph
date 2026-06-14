import { proxyStudio } from "@/lib/studio";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(req: Request) {
  const { searchParams } = new URL(req.url);
  const qs = new URLSearchParams({
    q: searchParams.get("q") ?? "",
    market: searchParams.get("market") ?? "US",
    limit: searchParams.get("limit") ?? "10",
  });
  return proxyStudio(`/company/search?${qs.toString()}`);
}
