import { describe, expect, it } from "vitest";
import { ValidationError } from "../src/errors";
import { addMoney, formatMoney, parseMoney, sumMoney } from "../src/money";

describe("parseMoney", () => {
  it("parses plain and decimal amounts into cents", () => {
    expect(parseMoney("12")).toBe(1200);
    expect(parseMoney("12.5")).toBe(1250);
    expect(parseMoney("12.34")).toBe(1234);
    expect(parseMoney("0.07")).toBe(7);
    expect(parseMoney("  8.10 ")).toBe(810);
  });

  it("parses dollar signs, thousands separators and negatives", () => {
    expect(parseMoney("$1,234.56")).toBe(123456);
    expect(parseMoney("$1,000,000")).toBe(100000000);
    expect(parseMoney("-3.20")).toBe(-320);
    expect(parseMoney("-$3.20")).toBe(-320);
    expect(parseMoney("1234.5")).toBe(123450);
  });

  it("rejects invalid input with a ValidationError", () => {
    for (const bad of ["", "abc", "12.345", "1,23", "$", "12.", ".5", "1.2.3", "--1", "$-3", "12,34.00", "1 000"]) {
      expect(() => parseMoney(bad), bad).toThrow(ValidationError);
    }
  });
});

describe("formatMoney", () => {
  it("formats cents with a dollar sign, commas and two decimals", () => {
    expect(formatMoney(123456)).toBe("$1,234.56");
    expect(formatMoney(5)).toBe("$0.05");
    expect(formatMoney(0)).toBe("$0.00");
    expect(formatMoney(100000000)).toBe("$1,000,000.00");
    expect(formatMoney(99999)).toBe("$999.99");
  });

  it("formats negatives and rejects non-integers", () => {
    expect(formatMoney(-320)).toBe("-$3.20");
    expect(formatMoney(-123456)).toBe("-$1,234.56");
    expect(() => formatMoney(1.5)).toThrow(ValidationError);
    for (const cents of [0, 7, 1250, 123456, -320]) {
      expect(parseMoney(formatMoney(cents))).toBe(cents);
    }
  });
});

describe("addMoney / sumMoney", () => {
  it("adds and sums integer cents", () => {
    expect(addMoney(150, 275)).toBe(425);
    expect(addMoney(-100, 40)).toBe(-60);
    expect(sumMoney([])).toBe(0);
    expect(sumMoney([1, 2, 3, 994])).toBe(1000);
    expect(() => addMoney(1.5, 1)).toThrow(ValidationError);
    expect(() => sumMoney([100, 0.5])).toThrow(ValidationError);
  });
});
