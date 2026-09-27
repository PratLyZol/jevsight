import { describe, expect, it } from "vitest";
import { CATEGORIES, categorize, isCategory } from "../lib/categories";

describe("categories", () => {
  it("recognizes exactly the known categories", () => {
    expect(CATEGORIES).toHaveLength(10);
    for (const c of CATEGORIES) expect(isCategory(c)).toBe(true);
    expect(isCategory("Groceries")).toBe(false);
    expect(isCategory("food")).toBe(false);
    expect(isCategory("")).toBe(false);
  });

  it("auto-categorizes common merchants", () => {
    expect(categorize("Uber")).toBe("transport");
    expect(categorize("Whole Foods Market")).toBe("groceries");
    expect(categorize("Netflix.com")).toBe("entertainment");
    expect(categorize("Amazon Marketplace")).toBe("shopping");
    expect(categorize("CVS")).toBe("health");
    expect(categorize("Southwest Airlines")).toBe("travel");
    expect(categorize("Comcast Cable")).toBe("utilities");
    expect(categorize("Sunset Apartments")).toBe("housing");
  });

  it("is case-insensitive and the first matching rule wins", () => {
    expect(categorize("UBER EATS")).toBe("dining");
    expect(categorize("uber trip 3pm")).toBe("transport");
    expect(categorize("  starbucks #123  ")).toBe("dining");
    expect(categorize("TRADER JOE'S")).toBe("groceries");
    expect(categorize("Shell Oil 5521")).toBe("transport");
  });

  it("falls back to other", () => {
    expect(categorize("Joe's Hardware")).toBe("other");
    expect(categorize("")).toBe("other");
    expect(categorize("   ")).toBe("other");
  });
});
