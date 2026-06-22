import { proxyStudio } from "@/lib/studio";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// The user's chat history (titles + ids), newest first.
export async function GET() {
  return proxyStudio("/conversations");
}
