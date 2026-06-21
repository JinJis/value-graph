import { proxyStudio } from "@/lib/studio";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// PH-DATA-5 / PH-9: a company's reported KPIs, each cited to its filing passage.
export async function POST(req: Request) {
  return proxyStudio("/kpis", { method: "POST", body: await req.text() });
}
