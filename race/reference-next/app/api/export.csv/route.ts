import { toCsv } from "../../../lib/csv";
import { getDb } from "../../../lib/db";
import { CSV_CONTENT_TYPE } from "../../../lib/http";

export const dynamic = "force-dynamic";

/** GET /api/export.csv */
export async function GET(): Promise<Response> {
  return new Response(toCsv(getDb().store.list()), {
    status: 200,
    headers: {
      "content-type": CSV_CONTENT_TYPE,
      "content-disposition": 'attachment; filename="expenses.csv"',
    },
  });
}
