import { proxyStudio } from "@/lib/studio";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Persisted messages of one conversation (role · content · citations) — to resume a chat.
export async function GET(_req: Request, { params }: { params: { id: string } }) {
  return proxyStudio(`/conversations/${params.id}/messages`);
}
