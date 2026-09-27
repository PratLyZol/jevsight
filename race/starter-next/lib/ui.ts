import type { ExpenseBody, ImportResponse } from "./api-types";
import type { BudgetAlert, BudgetStatus } from "./budgets";
import type { Category } from "./categories";
import type { Cents } from "./money";
import type { MonthlySummary } from "./reports";

/** Raw string values of the add-expense form on the home page. */
export interface ExpenseFormValues {
  date: string;
  amount: string;
  merchant: string;
  /** "" means "pick automatically". */
  category: string;
  note: string;
}

export interface CategoryRow {
  category: Category;
  totalCents: Cents;
  /** Share of the month total, rounded to 1 decimal. */
  percent: number;
}

/**
 * Rows for the category breakdown table: one per category in `byCategory`,
 * sorted by total descending, ties in CATEGORIES order.
 */
export function categoryBreakdown(summary: Pick<MonthlySummary, "byCategory" | "totalCents">): CategoryRow[] {
  throw new Error("not implemented");
}

/** Width of a budget bar in percent: percentUsed clamped to 0..100. */
export function budgetBarPercent(status: Pick<BudgetStatus, "percentUsed">): number {
  throw new Error("not implemented");
}

/** Label shown next to a budget bar. */
export function alertLabel(alert: BudgetAlert): string {
  throw new Error("not implemented");
}

/** "+10%", "-68.2%", "0%", or "n/a" when there is nothing to compare with. */
export function changeLabel(changePercent: number | null): string {
  throw new Error("not implemented");
}

/**
 * Turn form values into a POST /api/expenses body. Every value is trimmed.
 * `category` and `note` are left out when they are empty.
 */
export function formToExpenseBody(form: ExpenseFormValues): ExpenseBody {
  throw new Error("not implemented");
}

/** "Imported 2 expenses. 1 row had errors." */
export function importSummary(result: Pick<ImportResponse, "imported" | "errors">): string {
  throw new Error("not implemented");
}
