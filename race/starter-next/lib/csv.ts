import type { Expense, NewExpense } from "./expenses";

export const CSV_HEADER = "id,date,amount,merchant,category,note";

export interface CsvRowError {
  /** 1-based physical line where the bad record starts (the header is line 1). */
  line: number;
  message: string;
}

export interface CsvImportResult {
  rows: NewExpense[];
  errors: CsvRowError[];
}

/** Export expenses as CSV text. One header line, one line per expense, every line ends with "\n". */
export function toCsv(expenses: readonly Expense[]): string {
  throw new Error("not implemented");
}

/**
 * Parse CSV text produced by toCsv (or edited by hand). Never throws for bad rows:
 * each bad row adds an entry to `errors` and is skipped.
 */
export function fromCsv(text: string): CsvImportResult {
  throw new Error("not implemented");
}
