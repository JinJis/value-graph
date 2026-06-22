import { proxyStudio } from "@/lib/studio";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(req: Request) {
  const bid = new URL(req.url).searchParams.get("board_id");
  return proxyStudio(`/board${bid ? `?board_id=${encodeURIComponent(bid)}` : ""}`);
}

export async function POST(req: Request) {
  return proxyStudio("/board", { method: "POST", body: await req.text() });
}
