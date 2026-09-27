import { getDb } from "../../lib/db";
import { isValidMonth } from "../../lib/expenses";
import { formatMoney } from "../../lib/money";
import { buildSummary } from "../../lib/summary";
import { alertLabel, budgetBarPercent, categoryBreakdown, changeLabel } from "../../lib/ui";

export const dynamic = "force-dynamic";

function currentMonth(): string {
  return new Date().toISOString().slice(0, 7);
}

export default async function SummaryPage({ searchParams }: { searchParams: Promise<{ month?: string | string[] }> }) {
  const params = await searchParams;
  const { store, budgets } = getDb();
  const expenses = store.list();
  const requested = typeof params.month === "string" ? params.month : "";
  const month = isValidMonth(requested) ? requested : (expenses[0]?.date.slice(0, 7) ?? currentMonth());
  const { summary, budgets: statuses, comparison } = buildSummary(expenses, budgets, month);
  const rows = categoryBreakdown(summary);

  return (
    <>
      <h1>Summary for {month}</h1>

      <section>
        <form className="row" method="get">
          <label>
            Month
            <input type="month" name="month" defaultValue={month} />
          </label>
          <button type="submit">Show</button>
        </form>
      </section>

      <section className="stats">
        <div className="stat">
          <span className="muted">Total</span>
          <b>{formatMoney(summary.totalCents)}</b>
        </div>
        <div className="stat">
          <span className="muted">Expenses</span>
          <b>{summary.count}</b>
        </div>
        <div className="stat">
          <span className="muted">Daily average</span>
          <b>{formatMoney(summary.dailyAverageCents)}</b>
        </div>
        <div className="stat">
          <span className="muted">Vs {comparison.previousMonth}</span>
          <b>{changeLabel(comparison.changePercent)}</b>
        </div>
      </section>

      <section>
        <h2>By category</h2>
        {rows.length === 0 ? (
          <p className="muted">No expenses in this month.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Category</th>
                <th className="num">Total</th>
                <th className="num">Share</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.category}>
                  <td>{r.category}</td>
                  <td className="num">{formatMoney(r.totalCents)}</td>
                  <td className="num">{r.percent}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section>
        <h2>Budgets</h2>
        <table>
          <thead>
            <tr>
              <th>Category</th>
              <th>Used</th>
              <th className="num">Spent</th>
              <th className="num">Budget</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {statuses.map((s) => (
              <tr key={s.category}>
                <td>{s.category}</td>
                <td>
                  <div className="bar" title={`${s.percentUsed}%`}>
                    <span className={`bar-${s.alert}`} style={{ width: `${budgetBarPercent(s)}%` }} />
                  </div>
                </td>
                <td className="num">{formatMoney(s.spentCents)}</td>
                <td className="num">{formatMoney(s.budgetCents)}</td>
                <td>{alertLabel(s.alert)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section>
        <h2>Top merchants</h2>
        {summary.topMerchants.length === 0 ? (
          <p className="muted">None.</p>
        ) : (
          <ol>
            {summary.topMerchants.map((m) => (
              <li key={m.merchant}>
                {m.merchant}: {formatMoney(m.totalCents)}
              </li>
            ))}
          </ol>
        )}
      </section>
    </>
  );
}
