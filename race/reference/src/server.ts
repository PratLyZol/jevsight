import { readFile } from "node:fs/promises";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { NotFoundError, ValidationError } from "./errors";
import { ExpenseStore, type ExpenseFilter, type NewExpense } from "./expenses";
import { parseMoney } from "./money";
import { monthlySummary } from "./reports";

const INDEX_HTML = fileURLToPath(new URL("../public/index.html", import.meta.url));
const MAX_BODY = 1_000_000;

/**
 * Create (but do not start) an HTTP server for the JSON API and the static page.
 * The caller calls server.listen(port).
 */
export function createServer(store: ExpenseStore): http.Server {
  return http.createServer((req, res) => {
    handle(store, req, res).catch((err: unknown) => {
      if (err instanceof ValidationError) return sendJson(res, 400, { error: err.message });
      if (err instanceof NotFoundError) return sendJson(res, 404, { error: err.message });
      sendJson(res, 500, { error: "internal error" });
    });
  });
}

async function handle(store: ExpenseStore, req: http.IncomingMessage, res: http.ServerResponse): Promise<void> {
  const url = new URL(req.url ?? "/", "http://localhost");
  const method = req.method ?? "GET";
  const pathname = url.pathname;

  if (method === "GET" && (pathname === "/" || pathname === "/index.html")) {
    const html = await readFile(INDEX_HTML, "utf8");
    res.writeHead(200, { "content-type": "text/html; charset=utf-8" });
    res.end(html);
    return;
  }

  if (pathname === "/api/expenses") {
    if (method === "GET") {
      const filter: ExpenseFilter = {};
      for (const key of ["from", "to", "category", "merchant"] as const) {
        const v = url.searchParams.get(key);
        if (v !== null && v !== "") filter[key] = v;
      }
      return sendJson(res, 200, store.list(filter));
    }
    if (method === "POST") {
      const body = await readJson(req);
      const created = store.add(toNewExpense(body));
      return sendJson(res, 201, created);
    }
  }

  const idMatch = /^\/api\/expenses\/([^/]+)$/.exec(pathname);
  if (idMatch && method === "DELETE") {
    const id = /^\d+$/.test(idMatch[1]!) ? Number(idMatch[1]) : NaN;
    if (Number.isNaN(id) || !store.remove(id)) {
      return sendJson(res, 404, { error: `expense ${idMatch[1]} not found` });
    }
    res.writeHead(204);
    res.end();
    return;
  }

  if (method === "GET" && pathname === "/api/summary") {
    const month = url.searchParams.get("month");
    if (month === null) throw new ValidationError("month query parameter is required");
    return sendJson(res, 200, monthlySummary(store.list(), month));
  }

  sendJson(res, 404, { error: "not found" });
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

async function readJson(req: http.IncomingMessage): Promise<unknown> {
  const chunks: Buffer[] = [];
  let size = 0;
  for await (const chunk of req) {
    const buf = chunk as Buffer;
    size += buf.length;
    if (size > MAX_BODY) throw new ValidationError("body too large");
    chunks.push(buf);
  }
  const text = Buffer.concat(chunks).toString("utf8");
  try {
    return JSON.parse(text);
  } catch {
    throw new ValidationError("invalid JSON body");
  }
}

function sendJson(res: http.ServerResponse, status: number, data: unknown): void {
  const body = JSON.stringify(data);
  res.writeHead(status, { "content-type": "application/json; charset=utf-8" });
  res.end(body);
}

// Start the server when this file is run directly (npm start).
const isMain = process.argv[1] !== undefined && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (isMain) {
  const port = Number(process.env.PORT ?? 3000);
  const server = createServer(new ExpenseStore());
  server.listen(port, () => {
    console.log(`Expense tracker running at http://localhost:${port}`);
  });
}
