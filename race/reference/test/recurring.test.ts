import { describe, expect, it } from "vitest";
import { ValidationError } from "../src/errors";
import { expandRule, expandRules, type MonthlyRule, type WeeklyRule } from "../src/recurring";

const gym: WeeklyRule = {
  id: "gym",
  frequency: "weekly",
  startDate: "2024-01-03",
  amountCents: 1500,
  merchant: "City Gym",
  category: "health",
};

const rent: MonthlyRule = {
  id: "rent",
  frequency: "monthly",
  dayOfMonth: 31,
  startDate: "2024-01-01",
  amountCents: 150000,
  merchant: "Sunset Apartments",
  category: "housing",
};

describe("expandRule weekly", () => {
  it("steps 7 days from startDate and keeps dates inside the range", () => {
    const dates = expandRule(gym, "2024-01-20", "2024-02-10").map((o) => o.date);
    expect(dates).toEqual(["2024-01-24", "2024-01-31", "2024-02-07"]);
    const first = expandRule(gym, "2024-01-01", "2024-01-03");
    expect(first).toEqual([
      { ruleId: "gym", date: "2024-01-03", amountCents: 1500, merchant: "City Gym", category: "health" },
    ]);
  });

  it("stops at endDate and returns nothing for an empty range", () => {
    const rule: WeeklyRule = { ...gym, endDate: "2024-01-17" };
    expect(expandRule(rule, "2024-01-01", "2024-12-31").map((o) => o.date)).toEqual(["2024-01-03", "2024-01-10", "2024-01-17"]);
    expect(expandRule(gym, "2024-03-01", "2024-02-01")).toEqual([]);
    expect(expandRule(gym, "2023-01-01", "2023-12-31")).toEqual([]);
  });
});

describe("expandRule monthly", () => {
  it("clamps day 31 to the last day of shorter months (leap year)", () => {
    const dates = expandRule(rent, "2024-01-01", "2024-04-30").map((o) => o.date);
    expect(dates).toEqual(["2024-01-31", "2024-02-29", "2024-03-31", "2024-04-30"]);
  });

  it("clamps in non-leap years and skips a day before startDate", () => {
    const rule: MonthlyRule = { ...rent, id: "phone", dayOfMonth: 30, startDate: "2023-01-31" };
    expect(expandRule(rule, "2023-01-01", "2023-03-31").map((o) => o.date)).toEqual(["2023-02-28", "2023-03-30"]);
    const mid: MonthlyRule = { ...rent, id: "mid", dayOfMonth: 15, startDate: "2023-01-20", endDate: "2023-04-14" };
    expect(expandRule(mid, "2022-12-01", "2023-12-31").map((o) => o.date)).toEqual(["2023-02-15", "2023-03-15"]);
  });
});

describe("expandRules", () => {
  it("merges rules sorted by date then ruleId, and validates rules", () => {
    const a: MonthlyRule = { ...rent, id: "b-rent", dayOfMonth: 31 };
    const b: WeeklyRule = { ...gym, id: "a-gym", startDate: "2024-01-31" };
    const result = expandRules([a, b], "2024-01-25", "2024-02-14").map((o) => `${o.date} ${o.ruleId}`);
    expect(result).toEqual(["2024-01-31 a-gym", "2024-01-31 b-rent", "2024-02-07 a-gym", "2024-02-14 a-gym"]);
    expect(() => expandRule({ ...rent, dayOfMonth: 0 }, "2024-01-01", "2024-02-01")).toThrow(ValidationError);
    expect(() => expandRule({ ...rent, dayOfMonth: 32 }, "2024-01-01", "2024-02-01")).toThrow(ValidationError);
    expect(() => expandRule(gym, "2024-01-01", "2024-02-30")).toThrow(ValidationError);
  });
});
