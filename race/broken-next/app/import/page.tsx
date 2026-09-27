import { useState, type ChangeEvent, type FormEvent } from "react";
import type { ErrorBody, ImportResponse } from "../../lib/api-types";
import { CSV_HEADER } from "../../lib/csv";
import { formatMoney } from "../../lib/money";
import { importSummary } from "../../lib/ui";

export default function ImportPage() {
  const [text, setText] = useState(`${CSV_HEADER}\n`);
  const [result, setResult] = useState<ImportResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (file) setText(await file.text());
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await fetch("/api/import", {
        method: "POST",
        headers: { "content-type": "text/csv" },
        body: text,
      });
      const data = (await res.json()) as ImportResponse | ErrorBody;
      if ("error" in data) {
        setError(data.error);
        setResult(null);
      } else {
        setResult(data);
      }
    } catch {
      setError("Import failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <h1>Import CSV</h1>

      <section>
        <p className="muted">
          The first line must be <code>{CSV_HEADER}</code>. The id column is ignored. Leave category empty to pick one
          automatically.
        </p>
        <form onSubmit={onSubmit}>
          <p>
            <input type="file" accept=".csv,text/csv" onChange={(e) => void onFile(e)} />
          </p>
          <textarea aria-label="CSV text" value={text} onChange={(e) => setText(e.target.value)} />
          <p>
            <button type="submit" disabled={busy}>
              {busy ? "Importing..." : "Import"}
            </button>
          </p>
        </form>
        {error && <p className="error" role="alert">{error}</p>}
      </section>

      {result && (
        <section>
          <h2>{importSummary(result)}</h2>
          {result.errors.length > 0 && (
            <>
              <h3>Rows with errors</h3>
              <table>
                <thead>
                  <tr>
                    <th className="num">Line</th>
                    <th>Problem</th>
                  </tr>
                </thead>
                <tbody>
                  {result.errors.map((e, i) => (
                    <tr key={`${e.line}-${i}`}>
                      <td className="num">{e.line}</td>
                      <td className="error">{e.message}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
          {result.imported.length > 0 && (
            <>
              <h3>Imported</h3>
              <table>
                <thead>
                  <tr>
                    <th>Id</th>
                    <th>Date</th>
                    <th>Merchant</th>
                    <th>Category</th>
                    <th className="num">Amount</th>
                  </tr>
                </thead>
                <tbody>
                  {result.imported.map((e) => (
                    <tr key={e.id}>
                      <td>{e.id}</td>
                      <td>{e.date}</td>
                      <td>{e.merchant}</td>
                      <td>{e.category}</td>
                      <td className="num">{formatMoney(e.amountCents)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </section>
      )}
    </>
  );
}
