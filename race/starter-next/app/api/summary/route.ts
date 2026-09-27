import { notImplemented } from "../../../lib/http";

export const dynamic = "force-dynamic";

/** GET /api/summary?month=YYYY-MM (see SPEC.md) */
export async function GET(request: Request): Promise<Response> {
  return notImplemented();
}
