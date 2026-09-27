import type { AddressInfo } from "node:net";
import type { Server } from "node:http";
import { afterEach, describe, expect, it } from "vitest";
import { ExpenseStore } from "../src/expenses";
import { createServer } from "../src/server";

let server: Server | undefined;

afterEach(async () => {
  if (server) {
    await new Promise<void>((resolve) => server!.close(() => resolve()));
    server = undefined;
  }
});

async function start(store = new ExpenseStore()): Promise<{ base: string; store: ExpenseStore }> {
  server = createServer(store);
  await new Promise<void>((resolve) => server!.listen(0, "127.0.0.1", () => resolve()));
  const { port } = server.address() as AddressInfo;
  return { base: `http://127.0.0.1:${port}`, store };
}

async function json(res: Response): Promise<any> {
  return res.json();
}

function seededStore(): ExpenseStore {
  const store = new ExpenseStore();
  store.add({ date: "2024-03-01", amountCents: 1250, merchant: "Whole Foods" });
  store.add({ date: "2024-03-05", amountCents: 2300, merchant: "Uber" });
  store.add({ date: "2024-04-02", amountCents: 999, merchant: "Netflix" });
  return store;
}

describe("server", () => {
  it("serves the HTML page at /", async () => {
    const { base } = await start();
    const res = await fetch(`${base}/`);
    expect(res.status).toBe(200);
    expect(res.headers.get("content-type")).toMatch(/^text\/html/);
    expect(await res.text()).toContain("<title>Expense Tracker</title>");
  });

  it("creates an expense with POST and lists it with GET", async () => {
    const { base } = await start();
    const res = await fetch(`${base}/api/expenses`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ date: "2024-03-09", amount: "$1,234.50", merchant: "Whole Foods", note: "party" }),
    });
    expect(res.status).toBe(201);
    expect(res.headers.get("content-type")).toMatch(/^application\/json/);
    const created = await json(res);
    expect(created).toEqual({ id: 1, date: "2024-03-09", amountCents: 123450, merchant: "Whole Foods", category: "groceries", note: "party" });

    const res2 = await fetch(`${base}/api/expenses`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ date: "2024-03-10", amountCents: 500, merchant: "Lyft", category: "travel" }),
    });
    expect(res2.status).toBe(201);

    const list = await json(await fetch(`${base}/api/expenses`));
    expect(list.map((e: { id: number }) => e.id)).toEqual([2, 1]);
  });

  it("returns 400 with an error message for invalid input", async () => {
    const { base, store } = await start();
    const post = (body: string) =>
      fetch(`${base}/api/expenses`, { method: "POST", headers: { "content-type": "application/json" }, body });
    for (const body of [
      JSON.stringify({ date: "2024-02-30", amount: "5", merchant: "Uber" }),
      JSON.stringify({ date: "2024-02-01", amount: "five", merchant: "Uber" }),
      JSON.stringify({ date: "2024-02-01", amount: "-5", merchant: "Uber" }),
      JSON.stringify({ date: "2024-02-01", amount: "5", merchant: "" }),
      JSON.stringify({ date: "2024-02-01", amount: "5", merchant: "Uber", category: "food" }),
      "{not json",
    ]) {
      const res = await post(body);
      expect(res.status, body).toBe(400);
      const data = await json(res);
      expect(typeof data.error).toBe("string");
    }
    expect(store.list()).toEqual([]);
  });

  it("filters GET /api/expenses with query parameters", async () => {
    const { base } = await start(seededStore());
    const ids = async (qs: string) =>
      ((await json(await fetch(`${base}/api/expenses${qs}`))) as { id: number }[]).map((e) => e.id);
    expect(await ids("")).toEqual([3, 2, 1]);
    expect(await ids("?from=2024-03-02&to=2024-03-31")).toEqual([2]);
    expect(await ids("?category=groceries")).toEqual([1]);
    expect(await ids("?merchant=NET")).toEqual([3]);
  });

  it("deletes with DELETE /api/expenses/:id", async () => {
    const { base, store } = await start(seededStore());
    const res = await fetch(`${base}/api/expenses/2`, { method: "DELETE" });
    expect(res.status).toBe(204);
    expect(store.get(2)).toBeUndefined();
    const again = await fetch(`${base}/api/expenses/2`, { method: "DELETE" });
    expect(again.status).toBe(404);
    expect(typeof (await json(again)).error).toBe("string");
    expect((await fetch(`${base}/api/expenses/abc`, { method: "DELETE" })).status).toBe(404);
  });

  it("returns the monthly summary and 404 for unknown routes", async () => {
    const { base } = await start(seededStore());
    const res = await fetch(`${base}/api/summary?month=2024-03`);
    expect(res.status).toBe(200);
    expect(await json(res)).toEqual({
      month: "2024-03",
      totalCents: 3550,
      count: 2,
      byCategory: { groceries: 1250, transport: 2300 },
      topMerchants: [
        { merchant: "Uber", totalCents: 2300 },
        { merchant: "Whole Foods", totalCents: 1250 },
      ],
      dailyAverageCents: 115,
    });
    expect((await fetch(`${base}/api/summary`)).status).toBe(400);
    expect((await fetch(`${base}/api/summary?month=March`)).status).toBe(400);
    const missing = await fetch(`${base}/api/nope`);
    expect(missing.status).toBe(404);
    expect(typeof (await json(missing)).error).toBe("string");
  });
});
