import { notImplemented } from "../../../lib/http";

export const dynamic = "force-dynamic";

/** GET /api/export.csv (see SPEC.md) */
export async function GET(): Promise<Response> {
  return notImplemented();
}
