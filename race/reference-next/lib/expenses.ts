import { categorize, isCategory, type Category } from "./categories";
import { NotFoundError, ValidationError } from "./errors";
import type { Cents } from "./money";

export interface Expense {
  id: number;
  /** YYYY-MM-DD */
  date: string;
  amountCents: Cents;
  merchant: string;
  category: Category;
  note: string;
}

export interface NewExpense {
  date: string;
  amountCents: Cents;
  merchant: string;
  /** If omitted (or empty string), the category is chosen with categorize(merchant). */
  category?: string;
  note?: string;
}

export type ExpensePatch = Partial<NewExpense>;

export interface ExpenseFilter {
  /** Inclusive lower bound, YYYY-MM-DD. */
  from?: string;
  /** Inclusive upper bound, YYYY-MM-DD. */
  to?: string;
  category?: string;
  /** Case-insensitive substring of the merchant name. */
  merchant?: string;
}

/** True for a real calendar date written as YYYY-MM-DD (for example "2024-02-29" but not "2023-02-29"). */
export function isValidDate(value: unknown): value is string {
  if (typeof value !== "string") return false;
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!m) return false;
  const year = Number(m[1]);
  const month = Number(m[2]);
  const day = Number(m[3]);
  if (month < 1 || month > 12 || day < 1) return false;
  return day <= new Date(Date.UTC(year, month, 0)).getUTCDate();
}

/** True for a month written as YYYY-MM with month 01..12. */
export function isValidMonth(value: unknown): value is string {
  if (typeof value !== "string") return false;
  const m = /^(\d{4})-(\d{2})$/.exec(value);
  if (!m) return false;
  const month = Number(m[2]);
  return month >= 1 && month <= 12;
}

export class ExpenseStore {
  private items = new Map<number, Expense>();
  private nextId = 1;

  /** Validate and store a new expense. Ids start at 1 and increase by 1. */
  add(input: NewExpense): Expense {
    const expense = buildExpense(this.nextId, input);
    this.nextId += 1;
    this.items.set(expense.id, expense);
    return { ...expense };
  }

  /** Apply a partial change. Throws NotFoundError or ValidationError (store unchanged on error). */
  update(id: number, patch: ExpensePatch): Expense {
    const current = this.items.get(id);
    if (!current) throw new NotFoundError(`expense ${id} not found`);
    const merged: NewExpense = {
      date: patch.date ?? current.date,
      amountCents: patch.amountCents ?? current.amountCents,
      merchant: patch.merchant ?? current.merchant,
      category: patch.category ?? current.category,
      note: patch.note ?? current.note,
    };
    const updated = buildExpense(id, merged);
    this.items.set(id, updated);
    return { ...updated };
  }

  /** Remove by id. Returns true if something was removed. */
  remove(id: number): boolean {
    return this.items.delete(id);
  }

  /** Get a copy of one expense, or undefined. */
  get(id: number): Expense | undefined {
    const e = this.items.get(id);
    return e ? { ...e } : undefined;
  }

  /** Filtered copies, sorted by date descending, then id ascending. */
  list(filter: ExpenseFilter = {}): Expense[] {
    const needle = filter.merchant?.trim().toLowerCase();
    const result: Expense[] = [];
    for (const e of this.items.values()) {
      if (filter.from !== undefined && e.date < filter.from) continue;
      if (filter.to !== undefined && e.date > filter.to) continue;
      if (filter.category !== undefined && e.category !== filter.category) continue;
      if (needle && !e.merchant.toLowerCase().includes(needle)) continue;
      result.push({ ...e });
    }
    result.sort((a, b) => (a.date === b.date ? a.id - b.id : a.date < b.date ? 1 : -1));
    return result;
  }
}

function buildExpense(id: number, input: NewExpense): Expense {
  if (!Number.isSafeInteger(input.amountCents) || input.amountCents <= 0) {
    throw new ValidationError("amountCents must be a positive integer");
  }
  if (!isValidDate(input.date)) {
    throw new ValidationError(`invalid date: ${String(input.date)}`);
  }
  const merchant = typeof input.merchant === "string" ? input.merchant.trim() : "";
  if (merchant === "") {
    throw new ValidationError("merchant is required");
  }
  let category: Category;
  if (input.category === undefined || input.category === "") {
    category = categorize(merchant);
  } else if (isCategory(input.category)) {
    category = input.category;
  } else {
    throw new ValidationError(`unknown category: ${String(input.category)}`);
  }
  const note = input.note ?? "";
  if (typeof note !== "string") {
    throw new ValidationError("note must be a string");
  }
  return { id, date: input.date, amountCents: input.amountCents, merchant, category, note };
}
