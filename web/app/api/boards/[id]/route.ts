import { proxyStudio } from "@/lib/studio";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function PATCH(req: Request, { params }: { params: { id: string } }) {
  return proxyStudio(`/boards/${params.id}`, { method: "PATCH", body: await req.text() });
}

export async function DELETE(_req: Request, { params }: { params: { id: string } }) {
  return proxyStudio(`/boards/${params.id}`, { method: "DELETE" });
}
