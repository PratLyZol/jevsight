import { getDb } from "../../../lib/db";
import { ValidationError } from "../../../lib/errors";
import { errorJson, json } from "../../../lib/http";
import { buildSummary } from "../../../lib/summary";

export const dynamic = "force-dynamic";

/** GET /api/summary?month=YYYY-MM */
export async function GET(request: Request): Promise<Response> {
  const month = new URL(request.url).searchParams.get("month");
  if (month === null || month === "") return errorJson(400, "month query parameter is required");
  const { store, budgets } = getDb();
  try {
    return json(buildSummary(store.list(), budgets, month));
  } catch (err) {
    if (err instanceof ValidationError) return errorJson(400, err.message);
    throw err;
  }
}
