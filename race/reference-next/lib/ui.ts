import type { ExpenseBody, ImportResponse } from "./api-types";
import type { BudgetAlert, BudgetStatus } from "./budgets";
import { CATEGORIES, type Category } from "./categories";
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
  const rows: CategoryRow[] = [];
  for (const category of CATEGORIES) {
    const cents = summary.byCategory[category];
    if (cents === undefined) continue;
    const percent = summary.totalCents === 0 ? 0 : Math.round((cents / summary.totalCents) * 1000) / 10;
    rows.push({ category, totalCents: cents, percent });
  }
  // Array.prototype.sort is stable, so equal totals keep CATEGORIES order.
  return rows.sort((a, b) => b.totalCents - a.totalCents);
}

/** Width of a budget bar in percent: percentUsed clamped to 0..100. */
export function budgetBarPercent(status: Pick<BudgetStatus, "percentUsed">): number {
  return Math.min(100, Math.max(0, status.percentUsed));
}

/** Label shown next to a budget bar. */
export function alertLabel(alert: BudgetAlert): string {
  if (alert === "over") return "Over budget";
  if (alert === "warning") return "Almost there";
  return "On track";
}

/** "+10%", "-68.2%", "0%", or "n/a" when there is nothing to compare with. */
export function changeLabel(changePercent: number | null): string {
  if (changePercent === null) return "n/a";
  if (changePercent > 0) return `+${changePercent}%`;
  if (changePercent === 0) return "0%";
  return `${changePercent}%`;
}

/**
 * Turn form values into a POST /api/expenses body. Every value is trimmed.
 * `category` and `note` are left out when they are empty.
 */
export function formToExpenseBody(form: ExpenseFormValues): ExpenseBody {
  const body: ExpenseBody = {
    date: form.date.trim(),
    amount: form.amount.trim(),
    merchant: form.merchant.trim(),
  };
  const category = form.category.trim();
  if (category !== "") body.category = category;
  const note = form.note.trim();
  if (note !== "") body.note = note;
  return body;
}

/** "Imported 2 expenses. 1 row had errors." */
export function importSummary(result: Pick<ImportResponse, "imported" | "errors">): string {
  const n = result.imported.length;
  let text = `Imported ${n} ${n === 1 ? "expense" : "expenses"}.`;
  const e = result.errors.length;
  if (e > 0) text += ` ${e} ${e === 1 ? "row" : "rows"} had errors.`;
  return text;
}
