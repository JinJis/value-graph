import { proxyStudio } from "@/lib/studio";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// The run still generating for this conversation (if any) — lets the desk resume a live
// answer when the user re-enters a conversation whose generation is still in flight.
export async function GET(_req: Request, { params }: { params: { id: string } }) {
  return proxyStudio(`/conversations/${params.id}/active-run`);
}
