import { proxyStudio } from "@/lib/studio";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
  return proxyStudio("/agents");
}

export async function POST(req: Request) {
  return proxyStudio("/agents", { method: "POST", body: await req.text() });
}
