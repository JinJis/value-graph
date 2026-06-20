import { proxyStudio } from "@/lib/studio";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
  return proxyStudio("/prompts");
}

export async function POST(req: Request) {
  return proxyStudio("/prompts", { method: "POST", body: await req.text() });
}
