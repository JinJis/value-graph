import { proxyStudio } from "@/lib/studio";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// The user's boards (named canvases). GET lists (creates a default if none); POST creates one.
export async function GET() {
  return proxyStudio("/boards");
}

export async function POST(req: Request) {
  return proxyStudio("/boards", { method: "POST", body: await req.text() });
}
