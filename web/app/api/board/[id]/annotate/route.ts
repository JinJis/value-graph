import { proxyStudio } from "@/lib/studio";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// PH-VIZ-5: persist the user's drawings (user_annotations) on a pinned chart.
export async function POST(req: Request, { params }: { params: { id: string } }) {
  return proxyStudio(`/board/${params.id}/annotate`, { method: "POST", body: await req.text() });
}
