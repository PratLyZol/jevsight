import { isCategory } from "../../../lib/categories";
import { getDb } from "../../../lib/db";
import { NotFoundError, ValidationError } from "../../../lib/errors";
import { isValidDate, type ExpenseFilter, type NewExpense } from "../../../lib/expenses";
import { errorJson, json } from "../../../lib/http";
import { parseMoney } from "../../../lib/money";

export const dynamic = "force-dynamic";

/** GET /api/expenses?from=&to=&category=&merchant= */
export async function GET(request: Request): Promise<Response> {
  const params = new URL(request.url).searchParams;
  const filter: ExpenseFilter = {};
  for (const key of ["from", "to", "category", "merchant"] as const) {
    const value = params.get(key);
    if (value !== null && value !== "") filter[key] = value;
  }
  if (filter.from !== undefined && !isValidDate(filter.from)) return errorJson(400, `invalid from date: ${filter.from}`);
  if (filter.to !== undefined && !isValidDate(filter.to)) return errorJson(400, `invalid to date: ${filter.to}`);
  if (filter.category !== undefined && !isCategory(filter.category)) {
    return errorJson(400, `unknown category: ${filter.category}`);
  }
  return json(getDb().store.list(filter));
}

/** POST /api/expenses with a JSON body. */
export async function POST(request: Request): Promise<Response> {
  let body: unknown;
  try {
    body = JSON.parse(await request.text());
  } catch {
    return errorJson(400, "invalid JSON body");
  }
  try {
    const created = getDb().store.add(toNewExpense(body));
    return json(created, 201);
  } catch (err) {
    if (err instanceof ValidationError) return errorJson(400, err.message);
    if (err instanceof NotFoundError) return errorJson(404, err.message);
    throw err;
  }
}

function toNewExpense(body: unknown): NewExpense {
  if (typeof body !== "object" || body === null || Array.isArray(body)) {
    throw new ValidationError("body must be a JSON object");
  }
  const b = body as Record<string, unknown>;
  let amountCents: number;
  if (typeof b.amountCents === "number") {
    amountCents = b.amountCents;
  } else if (typeof b.amount === "string") {
    amountCents = parseMoney(b.amount);
  } else {
    throw new ValidationError("amount or amountCents is required");
  }
  const out: NewExpense = {
    date: typeof b.date === "string" ? b.date : "",
    amountCents,
    merchant: typeof b.merchant === "string" ? b.merchant : "",
  };
  if (b.category !== undefined) out.category = typeof b.category === "string" ? b.category : String(b.category);
  if (b.note !== undefined) {
    if (typeof b.note !== "string") throw new ValidationError("note must be a string");
    out.note = b.note;
  }
  return out;
}
