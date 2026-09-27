import type { Category } from "./categories";
import { ValidationError } from "./errors";
import { isValidMonth, type Expense } from "./expenses";
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
  if (!isValidMonth(month)) throw new ValidationError(`invalid month: ${month}`);
  const inMonth = expenses.filter((e) => e.date.startsWith(`${month}-`));
  let total = 0;
  const byCategory: Partial<Record<Category, Cents>> = {};
  const byMerchant = new Map<string, Cents>();
  for (const e of inMonth) {
    total += e.amountCents;
    byCategory[e.category] = (byCategory[e.category] ?? 0) + e.amountCents;
    byMerchant.set(e.merchant, (byMerchant.get(e.merchant) ?? 0) + e.amountCents);
  }
  const topMerchants = [...byMerchant.entries()]
    .map(([merchant, totalCents]) => ({ merchant, totalCents }))
    .sort((a, b) =>
      a.totalCents !== b.totalCents ? b.totalCents - a.totalCents : a.merchant < b.merchant ? -1 : a.merchant > b.merchant ? 1 : 0,
    )
    .slice(0, 3);
  const days = daysInMonth(month);
  return {
    month,
    totalCents: total,
    count: inMonth.length,
    byCategory,
    topMerchants,
    dailyAverageCents: Math.round(total / days),
  };
}

/** Compare the total of `month` with the month before it. */
export function monthOverMonth(expenses: readonly Expense[], month: string): MonthOverMonth {
  if (!isValidMonth(month)) throw new ValidationError(`invalid month: ${month}`);
  const previousMonth = previousMonthOf(month);
  const currentCents = monthlySummary(expenses, month).totalCents;
  const previousCents = monthlySummary(expenses, previousMonth).totalCents;
  const changePercent =
    previousCents === 0 ? null : Math.round(((currentCents - previousCents) / previousCents) * 1000) / 10;
  return { month, previousMonth, currentCents, previousCents, changePercent };
}

/** "2025-01" -> "2024-12". */
export function previousMonthOf(month: string): string {
  if (!isValidMonth(month)) throw new ValidationError(`invalid month: ${month}`);
  let year = Number(month.slice(0, 4));
  let m = Number(month.slice(5, 7)) - 1;
  if (m === 0) {
    m = 12;
    year -= 1;
  }
  return `${String(year).padStart(4, "0")}-${String(m).padStart(2, "0")}`;
}

function daysInMonth(month: string): number {
  return new Date(Date.UTC(Number(month.slice(0, 4)), Number(month.slice(5, 7)), 0)).getUTCDate();
}
