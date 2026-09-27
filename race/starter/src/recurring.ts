import type { Category } from "./categories";
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
  throw new Error("not implemented");
}

/** Occurrences of all rules, sorted by date ascending, then ruleId ascending. */
export function expandRules(rules: readonly RecurringRule[], from: string, to: string): Occurrence[] {
  throw new Error("not implemented");
}
