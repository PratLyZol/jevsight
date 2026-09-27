// The in-memory database used by the API routes. This file is complete; you do not need to change it.
import type { Budgets } from "./budgets";
import { ExpenseStore } from "./expenses";

/** Monthly budgets used by GET /api/summary until a test calls resetDb with others. */
export const DEFAULT_BUDGETS: Budgets = {
  groceries: 40000,
  dining: 20000,
  transport: 15000,
  housing: 150000,
  utilities: 20000,
  entertainment: 5000,
  health: 10000,
  shopping: 15000,
  travel: 30000,
};

export interface Db {
  store: ExpenseStore;
  budgets: Budgets;
}

// Kept on globalThis so every route bundle (and dev hot reload) shares one store per process.
const KEY = Symbol.for("expense-tracker.db");
type Holder = { [KEY]?: Db };

/** The shared database. Created empty on first use. */
export function getDb(): Db {
  const holder = globalThis as Holder;
  if (!holder[KEY]) holder[KEY] = { store: new ExpenseStore(), budgets: { ...DEFAULT_BUDGETS } };
  return holder[KEY];
}

/** Replace the shared database with a fresh, empty store. Tests call this before each case. */
export function resetDb(budgets: Budgets = DEFAULT_BUDGETS): Db {
  const db: Db = { store: new ExpenseStore(), budgets: { ...budgets } };
  (globalThis as Holder)[KEY] = db;
  return db;
}
