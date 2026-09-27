/** Integer number of cents. */
export type Cents = number;

/**
 * Parse a user string such as "$1,234.56", "12", "12.5" or "-3.20" into integer cents.
 * Throws ValidationError on invalid input. See SPEC.md.
 */
export function parseMoney(input: string): Cents {
  throw new Error("not implemented");
}

/** Format integer cents as "$1,234.56" (negative values as "-$1,234.56"). */
export function formatMoney(cents: Cents): string {
  throw new Error("not implemented");
}

/** Add two cent amounts. Throws ValidationError if either is not an integer. */
export function addMoney(a: Cents, b: Cents): Cents {
  throw new Error("not implemented");
}

/** Sum a list of cent amounts. Empty list sums to 0. */
export function sumMoney(values: readonly Cents[]): Cents {
  throw new Error("not implemented");
}
