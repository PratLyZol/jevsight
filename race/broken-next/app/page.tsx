"use client";

import { useEffect, useState, type FormEvent } from "react";
import type { ErrorBody } from "../lib/api-types";
import { CATEGORIES } from "../lib/categories";
import type { Expense } from "../lib/expenses";
import { formatMoney } from "../lib/money";
import { formToExpenseBody, type ExpenseFormValues } from "../lib/ui";

const EMPTY_FORM: ExpenseFormValues = { date: "", amount: "", merchant: "", category: "", note: "" };

export default function ExpensesPage() {
  const [expenses, setExpenses] = useState<Expense[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [merchantFilter, setMerchantFilter] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("");
  const [form, setForm] = useState<ExpenseFormValues>(EMPTY_FORM);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    const params = new URLSearchParams();
    if (merchantFilter.trim() !== "") params.set("merchant", merchantFilter.trim());
    if (categoryFilter !== "") params.set("category", categoryFilter);
    fetch(`/api/expenses?${params.toString()}`)
      .then((res) => res.json() as Promise<Expense[] | ErrorBody>)
      .then((data) => {
        if (cancelled) return;
        if (Array.isArray(data)) setExpenses(data);
        else setError(data.error);
        setLoaded(true);
      })
      .catch(() => {
        if (!cancelled) setError("Could not load expenses.");
      });
    return () => {
      cancelled = true;
    };
  }, [merchantFilter, categoryFilter, version]);

  function update(field: keyof ExpenseFormValues, value: string) {
    setForm((f) => ({ ...f, [field]: value }));
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    const res = await fetch("/api/expenses", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(formToExpenseBody(form)),
    });
    if (!res.ok) {
      const data = (await res.json()) as ErrorBody;
      setError(data.error);
      return;
    }
    setForm(EMPTY_FORM);
    setVersion((v) => v + 1);
  }

  async function onDelete(id: number) {
    setError(null);
    const res = await fetch(`/api/expenses/${id}`, { method: "DELETE" });
    if (!res.ok) {
      const data = (await res.json()) as ErrorBody;
      setError(data.error);
    }
    setVersion((v) => v + 1);
  }

  const total = expenses.reduce((sum, e) => sum + e.amountCents, 0);

  return (
    <>
      <h1>Expenses</h1>

      <section>
        <h2>Add an expense</h2>
        <form className="row" onSubmit={onSubmit}>
          <label>
            Date
            <input type="date" required value={form.date} onChange={(e) => update("date", e.target.value)} />
          </label>
          <label>
            Amount
            <input placeholder="12.50" required value={form.amount} onChange={(e) => update("amount", e.target.value)} />
          </label>
          <label>
            Merchant
            <input required value={form.merchant} onChange={(e) => update("merchant", e.target.value)} />
          </label>
          <label>
            Category
            <select value={form.category} onChange={(e) => update("category", e.target.value)}>
              <option value="">Auto</option>
              {CATEGORIES.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </label>
          <label>
            Note
            <input value={form.note} onChange={(e) => update("note", e.target.value)} />
          </label>
          <button type="submit">Add</button>
        </form>
        {error && <p className="error" role="alert">{error}</p>}
      </section>

      <section>
        <div className="row">
          <label>
            Merchant contains
            <input value={merchantFilter} onChange={(e) => setMerchantFilter(e.target.value)} />
          </label>
          <label>
            Category
            <select value={categoryFilter} onChange={(e) => setCategoryFilter(e.target.value)}>
              <option value="">All</option>
              {CATEGORIES.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </label>
          <a href="/api/export.csv">Export CSV</a>
        </div>

        {loaded && expenses.length === 0 ? (
          <p className="muted">No expenses yet.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Date</th>
                <th>Merchant</th>
                <th>Category</th>
                <th>Note</th>
                <th className="num">Amount</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {expenses.map((e) => (
                <tr key={e.id}>
                  <td>{e.date}</td>
                  <td>{e.merchant}</td>
                  <td>{e.category}</td>
                  <td>{e.note}</td>
                  <td className="num">{formatMoney(e.amountCents)}</td>
                  <td>
                    <button type="button" className="link" onClick={() => void onDelete(e.id)}>
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <th colSpan={4}>Total</th>
                <th className="num">{formatMoney(total)}</th>
                <th />
              </tr>
            </tfoot>
          </table>
        )}
      </section>
    </>
  );
}
