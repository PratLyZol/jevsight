import type { Cents } from "./money";

export interface Share {
  person: string;
  amountCents: Cents;
}

export interface Transfer {
  from: string;
  to: string;
  amountCents: Cents;
}

/**
 * Split totalCents evenly. Everyone gets floor(total / n); the leftover cents go
 * one each to the first people in the given order.
 */
export function splitEven(totalCents: Cents, people: readonly string[]): Share[] {
  throw new Error("not implemented");
}

/**
 * Split totalCents by positive integer weights using the largest remainder method.
 * Leftover cents go to the largest fractional remainders; ties go to the earlier person.
 */
export function splitByWeights(totalCents: Cents, weights: readonly { person: string; weight: number }[]): Share[] {
  throw new Error("not implemented");
}

/**
 * Given what each person paid toward shared costs, split the total evenly among
 * all of them (with splitEven, in input order) and return the transfers that settle up.
 * Greedy: repeatedly the person who owes the most pays the person who is owed the most.
 */
export function settleUp(payments: readonly { person: string; paidCents: Cents }[]): Transfer[] {
  throw new Error("not implemented");
}
