import { ValidationError } from "./errors";
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
  validateTotal(totalCents);
  validatePeople(people);
  const n = people.length;
  const base = Math.floor(totalCents / n);
  const extra = totalCents - base * n;
  return people.map((person, i) => ({ person, amountCents: base + (i < extra ? 1 : 0) }));
}

/**
 * Split totalCents by positive integer weights using the largest remainder method.
 * Leftover cents go to the largest fractional remainders; ties go to the earlier person.
 */
export function splitByWeights(totalCents: Cents, weights: readonly { person: string; weight: number }[]): Share[] {
  validateTotal(totalCents);
  validatePeople(weights.map((w) => w.person));
  for (const w of weights) {
    if (!Number.isSafeInteger(w.weight) || w.weight <= 0) {
      throw new ValidationError(`weight for ${w.person} must be a positive integer`);
    }
  }
  const sum = weights.reduce((acc, w) => acc + w.weight, 0);
  const parts = weights.map((w, index) => {
    const exact = totalCents * w.weight;
    return { person: w.person, index, amountCents: Math.floor(exact / sum), remainder: exact % sum };
  });
  let leftover = totalCents - parts.reduce((acc, p) => acc + p.amountCents, 0);
  const order = [...parts].sort((a, b) => (b.remainder !== a.remainder ? b.remainder - a.remainder : a.index - b.index));
  for (const p of order) {
    if (leftover === 0) break;
    p.amountCents += 1;
    leftover -= 1;
  }
  return parts.map((p) => ({ person: p.person, amountCents: p.amountCents }));
}

/**
 * Given what each person paid toward shared costs, split the total evenly among
 * all of them (with splitEven, in input order) and return the transfers that settle up.
 * Greedy: repeatedly the person who owes the most pays the person who is owed the most.
 */
export function settleUp(payments: readonly { person: string; paidCents: Cents }[]): Transfer[] {
  const people = payments.map((p) => p.person);
  validatePeople(people);
  for (const p of payments) {
    if (!Number.isSafeInteger(p.paidCents) || p.paidCents < 0) {
      throw new ValidationError(`paidCents for ${p.person} must be a non-negative integer`);
    }
  }
  const total = payments.reduce((acc, p) => acc + p.paidCents, 0);
  const shares = splitEven(total, people);
  const balance = payments.map((p, i) => p.paidCents - shares[i]!.amountCents);

  const transfers: Transfer[] = [];
  for (;;) {
    let debtor = -1;
    let creditor = -1;
    for (let i = 0; i < balance.length; i++) {
      const b = balance[i]!;
      if (b < 0 && (debtor === -1 || b < balance[debtor]!)) debtor = i;
      if (b > 0 && (creditor === -1 || b > balance[creditor]!)) creditor = i;
    }
    if (debtor === -1 || creditor === -1) break;
    const amount = Math.min(-balance[debtor]!, balance[creditor]!);
    transfers.push({ from: people[debtor]!, to: people[creditor]!, amountCents: amount });
    balance[debtor] += amount;
    balance[creditor] -= amount;
  }
  return transfers;
}

function validateTotal(totalCents: number): void {
  if (!Number.isSafeInteger(totalCents) || totalCents < 0) {
    throw new ValidationError("totalCents must be a non-negative integer");
  }
}

function validatePeople(people: readonly string[]): void {
  if (people.length === 0) throw new ValidationError("at least one person is required");
  const seen = new Set<string>();
  for (const p of people) {
    if (typeof p !== "string" || p.trim() === "") throw new ValidationError("person names must be non-empty");
    if (seen.has(p)) throw new ValidationError(`duplicate person: ${p}`);
    seen.add(p);
  }
}
