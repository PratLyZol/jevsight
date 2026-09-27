import { isCategory } from "./categories";
import { isValidDate, type Expense, type NewExpense } from "./expenses";
import { parseMoney } from "./money";

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
  let out = CSV_HEADER + "\n";
  for (const e of expenses) {
    const fields = [String(e.id), e.date, centsToDecimal(e.amountCents), e.merchant, e.category, e.note];
    out += fields.map(quoteField).join(",") + "\n";
  }
  return out;
}

/** Quote a field only if it contains a comma, a double quote, "\r" or "\n". Inner quotes are doubled. */
export function quoteField(value: string): string {
  if (/[",\r\n]/.test(value)) return `"${value.replace(/"/g, '""')}"`;
  return value;
}

/**
 * Parse CSV text produced by toCsv (or edited by hand). Never throws for bad rows:
 * each bad row adds an entry to `errors` and is skipped.
 */
export function fromCsv(text: string): CsvImportResult {
  const rows: NewExpense[] = [];
  const errors: CsvRowError[] = [];
  const { records, error } = parseRecords(text);

  const header = records[0];
  if (!header || header.fields.join(",") !== CSV_HEADER) {
    return { rows, errors: [{ line: 1, message: `missing or invalid header, expected "${CSV_HEADER}"` }] };
  }

  for (const rec of records.slice(1)) {
    const f = rec.fields;
    if (f.length === 1 && f[0] === "") continue; // blank line
    if (f.length !== 6) {
      errors.push({ line: rec.line, message: `expected 6 fields, got ${f.length}` });
      continue;
    }
    const [, date, amount, merchantRaw, category, note] = f as [string, string, string, string, string, string];
    if (!isValidDate(date)) {
      errors.push({ line: rec.line, message: `invalid date: "${date}"` });
      continue;
    }
    let amountCents: number;
    try {
      amountCents = parseMoney(amount);
    } catch {
      errors.push({ line: rec.line, message: `invalid amount: "${amount}"` });
      continue;
    }
    if (amountCents <= 0) {
      errors.push({ line: rec.line, message: "amount must be greater than 0" });
      continue;
    }
    const merchant = merchantRaw.trim();
    if (merchant === "") {
      errors.push({ line: rec.line, message: "merchant is required" });
      continue;
    }
    if (category !== "" && !isCategory(category)) {
      errors.push({ line: rec.line, message: `unknown category: "${category}"` });
      continue;
    }
    const row: NewExpense = { date, amountCents, merchant, note };
    if (category !== "") row.category = category;
    rows.push(row);
  }

  if (error) errors.push(error);
  return { rows, errors };
}

interface RawRecord {
  line: number;
  fields: string[];
}

function parseRecords(text: string): { records: RawRecord[]; error?: CsvRowError } {
  const records: RawRecord[] = [];
  let line = 1;
  let recordLine = 1;
  let fields: string[] = [];
  let field = "";
  let inQuotes = false;
  let i = 0;
  const n = text.length;

  const endRecord = () => {
    fields.push(field);
    records.push({ line: recordLine, fields });
    fields = [];
    field = "";
  };

  while (i < n) {
    const c = text[i]!;
    if (inQuotes) {
      if (c === '"') {
        if (text[i + 1] === '"') {
          field += '"';
          i += 2;
          continue;
        }
        inQuotes = false;
        i += 1;
        continue;
      }
      if (c === "\n") line += 1;
      field += c;
      i += 1;
      continue;
    }
    if (c === '"' && field === "") {
      inQuotes = true;
      i += 1;
    } else if (c === ",") {
      fields.push(field);
      field = "";
      i += 1;
    } else if (c === "\r" && text[i + 1] === "\n") {
      i += 1; // handled by the "\n" branch next
    } else if (c === "\n") {
      endRecord();
      line += 1;
      recordLine = line;
      i += 1;
    } else {
      field += c;
      i += 1;
    }
  }

  if (inQuotes) {
    return { records, error: { line: recordLine, message: "unterminated quoted field" } };
  }
  if (field !== "" || fields.length > 0) endRecord();
  return { records };
}

function centsToDecimal(cents: number): string {
  const sign = cents < 0 ? "-" : "";
  const abs = Math.abs(cents);
  return `${sign}${Math.floor(abs / 100)}.${String(abs % 100).padStart(2, "0")}`;
}
