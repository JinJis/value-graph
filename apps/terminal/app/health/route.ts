// [M0-API-05] Liveness endpoint. Datastore readiness is added later.
export function GET() {
  return Response.json({ status: "ok", service: "terminal" });
}
