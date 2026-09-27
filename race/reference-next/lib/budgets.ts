import { CATEGORIES, type Category } from "./categories";
import { ValidationError } from "./errors";
import { isValidMonth, type Expense } from "./expenses";
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
  if (!isValidMonth(month)) throw new ValidationError(`invalid month: ${month}`);
  const result: BudgetStatus[] = [];
  for (const category of CATEGORIES) {
    const budget = budgets[category];
    if (budget === undefined) continue;
    if (!Number.isSafeInteger(budget) || budget <= 0) {
      throw new ValidationError(`budget for ${category} must be a positive integer`);
    }
    let spent = 0;
    for (const e of expenses) {
      if (e.category === category && e.date.startsWith(`${month}-`)) spent += e.amountCents;
    }
    let alert: BudgetAlert = "ok";
    if (spent >= budget) alert = "over";
    else if (spent * 100 >= budget * 80) alert = "warning";
    result.push({
      category,
      budgetCents: budget,
      spentCents: spent,
      remainingCents: budget - spent,
      percentUsed: Math.round((spent / budget) * 100),
      alert,
    });
  }
  return result;
}

/** Only the statuses whose alert is not "ok", in the same order. */
export function budgetAlerts(statuses: readonly BudgetStatus[]): BudgetStatus[] {
  return statuses.filter((s) => s.alert !== "ok");
}
