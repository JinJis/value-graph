import { proxyStudio } from "@/lib/studio";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function DELETE(_req: Request, { params }: { params: { id: string; itemId: string } }) {
  return proxyStudio(`/watchlists/${params.id}/items/${params.itemId}`, { method: "DELETE" });
}
