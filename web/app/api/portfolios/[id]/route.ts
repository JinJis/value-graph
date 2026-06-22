import { proxyStudio } from "@/lib/studio";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(_req: Request, { params }: { params: { id: string } }) {
  return proxyStudio(`/portfolios/${params.id}`);
}
export async function DELETE(_req: Request, { params }: { params: { id: string } }) {
  return proxyStudio(`/portfolios/${params.id}`, { method: "DELETE" });
}
