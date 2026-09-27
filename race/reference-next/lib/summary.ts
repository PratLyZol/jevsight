import type { SummaryResponse } from "./api-types";
import { budgetAlerts, budgetStatus, type Budgets } from "./budgets";
import { ValidationError } from "./errors";
import { isValidMonth, type Expense } from "./expenses";
import { monthOverMonth, monthlySummary } from "./reports";

/**
 * Everything the summary page and GET /api/summary show for one month.
 * Throws ValidationError for a bad month or a bad budget.
 */
export function buildSummary(expenses: readonly Expense[], budgets: Budgets, month: string): SummaryResponse {
  if (!isValidMonth(month)) throw new ValidationError(`invalid month: ${month}`);
  const statuses = budgetStatus(expenses, budgets, month);
  return {
    summary: monthlySummary(expenses, month),
    budgets: statuses,
    alerts: budgetAlerts(statuses),
    comparison: monthOverMonth(expenses, month),
  };
}
