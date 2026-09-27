// Shapes of API request and response bodies. This file is complete; you do not need to change it.
import type { BudgetStatus } from "./budgets";
import type { CsvRowError } from "./csv";
import type { Expense } from "./expenses";
import type { MonthOverMonth, MonthlySummary } from "./reports";

/** Body of POST /api/expenses. Send `amountCents` (a number) or `amount` (a money string). */
export interface ExpenseBody {
  date: string;
  amount?: string;
  amountCents?: number;
  merchant: string;
  category?: string;
  note?: string;
}

/** Every error response. */
export interface ErrorBody {
  error: string;
}

/** 200 body of GET /api/summary?month=YYYY-MM. */
export interface SummaryResponse {
  summary: MonthlySummary;
  budgets: BudgetStatus[];
  alerts: BudgetStatus[];
  comparison: MonthOverMonth;
}

/** 200 body of POST /api/import. */
export interface ImportResponse {
  imported: Expense[];
  errors: CsvRowError[];
}
