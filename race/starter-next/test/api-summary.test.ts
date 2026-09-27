import { beforeEach, describe, expect, it } from "vitest";
import { GET } from "../app/api/summary/route";
import { getDb, resetDb } from "../lib/db";
import { body, get, seed } from "./helpers";

beforeEach(() => {
  resetDb({ groceries: 1500, transport: 2500, dining: 10000 });
});

describe("GET /api/summary", () => {
  it("returns the monthly summary and the month over month comparison", async () => {
    seed();
    const res = await GET(get("/api/summary?month=2024-03"));
    expect(res.status).toBe(200);
    expect(res.headers.get("content-type")).toBe("application/json; charset=utf-8");
    const data = await body(res);
    expect(data.summary).toEqual({
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
    expect(data.comparison).toEqual({
      month: "2024-03", previousMonth: "2024-02", currentCents: 3550, previousCents: 0, changePercent: null,
    });
    const april = await body(await GET(get("/api/summary?month=2024-04")));
    expect(april.comparison.changePercent).toBe(-71.9); // 999 vs 3550
  });

  it("includes budget statuses and alerts from the stored budgets", async () => {
    seed();
    getDb().store.add({ date: "2024-03-20", amountCents: 1000, merchant: "Chipotle" });
    const data = await body(await GET(get("/api/summary?month=2024-03")));
    expect(data.budgets).toEqual([
      { category: "groceries", budgetCents: 1500, spentCents: 1250, remainingCents: 250, percentUsed: 83, alert: "warning" },
      { category: "dining", budgetCents: 10000, spentCents: 1000, remainingCents: 9000, percentUsed: 10, alert: "ok" },
      { category: "transport", budgetCents: 2500, spentCents: 2300, remainingCents: 200, percentUsed: 92, alert: "warning" },
    ]);
    expect(data.alerts.map((s: { category: string }) => s.category)).toEqual(["groceries", "transport"]);
    const empty = await body(await GET(get("/api/summary?month=2023-01")));
    expect(empty.summary.count).toBe(0);
    expect(empty.alerts).toEqual([]);
  });

  it("returns 400 for a missing or invalid month", async () => {
    for (const query of ["", "?month=", "?month=March", "?month=2024-13", "?month=2024-3"]) {
      const res = await GET(get(`/api/summary${query}`));
      expect(res.status, query).toBe(400);
      expect(typeof (await body(res)).error).toBe("string");
    }
  });
});
