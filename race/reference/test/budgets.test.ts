import { describe, expect, it } from "vitest";
import { budgetAlerts, budgetStatus } from "../src/budgets";
import { ValidationError } from "../src/errors";
import type { Expense } from "../src/expenses";

let nextId = 1;
function exp(date: string, amountCents: number, category: Expense["category"], merchant = "m"): Expense {
  return { id: nextId++, date, amountCents, merchant, category, note: "" };
}

const expenses: Expense[] = [
  exp("2024-03-01", 10000, "groceries"),
  exp("2024-03-15", 5000, "groceries"),
  exp("2024-02-28", 99999, "groceries"),
  exp("2024-03-03", 8000, "dining"),
  exp("2024-03-20", 3000, "transport"),
  exp("2024-04-01", 5000, "transport"),
];

describe("budgetStatus", () => {
  it("computes spent, remaining and percent for the month, in category order", () => {
    const result = budgetStatus(expenses, { transport: 10000, groceries: 40000, travel: 50000 }, "2024-03");
    expect(result).toEqual([
      { category: "groceries", budgetCents: 40000, spentCents: 15000, remainingCents: 25000, percentUsed: 38, alert: "ok" },
      { category: "transport", budgetCents: 10000, spentCents: 3000, remainingCents: 7000, percentUsed: 30, alert: "ok" },
      { category: "travel", budgetCents: 50000, spentCents: 0, remainingCents: 50000, percentUsed: 0, alert: "ok" },
    ]);
  });

  it("raises a warning at 80% and over at 100%", () => {
    const month = [exp("2024-05-02", 7999, "groceries"), exp("2024-05-02", 8000, "dining"), exp("2024-05-02", 10000, "health"), exp("2024-05-02", 12500, "travel")];
    const result = budgetStatus(month, { groceries: 10000, dining: 10000, health: 10000, travel: 10000 }, "2024-05");
    expect(result.map((s) => [s.category, s.alert, s.percentUsed, s.remainingCents])).toEqual([
      ["groceries", "ok", 80, 2001],
      ["dining", "warning", 80, 2000],
      ["health", "over", 100, 0],
      ["travel", "over", 125, -2500],
    ]);
    expect(budgetAlerts(result).map((s) => s.category)).toEqual(["dining", "health", "travel"]);
  });

  it("rejects a bad month or a non-positive budget", () => {
    expect(() => budgetStatus(expenses, { groceries: 100 }, "2024-3")).toThrow(ValidationError);
    expect(() => budgetStatus(expenses, { groceries: 0 }, "2024-03")).toThrow(ValidationError);
    expect(() => budgetStatus(expenses, { groceries: 10.5 }, "2024-03")).toThrow(ValidationError);
    expect(budgetStatus(expenses, {}, "2024-03")).toEqual([]);
  });
});
