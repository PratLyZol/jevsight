# broken-next: injected bugs

Answer key for `race/broken-next`. Keep this file outside the app directory so agents never see it.
`broken-next` is `reference-next` with the 12 changes below and a shorter README. Undoing all 12 makes every source file identical to `reference-next` again.

`npm run check` stops at the first failing stage, so an agent sees them in this order: typecheck (3), lint (2), test (6), build (1).

## Stage 1: typecheck (`tsc --noEmit`)

All three show up together in the first run.

| # | File | What was changed | Error the agent sees | Fix |
|---|---|---|---|---|
| T1 | `lib/expenses.ts` (`ExpenseStore.get`) | Return type `Expense \| undefined` narrowed to `Expense` | `TS2322: Type 'undefined' is not assignable to type 'Expense'` (line 93) | Restore `get(id: number): Expense \| undefined {` |
| T2 | `lib/budgets.ts` (`budgetStatus`) | Dropped the `remainingCents: budget - spent,` field from the pushed object | `TS2345 ... Property 'remainingCents' is missing` (line 43) | Add `remainingCents: budget - spent,` back after `spentCents: spent,` |
| T3 | `app/api/expenses/[id]/route.ts` (`DELETE`) | `getDb().store.remove(num)` became `remove(id)` (the raw string param) | `TS2345: Argument of type 'string' is not assignable to parameter of type 'number'` (line 10) | Pass `num`: `!getDb().store.remove(num)` |

If T2 or T3 were only "fixed" with a cast, tests would still fail: T2 breaks 3 budget/summary tests, T3 breaks 2 DELETE tests.

## Stage 2: lint (`eslint .`)

| # | File | What was changed | Error the agent sees | Fix |
|---|---|---|---|---|
| L1 | `lib/csv.ts` (`fromCsv`) | Destructure `const [, date, ...]` became `const [id, date, ...]`; `id` is never used | `@typescript-eslint/no-unused-vars` at 55:12 | Go back to `const [, date, amount, merchantRaw, category, note] =` |
| L2 | `app/page.tsx` (`ExpensesPage` effect) | Added `setError(null);` as the second line of the `useEffect` body | `react-hooks/set-state-in-effect` at 23:5 | Delete that `setError(null);` line |

## Stage 3: test (`vitest run`)

With stages 1 and 2 fixed, 10 of 58 tests fail across 7 files.

| # | File | What was changed | Failing tests | Fix |
|---|---|---|---|---|
| B1 | `lib/recurring.ts` (`expandRule`, monthly) | Month-end clamp uses `Date.UTC(year, month - 1, 0)` (last day of the previous month), so Feb gets day 31 and Apr gets 31 | recurring: "clamps day 31 to the last day of shorter months (leap year)", "clamps in non-leap years and skips a day before startDate" | `new Date(Date.UTC(year, month, 0)).getUTCDate()` |
| B2 | `lib/split.ts` (`splitByWeights`) | Base share uses `Math.round(exact / sum)` instead of `Math.floor`, so the leftover can go negative and cents get over-assigned (1000 by 3:3:1 gives 430/430/144) | split: "uses the largest remainder method with ties going to the earlier person" | `amountCents: Math.floor(exact / sum)` |
| B3 | `lib/ui.ts` (`categoryBreakdown`) | Sort comparator flipped to ascending: `a.totalCents - b.totalCents` | ui: "builds category breakdown rows sorted by total" | `rows.sort((a, b) => b.totalCents - a.totalCents)` |
| B4 | `lib/csv.ts` (`quoteField`) | `value.replace(/"/g, '""')` became `value.replace('"', '""')`, which only doubles the first quote | csv: "writes a header and quotes fields...", "round-trips exported expenses"; api-csv: "round-trips an export into an empty store" | Use the global regex: `value.replace(/"/g, '""')` |
| B5 | `lib/budgets.ts` (`budgetStatus`) | Over-budget check `spent >= budget` became `spent > budget`, so exactly 100% is "warning" | budgets: "raises a warning at 80% and over at 100%" | `if (spent >= budget) alert = "over";` |
| B6 | `app/api/expenses/route.ts` (`POST`) | `json(created, 201)` became `json(created)`, so it returns 200 | api-expenses: "creates an expense and GET lists it", "never reuses a deleted id" | `return json(created, 201);` |

## Stage 4: build (`next build`)

| # | File | What was changed | Error the agent sees | Fix |
|---|---|---|---|---|
| X1 | `app/import/page.tsx` | Removed the `"use client";` directive (and the blank line after it). The page uses `useState` and event handlers | Turbopack: `You're importing a module that depends on useState into a React Server Component module ... mark the file (or its parent) with the "use client" directive` at `./app/import/page.tsx:1:10` | Put `"use client";` back as the first line |

X1 passes `tsc --noEmit`, `eslint .` and all 58 tests. Only `next build` catches it.

## Verification (2026-09-25, Node 22.22.2, `npm ci` from the unchanged lockfile, `NEXT_TELEMETRY_DISABLED=1`)

Each bug alone on a clean tree was caught by exactly the stage listed above (T2 and T3 also break tests, but typecheck stops the run first). Cumulative run:

| State | Result | Wall time |
|---|---|---|
| All 12 bugs | `npm run check` fails at typecheck, 3 errors | 3.3 s |
| T1 to T3 fixed | typecheck passes (3.0 s); lint fails, 2 errors | 2.8 s |
| + L1, L2 fixed | lint passes (2.3 s); test fails, 10 failed / 48 passed | 3.2 s |
| + B1 to B6 fixed | test passes, 58/58 (3.1 s); build fails on X1 | 9.2 s |
| + X1 fixed | full `npm run check` passes (58/58, build OK), cold `.next` | 20.1 s |
| Same, warm `.next` cache | full `npm run check` passes | 13.5 s |
| `next build` alone, cold | passes | 12.2 s |

After all fixes, every file matches `reference-next` except README.md.
