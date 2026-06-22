import { proxyStudio } from "@/lib/studio";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function DELETE(_req: Request, { params }: { params: { id: string; hid: string } }) {
  return proxyStudio(`/portfolios/${params.id}/holdings/${params.hid}`, { method: "DELETE" });
}
