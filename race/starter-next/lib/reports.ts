import type { Category } from "./categories";
import type { Expense } from "./expenses";
import type { Cents } from "./money";

export interface MerchantTotal {
  merchant: string;
  totalCents: Cents;
}

export interface MonthlySummary {
  month: string;
  totalCents: Cents;
  count: number;
  /** Only categories that have at least one expense in the month. */
  byCategory: Partial<Record<Category, Cents>>;
  /** Up to 3 merchants by total descending, ties by merchant name ascending. */
  topMerchants: MerchantTotal[];
  /** Math.round(totalCents / number of days in the month). */
  dailyAverageCents: Cents;
}

export interface MonthOverMonth {
  month: string;
  previousMonth: string;
  currentCents: Cents;
  previousCents: Cents;
  /** Percent change rounded to 1 decimal, or null when the previous month total is 0. */
  changePercent: number | null;
}

/** Summary of expenses dated in `month` (YYYY-MM). Throws ValidationError for a bad month. */
export function monthlySummary(expenses: readonly Expense[], month: string): MonthlySummary {
  throw new Error("not implemented");
}

/** Compare the total of `month` with the month before it. */
export function monthOverMonth(expenses: readonly Expense[], month: string): MonthOverMonth {
  throw new Error("not implemented");
}

/** "2025-01" -> "2024-12". */
export function previousMonthOf(month: string): string {
  throw new Error("not implemented");
}
