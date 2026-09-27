import { describe, expect, it } from "vitest";
import { CSV_HEADER, fromCsv, toCsv } from "../lib/csv";
import type { Expense } from "../lib/expenses";

const expenses: Expense[] = [
  { id: 1, date: "2024-03-01", amountCents: 1250, merchant: "Whole Foods", category: "groceries", note: "" },
  { id: 2, date: "2024-03-02", amountCents: 123456, merchant: "Joe's Diner, Downtown", category: "dining", note: 'said "thanks"' },
  { id: 3, date: "2024-03-03", amountCents: 5, merchant: "Uber", category: "transport", note: "line one\nline two" },
];

describe("toCsv", () => {
  it("writes a header and quotes fields with commas, quotes or newlines", () => {
    expect(CSV_HEADER).toBe("id,date,amount,merchant,category,note");
    expect(toCsv(expenses)).toBe(
      "id,date,amount,merchant,category,note\n" +
        "1,2024-03-01,12.50,Whole Foods,groceries,\n" +
        '2,2024-03-02,1234.56,"Joe\'s Diner, Downtown",dining,"said ""thanks"""\n' +
        '3,2024-03-03,0.05,Uber,transport,"line one\nline two"\n',
    );
    expect(toCsv([])).toBe("id,date,amount,merchant,category,note\n");
  });
});

describe("fromCsv", () => {
  it("round-trips exported expenses", () => {
    const result = fromCsv(toCsv(expenses));
    expect(result.errors).toEqual([]);
    expect(result.rows).toEqual(
      expenses.map((e) => ({ date: e.date, amountCents: e.amountCents, merchant: e.merchant, category: e.category, note: e.note })),
    );
  });

  it("reports bad rows with line numbers and keeps the good ones", () => {
    const text = [
      "id,date,amount,merchant,category,note",
      "1,2024-03-01,12.50,Whole Foods,groceries,ok", // line 2 ok
      "2,2024-02-30,5.00,Uber,transport,", // line 3 bad date
      "3,2024-03-02,abc,Uber,transport,", // line 4 bad amount
      "4,2024-03-02,0,Uber,transport,", // line 5 amount must be > 0
      "5,2024-03-02,1.00,   ,transport,", // line 6 empty merchant
      "6,2024-03-02,1.00,Uber,food,", // line 7 unknown category
      "7,2024-03-02,1.00,Uber", // line 8 wrong field count
      "8,2024-03-04,7.25,Lyft,transport,late", // line 9 ok
    ].join("\n");
    const result = fromCsv(text);
    expect(result.errors.map((e) => e.line)).toEqual([3, 4, 5, 6, 7, 8]);
    for (const e of result.errors) expect(e.message.length).toBeGreaterThan(0);
    expect(result.rows).toEqual([
      { date: "2024-03-01", amountCents: 1250, merchant: "Whole Foods", category: "groceries", note: "ok" },
      { date: "2024-03-04", amountCents: 725, merchant: "Lyft", category: "transport", note: "late" },
    ]);
  });

  it("handles CRLF, blank lines, quoted amounts, empty category and multi-line fields", () => {
    const text =
      "id,date,amount,merchant,category,note\r\n" +
      '1,2024-03-01,"$1,234.56",Target,,"two\r\nlines"\r\n' + // lines 2-3
      "\r\n" + // line 4 blank
      "2,2024-13-01,1.00,Uber,,\r\n" + // line 5 bad date
      "3,2024-03-05,3,Uber,,\r\n"; // line 6 ok
    const result = fromCsv(text);
    expect(result.errors.map((e) => e.line)).toEqual([5]);
    expect(result.rows).toEqual([
      { date: "2024-03-01", amountCents: 123456, merchant: "Target", note: "two\r\nlines" },
      { date: "2024-03-05", amountCents: 300, merchant: "Uber", note: "" },
    ]);
  });

  it("reports a missing or wrong header as a line 1 error", () => {
    expect(fromCsv("date,amount\n2024-01-01,5")).toEqual({ rows: [], errors: [{ line: 1, message: expect.any(String) }] });
    expect(fromCsv("")).toEqual({ rows: [], errors: [{ line: 1, message: expect.any(String) }] });
  });
});
