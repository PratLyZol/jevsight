import { describe, expect, it } from "vitest";
import { alertLabel, budgetBarPercent, categoryBreakdown, changeLabel, formToExpenseBody, importSummary } from "../lib/ui";

describe("page helpers", () => {
  it("builds category breakdown rows sorted by total", () => {
    expect(categoryBreakdown({ totalCents: 22000, byCategory: { groceries: 8000, transport: 5000, dining: 9000 } })).toEqual([
      { category: "dining", totalCents: 9000, percent: 40.9 },
      { category: "groceries", totalCents: 8000, percent: 36.4 },
      { category: "transport", totalCents: 5000, percent: 22.7 },
    ]);
    expect(categoryBreakdown({ totalCents: 300, byCategory: { other: 100, travel: 100, dining: 100 } }).map((r) => r.category)).toEqual([
      "dining", "travel", "other",
    ]);
    expect(categoryBreakdown({ totalCents: 0, byCategory: {} })).toEqual([]);
  });

  it("clamps budget bars and labels alerts", () => {
    expect(budgetBarPercent({ percentUsed: 38 })).toBe(38);
    expect(budgetBarPercent({ percentUsed: 125 })).toBe(100);
    expect(budgetBarPercent({ percentUsed: -5 })).toBe(0);
    expect(alertLabel("ok")).toBe("On track");
    expect(alertLabel("warning")).toBe("Almost there");
    expect(alertLabel("over")).toBe("Over budget");
  });

  it("formats month over month change", () => {
    expect(changeLabel(10)).toBe("+10%");
    expect(changeLabel(-68.2)).toBe("-68.2%");
    expect(changeLabel(0)).toBe("0%");
    expect(changeLabel(null)).toBe("n/a");
  });

  it("turns form values into a request body", () => {
    expect(formToExpenseBody({ date: " 2024-03-09 ", amount: " $12.50 ", merchant: "  Uber ", category: "", note: "  " })).toEqual({
      date: "2024-03-09", amount: "$12.50", merchant: "Uber",
    });
    expect(formToExpenseBody({ date: "2024-03-09", amount: "3", merchant: "Kroger", category: "groceries", note: " milk " })).toEqual({
      date: "2024-03-09", amount: "3", merchant: "Kroger", category: "groceries", note: "milk",
    });
  });

  it("summarizes an import result", () => {
    expect(importSummary({ imported: [], errors: [] })).toBe("Imported 0 expenses.");
    expect(importSummary({ imported: [{} as never], errors: [] })).toBe("Imported 1 expense.");
    expect(importSummary({ imported: [{} as never, {} as never], errors: [{ line: 3, message: "bad" }] })).toBe(
      "Imported 2 expenses. 1 row had errors.",
    );
    expect(importSummary({ imported: [], errors: [{ line: 1, message: "a" }, { line: 2, message: "b" }] })).toBe(
      "Imported 0 expenses. 2 rows had errors.",
    );
  });
});
