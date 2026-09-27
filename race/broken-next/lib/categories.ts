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
  return typeof value === "string" && (CATEGORIES as readonly string[]).includes(value);
}

/** Ordered rules. The first rule whose keyword appears in the merchant name wins. */
const RULES: ReadonlyArray<readonly [string, Category]> = [
  ["uber eats", "dining"],
  ["doordash", "dining"],
  ["starbucks", "dining"],
  ["chipotle", "dining"],
  ["mcdonald", "dining"],
  ["pizza", "dining"],
  ["cafe", "dining"],
  ["restaurant", "dining"],
  ["whole foods", "groceries"],
  ["trader joe", "groceries"],
  ["kroger", "groceries"],
  ["safeway", "groceries"],
  ["costco", "groceries"],
  ["h-e-b", "groceries"],
  ["uber", "transport"],
  ["lyft", "transport"],
  ["shell", "transport"],
  ["chevron", "transport"],
  ["parking", "transport"],
  ["metro", "transport"],
  ["mortgage", "housing"],
  ["apartments", "housing"],
  ["landlord", "housing"],
  ["comcast", "utilities"],
  ["xfinity", "utilities"],
  ["verizon", "utilities"],
  ["electric", "utilities"],
  ["netflix", "entertainment"],
  ["spotify", "entertainment"],
  ["hulu", "entertainment"],
  ["steam", "entertainment"],
  ["cinema", "entertainment"],
  ["cvs", "health"],
  ["walgreens", "health"],
  ["pharmacy", "health"],
  ["dental", "health"],
  ["clinic", "health"],
  ["amazon", "shopping"],
  ["target", "shopping"],
  ["walmart", "shopping"],
  ["best buy", "shopping"],
  ["ikea", "shopping"],
  ["airlines", "travel"],
  ["airbnb", "travel"],
  ["marriott", "travel"],
  ["hilton", "travel"],
  ["expedia", "travel"],
];

/** Guess a category from a merchant name. Case-insensitive substring match; "other" if nothing matches. */
export function categorize(merchant: string): Category {
  const name = merchant.trim().toLowerCase();
  if (name === "") return "other";
  for (const [keyword, category] of RULES) {
    if (name.includes(keyword)) return category;
  }
  return "other";
}
