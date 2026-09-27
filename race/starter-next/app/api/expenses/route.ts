import { notImplemented } from "../../../lib/http";

export const dynamic = "force-dynamic";

/** GET /api/expenses?from=&to=&category=&merchant= (see SPEC.md) */
export async function GET(request: Request): Promise<Response> {
  return notImplemented();
}

/** POST /api/expenses with a JSON body (see SPEC.md) */
export async function POST(request: Request): Promise<Response> {
  return notImplemented();
}
