// Shared helpers for the route handler tests.
import { getDb } from "../lib/db";
import type { ExpenseStore } from "../lib/expenses";

export const BASE = "http://localhost";

export function get(path: string): Request {
  return new Request(`${BASE}${path}`);
}

export function postJson(path: string, body: string): Request {
  return new Request(`${BASE}${path}`, { method: "POST", headers: { "content-type": "application/json" }, body });
}

export function postText(path: string, body: string): Request {
  return new Request(`${BASE}${path}`, { method: "POST", headers: { "content-type": "text/csv" }, body });
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export async function body(res: Response): Promise<any> {
  return res.json();
}

/** Adds three expenses to the shared store: 1 Whole Foods, 2 Uber, 3 Netflix. */
export function seed(): ExpenseStore {
  const { store } = getDb();
  store.add({ date: "2024-03-01", amountCents: 1250, merchant: "Whole Foods" });
  store.add({ date: "2024-03-05", amountCents: 2300, merchant: "Uber" });
  store.add({ date: "2024-04-02", amountCents: 999, merchant: "Netflix" });
  return store;
}
