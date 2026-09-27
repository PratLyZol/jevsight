import type { Category } from "./categories";
import { ValidationError } from "./errors";
import { isValidDate } from "./expenses";
import type { Cents } from "./money";

interface RuleBase {
  id: string;
  amountCents: Cents;
  merchant: string;
  category: Category;
  /** First date the rule can produce an occurrence (YYYY-MM-DD). */
  startDate: string;
  /** Optional last date (inclusive). */
  endDate?: string;
}

export interface WeeklyRule extends RuleBase {
  frequency: "weekly";
}

export interface MonthlyRule extends RuleBase {
  frequency: "monthly";
  /** 1..31. Clamped to the last day of shorter months. */
  dayOfMonth: number;
}

export type RecurringRule = WeeklyRule | MonthlyRule;

export interface Occurrence {
  ruleId: string;
  date: string;
  amountCents: Cents;
  merchant: string;
  category: Category;
}

/** All occurrences of one rule with from <= date <= to, in ascending date order. */
export function expandRule(rule: RecurringRule, from: string, to: string): Occurrence[] {
  if (!isValidDate(from) || !isValidDate(to)) throw new ValidationError("invalid range");
  if (!isValidDate(rule.startDate)) throw new ValidationError("invalid startDate");
  if (rule.endDate !== undefined && !isValidDate(rule.endDate)) throw new ValidationError("invalid endDate");

  const lower = rule.startDate > from ? rule.startDate : from;
  let upper = to;
  if (rule.endDate !== undefined && rule.endDate < upper) upper = rule.endDate;

  const dates: string[] = [];
  if (rule.frequency === "weekly") {
    let t = toUtc(rule.startDate);
    const upperT = toUtc(upper);
    const lowerT = toUtc(lower);
    while (t <= upperT) {
      if (t >= lowerT) dates.push(fromUtc(t));
      t += 7 * 86_400_000;
    }
  } else if (rule.frequency === "monthly") {
    const day = rule.dayOfMonth;
    if (!Number.isInteger(day) || day < 1 || day > 31) throw new ValidationError("dayOfMonth must be 1..31");
    let year = Number(rule.startDate.slice(0, 4));
    let month = Number(rule.startDate.slice(5, 7));
    for (;;) {
      const last = new Date(Date.UTC(year, month - 1, 0)).getUTCDate();
      const d = `${pad(year, 4)}-${pad(month, 2)}-${pad(Math.min(day, last), 2)}`;
      if (d > upper) break;
      if (d >= lower) dates.push(d);
      month += 1;
      if (month > 12) {
        month = 1;
        year += 1;
      }
    }
  } else {
    throw new ValidationError("unknown frequency");
  }

  return dates.map((date) => ({
    ruleId: rule.id,
    date,
    amountCents: rule.amountCents,
    merchant: rule.merchant,
    category: rule.category,
  }));
}

/** Occurrences of all rules, sorted by date ascending, then ruleId ascending. */
export function expandRules(rules: readonly RecurringRule[], from: string, to: string): Occurrence[] {
  const all = rules.flatMap((r) => expandRule(r, from, to));
  all.sort((a, b) => (a.date === b.date ? cmp(a.ruleId, b.ruleId) : cmp(a.date, b.date)));
  return all;
}

function cmp(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

function toUtc(date: string): number {
  return Date.UTC(Number(date.slice(0, 4)), Number(date.slice(5, 7)) - 1, Number(date.slice(8, 10)));
}

function fromUtc(t: number): string {
  return new Date(t).toISOString().slice(0, 10);
}

function pad(n: number, width: number): string {
  return String(n).padStart(width, "0");
}
