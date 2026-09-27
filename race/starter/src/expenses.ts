import type { Category } from "./categories";
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
  throw new Error("not implemented");
}

/** True for a month written as YYYY-MM with month 01..12. */
export function isValidMonth(value: unknown): value is string {
  throw new Error("not implemented");
}

export class ExpenseStore {
  /** Validate and store a new expense. Ids start at 1 and increase by 1. */
  add(input: NewExpense): Expense {
    throw new Error("not implemented");
  }

  /** Apply a partial change. Throws NotFoundError or ValidationError (store unchanged on error). */
  update(id: number, patch: ExpensePatch): Expense {
    throw new Error("not implemented");
  }

  /** Remove by id. Returns true if something was removed. */
  remove(id: number): boolean {
    throw new Error("not implemented");
  }

  /** Get a copy of one expense, or undefined. */
  get(id: number): Expense | undefined {
    throw new Error("not implemented");
  }

  /** Filtered copies, sorted by date descending, then id ascending. */
  list(filter: ExpenseFilter = {}): Expense[] {
    throw new Error("not implemented");
  }
}
