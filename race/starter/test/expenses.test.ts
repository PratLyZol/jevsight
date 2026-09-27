import { describe, expect, it } from "vitest";
import { NotFoundError, ValidationError } from "../src/errors";
import { ExpenseStore, isValidDate, isValidMonth } from "../src/expenses";

function seeded(): ExpenseStore {
  const store = new ExpenseStore();
  store.add({ date: "2024-03-05", amountCents: 1250, merchant: "Whole Foods" }); // 1
  store.add({ date: "2024-03-10", amountCents: 2300, merchant: "Uber" }); // 2
  store.add({ date: "2024-03-05", amountCents: 999, merchant: "Netflix" }); // 3
  store.add({ date: "2024-02-28", amountCents: 4500, merchant: "whole foods market" }); // 4
  store.add({ date: "2024-04-01", amountCents: 120000, merchant: "Sunset Apartments", category: "housing" }); // 5
  return store;
}

describe("ExpenseStore.add", () => {
  it("assigns ids from 1, trims merchant, defaults note and auto-categorizes", () => {
    const store = new ExpenseStore();
    const a = store.add({ date: "2024-01-15", amountCents: 1850, merchant: "  Uber  " });
    const b = store.add({ date: "2024-01-16", amountCents: 500, merchant: "Corner Shop", category: "groceries", note: "milk" });
    expect(a).toEqual({ id: 1, date: "2024-01-15", amountCents: 1850, merchant: "Uber", category: "transport", note: "" });
    expect(b).toEqual({ id: 2, date: "2024-01-16", amountCents: 500, merchant: "Corner Shop", category: "groceries", note: "milk" });
  });

  it("rejects amounts that are not positive integers", () => {
    const store = new ExpenseStore();
    for (const amountCents of [0, -500, 12.5, Number.NaN]) {
      expect(() => store.add({ date: "2024-01-15", amountCents, merchant: "Uber" })).toThrow(ValidationError);
    }
    expect(store.list()).toEqual([]);
  });

  it("rejects bad dates, empty merchants and unknown categories", () => {
    const store = new ExpenseStore();
    for (const date of ["2024-13-01", "2023-02-29", "2024-04-31", "2024/01/01", "24-01-01", ""]) {
      expect(() => store.add({ date, amountCents: 100, merchant: "Uber" }), date).toThrow(ValidationError);
    }
    expect(() => store.add({ date: "2024-01-01", amountCents: 100, merchant: "   " })).toThrow(ValidationError);
    expect(() => store.add({ date: "2024-01-01", amountCents: 100, merchant: "Uber", category: "food" })).toThrow(ValidationError);
    expect(store.add({ date: "2024-02-29", amountCents: 100, merchant: "Uber" }).id).toBe(1);
  });

  it("validates dates and months as helpers", () => {
    expect(isValidDate("2024-02-29")).toBe(true);
    expect(isValidDate("2023-02-29")).toBe(false);
    expect(isValidDate("2024-2-09")).toBe(false);
    expect(isValidMonth("2024-12")).toBe(true);
    expect(isValidMonth("2024-13")).toBe(false);
    expect(isValidMonth("2024-1")).toBe(false);
  });
});

describe("ExpenseStore get/remove/update", () => {
  it("gets copies and removes by id", () => {
    const store = seeded();
    const e = store.get(2)!;
    expect(e.merchant).toBe("Uber");
    e.merchant = "changed";
    expect(store.get(2)!.merchant).toBe("Uber");
    expect(store.get(99)).toBeUndefined();
    expect(store.remove(2)).toBe(true);
    expect(store.remove(2)).toBe(false);
    expect(store.get(2)).toBeUndefined();
    expect(store.add({ date: "2024-05-01", amountCents: 1, merchant: "x" }).id).toBe(6);
  });

  it("updates some fields, keeps the rest, and validates", () => {
    const store = seeded();
    const updated = store.update(1, { amountCents: 1500, note: "weekly shop" });
    expect(updated).toEqual({
      id: 1, date: "2024-03-05", amountCents: 1500, merchant: "Whole Foods", category: "groceries", note: "weekly shop",
    });
    expect(store.get(1)).toEqual(updated);
    expect(() => store.update(42, { amountCents: 1 })).toThrow(NotFoundError);
    expect(() => store.update(1, { date: "2024-02-30" })).toThrow(ValidationError);
    expect(() => store.update(1, { category: "nope" })).toThrow(ValidationError);
    expect(store.get(1)).toEqual(updated);
  });
});

describe("ExpenseStore.list", () => {
  it("sorts by date descending, then id ascending", () => {
    const ids = seeded().list().map((e) => e.id);
    expect(ids).toEqual([5, 2, 1, 3, 4]);
  });

  it("filters by inclusive date range, category and merchant substring", () => {
    const store = seeded();
    expect(store.list({ from: "2024-03-05", to: "2024-03-10" }).map((e) => e.id)).toEqual([2, 1, 3]);
    expect(store.list({ to: "2024-03-05" }).map((e) => e.id)).toEqual([1, 3, 4]);
    expect(store.list({ category: "groceries" }).map((e) => e.id)).toEqual([1, 4]);
    expect(store.list({ merchant: "WHOLE" }).map((e) => e.id)).toEqual([1, 4]);
    expect(store.list({ merchant: "foods", from: "2024-03-01" }).map((e) => e.id)).toEqual([1]);
    expect(store.list({ category: "travel" })).toEqual([]);
  });
});
