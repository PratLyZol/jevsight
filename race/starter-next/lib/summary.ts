import type { SummaryResponse } from "./api-types";
import type { Budgets } from "./budgets";
import type { Expense } from "./expenses";

/**
 * Everything the summary page and GET /api/summary show for one month.
 * Throws ValidationError for a bad month or a bad budget. See SPEC.md.
 */
export function buildSummary(expenses: readonly Expense[], budgets: Budgets, month: string): SummaryResponse {
  throw new Error("not implemented");
}
