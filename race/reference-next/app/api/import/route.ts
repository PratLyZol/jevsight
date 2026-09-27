import type { ImportResponse } from "../../../lib/api-types";
import { fromCsv } from "../../../lib/csv";
import { getDb } from "../../../lib/db";
import { json } from "../../../lib/http";

export const dynamic = "force-dynamic";

/** POST /api/import with raw CSV text as the body. */
export async function POST(request: Request): Promise<Response> {
  const { rows, errors } = fromCsv(await request.text());
  const { store } = getDb();
  const body: ImportResponse = { imported: rows.map((row) => store.add(row)), errors };
  return json(body);
}
