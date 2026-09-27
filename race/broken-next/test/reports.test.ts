import { describe, expect, it } from "vitest";
import { ValidationError } from "../lib/errors";
import type { Expense } from "../lib/expenses";
import { monthOverMonth, monthlySummary, previousMonthOf } from "../lib/reports";

let nextId = 1;
function exp(date: string, amountCents: number, merchant: string, category: Expense["category"]): Expense {
  return { id: nextId++, date, amountCents, merchant, category, note: "" };
}

const data: Expense[] = [
  exp("2024-02-01", 5000, "Whole Foods", "groceries"),
  exp("2024-02-10", 3000, "Whole Foods", "groceries"),
  exp("2024-02-11", 2500, "Uber", "transport"),
  exp("2024-02-12", 2500, "Lyft", "transport"),
  exp("2024-02-20", 8000, "Chipotle", "dining"),
  exp("2024-02-29", 1000, "Aardvark Cafe", "dining"),
  exp("2024-01-15", 20000, "Whole Foods", "groceries"),
  exp("2024-03-01", 7000, "Uber", "transport"),
];

describe("monthlySummary", () => {
  it("totals the month and groups by category", () => {
    const s = monthlySummary(data, "2024-02");
    expect(s.month).toBe("2024-02");
    expect(s.totalCents).toBe(22000);
    expect(s.count).toBe(6);
    expect(s.byCategory).toEqual({ groceries: 8000, transport: 5000, dining: 9000 });
  });

  it("lists the top 3 merchants, ties broken by name", () => {
    const s = monthlySummary(data, "2024-02");
    expect(s.topMerchants).toEqual([
      { merchant: "Chipotle", totalCents: 8000 },
      { merchant: "Whole Foods", totalCents: 8000 },
      { merchant: "Lyft", totalCents: 2500 },
    ]);
  });

  it("computes the daily average over every day of the month", () => {
    expect(monthlySummary(data, "2024-02").dailyAverageCents).toBe(759); // 22000 / 29 = 758.6
    expect(monthlySummary(data, "2024-01").dailyAverageCents).toBe(645); // 20000 / 31 = 645.2
    expect(monthlySummary([exp("2023-02-01", 1400, "x", "other")], "2023-02").dailyAverageCents).toBe(50);
  });

  it("returns an empty summary for a month with no expenses and rejects bad months", () => {
    expect(monthlySummary(data, "2023-07")).toEqual({
      month: "2023-07", totalCents: 0, count: 0, byCategory: {}, topMerchants: [], dailyAverageCents: 0,
    });
    expect(() => monthlySummary(data, "2024-00")).toThrow(ValidationError);
    expect(() => monthlySummary(data, "Feb 2024")).toThrow(ValidationError);
  });
});

describe("monthOverMonth", () => {
  it("computes percent change against the previous month", () => {
    expect(monthOverMonth(data, "2024-02")).toEqual({
      month: "2024-02", previousMonth: "2024-01", currentCents: 22000, previousCents: 20000, changePercent: 10,
    });
    expect(monthOverMonth(data, "2024-03").changePercent).toBe(-68.2); // 7000 vs 22000
    expect(monthOverMonth(data, "2024-01").changePercent).toBeNull();
    expect(previousMonthOf("2025-01")).toBe("2024-12");
  });
});
