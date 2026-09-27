export const CATEGORIES = [
  "groceries",
  "dining",
  "transport",
  "housing",
  "utilities",
  "entertainment",
  "health",
  "shopping",
  "travel",
  "other",
] as const;

export type Category = (typeof CATEGORIES)[number];

/** True if value is one of CATEGORIES (exact, lowercase match). */
export function isCategory(value: unknown): value is Category {
  throw new Error("not implemented");
}

/**
 * Guess a category from a merchant name using the ordered keyword rules in SPEC.md.
 * Case-insensitive substring match; "other" if nothing matches.
 */
export function categorize(merchant: string): Category {
  throw new Error("not implemented");
}
