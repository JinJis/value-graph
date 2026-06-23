import { proxyStudio } from "@/lib/studio";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function DELETE(_req: Request, { params }: { params: { id: string } }) {
  return proxyStudio(`/board/${params.id}`, { method: "DELETE" });
}

export async function PATCH(req: Request, { params }: { params: { id: string } }) {
  return proxyStudio(`/board/${params.id}`, { method: "PATCH", body: await req.text() });
}
