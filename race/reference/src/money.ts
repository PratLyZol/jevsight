import { ValidationError } from "./errors";

/** Integer number of cents. */
export type Cents = number;

const MONEY_RE = /^(-)?\$?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{1,2}))?$/;

/**
 * Parse a user string such as "$1,234.56", "12", "12.5" or "-3.20" into integer cents.
 * Throws ValidationError on invalid input.
 */
export function parseMoney(input: string): Cents {
  if (typeof input !== "string") {
    throw new ValidationError("amount must be a string");
  }
  const match = MONEY_RE.exec(input.trim());
  if (!match) {
    throw new ValidationError(`invalid amount: "${input}"`);
  }
  const negative = match[1] === "-";
  const whole = Number(match[2]!.replace(/,/g, ""));
  const frac = Number((match[3] ?? "").padEnd(2, "0"));
  const cents = whole * 100 + frac;
  if (!Number.isSafeInteger(cents)) {
    throw new ValidationError(`amount too large: "${input}"`);
  }
  return negative && cents !== 0 ? -cents : cents;
}

/** Format integer cents as "$1,234.56" (negative values as "-$1,234.56"). */
export function formatMoney(cents: Cents): string {
  assertCents(cents);
  const negative = cents < 0;
  const abs = Math.abs(cents);
  const whole = Math.floor(abs / 100);
  const frac = abs % 100;
  const wholeStr = whole.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return `${negative ? "-" : ""}$${wholeStr}.${frac.toString().padStart(2, "0")}`;
}

/** Add two cent amounts. Throws ValidationError if either is not an integer. */
export function addMoney(a: Cents, b: Cents): Cents {
  assertCents(a);
  assertCents(b);
  return a + b;
}

/** Sum a list of cent amounts. Empty list sums to 0. */
export function sumMoney(values: readonly Cents[]): Cents {
  let total = 0;
  for (const v of values) total = addMoney(total, v);
  return total;
}

function assertCents(value: number): void {
  if (!Number.isSafeInteger(value)) {
    throw new ValidationError(`cents must be an integer, got ${value}`);
  }
}
