import type { Category } from "./categories";
import type { Expense } from "./expenses";
import type { Cents } from "./money";

/** Monthly budget in cents per category. Categories without a key have no budget. */
export type Budgets = Partial<Record<Category, Cents>>;

export type BudgetAlert = "ok" | "warning" | "over";

export interface BudgetStatus {
  category: Category;
  budgetCents: Cents;
  spentCents: Cents;
  /** budgetCents - spentCents (negative when over budget). */
  remainingCents: Cents;
  /** Math.round(spent / budget * 100). */
  percentUsed: number;
  /** "over" when spent >= 100% of budget, "warning" when spent >= 80%, else "ok". */
  alert: BudgetAlert;
}

/**
 * One status per budgeted category, in CATEGORIES order, for expenses dated in `month` (YYYY-MM).
 * Throws ValidationError for a bad month or a budget that is not a positive integer.
 */
export function budgetStatus(expenses: readonly Expense[], budgets: Budgets, month: string): BudgetStatus[] {
  throw new Error("not implemented");
}

/** Only the statuses whose alert is not "ok", in the same order. */
export function budgetAlerts(statuses: readonly BudgetStatus[]): BudgetStatus[] {
  throw new Error("not implemented");
}
