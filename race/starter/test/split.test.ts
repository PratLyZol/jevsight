import { describe, expect, it } from "vitest";
import { ValidationError } from "../src/errors";
import { settleUp, splitByWeights, splitEven } from "../src/split";

describe("splitEven", () => {
  it("gives leftover cents to the first people in order", () => {
    expect(splitEven(1000, ["ann", "ben", "cat"])).toEqual([
      { person: "ann", amountCents: 334 },
      { person: "ben", amountCents: 333 },
      { person: "cat", amountCents: 333 },
    ]);
    expect(splitEven(1001, ["ann", "ben", "cat"]).map((s) => s.amountCents)).toEqual([334, 334, 333]);
    expect(splitEven(100, ["a", "b", "c", "d"]).map((s) => s.amountCents)).toEqual([25, 25, 25, 25]);
    expect(splitEven(0, ["solo"])).toEqual([{ person: "solo", amountCents: 0 }]);
  });

  it("rejects no people, duplicate people and bad totals", () => {
    expect(() => splitEven(100, [])).toThrow(ValidationError);
    expect(() => splitEven(100, ["a", "a"])).toThrow(ValidationError);
    expect(() => splitEven(-1, ["a"])).toThrow(ValidationError);
    expect(() => splitEven(10.5, ["a"])).toThrow(ValidationError);
  });
});

describe("splitByWeights", () => {
  it("uses the largest remainder method with ties going to the earlier person", () => {
    expect(splitByWeights(1000, [{ person: "ann", weight: 1 }, { person: "ben", weight: 2 }])).toEqual([
      { person: "ann", amountCents: 333 },
      { person: "ben", amountCents: 667 },
    ]);
    const equal = splitByWeights(100, [{ person: "a", weight: 1 }, { person: "b", weight: 1 }, { person: "c", weight: 1 }]);
    expect(equal.map((s) => s.amountCents)).toEqual([34, 33, 33]);
    const mixed = splitByWeights(1000, [{ person: "a", weight: 3 }, { person: "b", weight: 3 }, { person: "c", weight: 1 }]);
    expect(mixed.map((s) => s.amountCents)).toEqual([429, 428, 143]);
    expect(() => splitByWeights(100, [{ person: "a", weight: 0 }])).toThrow(ValidationError);
    expect(() => splitByWeights(100, [{ person: "a", weight: 1.5 }])).toThrow(ValidationError);
  });
});

describe("settleUp", () => {
  it("has the biggest debtor pay the biggest creditor first", () => {
    const transfers = settleUp([
      { person: "alice", paidCents: 9000 },
      { person: "bob", paidCents: 3000 },
      { person: "carol", paidCents: 0 },
    ]);
    expect(transfers).toEqual([
      { from: "carol", to: "alice", amountCents: 4000 },
      { from: "bob", to: "alice", amountCents: 1000 },
    ]);
  });

  it("handles uneven cents, multiple creditors and already-even groups", () => {
    expect(settleUp([{ person: "a", paidCents: 100 }, { person: "b", paidCents: 0 }, { person: "c", paidCents: 0 }])).toEqual([
      { from: "b", to: "a", amountCents: 33 },
      { from: "c", to: "a", amountCents: 33 },
    ]);
    expect(
      settleUp([
        { person: "a", paidCents: 0 },
        { person: "b", paidCents: 6000 },
        { person: "c", paidCents: 5000 },
        { person: "d", paidCents: 1000 },
      ]),
    ).toEqual([
      { from: "a", to: "b", amountCents: 3000 },
      { from: "d", to: "c", amountCents: 2000 },
    ]);
    expect(settleUp([{ person: "x", paidCents: 500 }, { person: "y", paidCents: 500 }])).toEqual([]);
    expect(() => settleUp([{ person: "x", paidCents: -1 }])).toThrow(ValidationError);
  });
});
