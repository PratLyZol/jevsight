# Expense Tracker (Next.js)

A Next.js App Router app with an in-memory expense store, a JSON API and three pages.
Read `SPEC.md` for the full spec.

```
npm install
npm run check   # typecheck, lint, test, build
npm run dev     # http://localhost:3000
```

Notes:

- The build needs no network. It uses system fonts and no remote assets.
- Set `NEXT_TELEMETRY_DISABLED=1` to turn off Next.js telemetry. The race harness does this.
- Data lives in memory and resets when the server restarts.
