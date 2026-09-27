# Expense Tracker (Next.js) Spec

Build a small expense tracker with Next.js (App Router), React and TypeScript.
Every function in `lib/` that throws `new Error("not implemented")` needs a real body.
Every route handler in `app/api/` that returns `notImplemented()` needs a real body.
The three pages in `app/` are placeholders. Replace them with the pages described below.

Do not change exported names, signatures or types.
Do not edit `test/`, `package.json`, the config files, `app/layout.tsx`, `app/globals.css`, `lib/errors.ts`, `lib/db.ts`, `lib/http.ts` or `lib/api-types.ts`.
Do not add packages. Everything you need is installed.

You are done when `npm run check` passes. It runs, in order:

- `npm run typecheck` (`tsc --noEmit`, strict)
- `npm run lint` (`eslint .`)
- `npm test` (`vitest run`)
- `npm run build` (`next build`)

## Project layout

| Path | What it is |
|---|---|
| `lib/money.ts`, `lib/categories.ts`, `lib/expenses.ts`, `lib/budgets.ts`, `lib/recurring.ts`, `lib/reports.ts`, `lib/csv.ts`, `lib/split.ts` | Domain logic. You implement these. |
| `lib/summary.ts` | `buildSummary`, shared by the summary route and the summary page. You implement it. |
| `lib/ui.ts` | Small pure helpers used by the pages. You implement these. |
| `lib/errors.ts` | `ValidationError` and `NotFoundError`. Given. |
| `lib/db.ts` | The in-memory database: `getDb()`, `resetDb()`, `DEFAULT_BUDGETS`. Given. |
| `lib/http.ts` | `json()`, `errorJson()`, `notImplemented()` and content type constants. Given. |
| `lib/api-types.ts` | Request and response body types. Given. |
| `app/api/**/route.ts` | Route handlers. You implement these. |
| `app/page.tsx`, `app/summary/page.tsx`, `app/import/page.tsx` | Pages. You write these. |
| `app/layout.tsx`, `app/globals.css` | Root layout with the nav bar, and the styles. Given. |
| `test/` | Vitest tests. They import `lib/` modules and route handlers directly. |

Use relative imports (for example `../../../lib/db`). There is no `@/` path alias.

## General rules

- Money is always an integer number of cents (`Cents`).
- Dates are strings `YYYY-MM-DD`. Months are strings `YYYY-MM`. Compare them as strings.
- Bad input throws `ValidationError`. A missing id in `update` throws `NotFoundError`. Both live in `lib/errors.ts`.
- String order means plain `<` / `>` comparison (not `localeCompare`).
- Nothing may depend on the current date or the local time zone, except the default month on the summary page.
- The build must not need the network. Do not use `next/font/google` or any remote asset.

## lib/money.ts

- `parseMoney(input)`: trim the input. Accepted form: optional `-`, then optional `$`, then digits, then optional `.` with 1 or 2 digits. The whole part is either plain digits (`1234`) or correctly grouped with commas (`1,234,567`). Return cents, so `"12.5"` is 1250 and `"-$3.20"` is -320. Anything else throws `ValidationError`, including `""`, `"12."`, `".5"`, `"12.345"`, `"1,23"`, `"$-3"` and `"1 000"`.
- `formatMoney(cents)`: `"$1,234.56"` with comma thousands separators and exactly two decimals. Negative values get a leading minus: `"-$3.20"`. Non-integers throw `ValidationError`.
- `addMoney(a, b)` returns `a + b`. `sumMoney(values)` sums a list (0 for empty). Any non-integer input throws `ValidationError`.

## lib/categories.ts

- `CATEGORIES` is given. `isCategory(value)` is true only for an exact member of it.
- `categorize(merchant)`: lowercase and trim the merchant. Walk the rules below in order. The first keyword that is a substring of the merchant wins. No match, or an empty merchant, returns `"other"`.

| Order | Category | Keywords (in this order) |
|---|---|---|
| 1 | dining | uber eats, doordash, starbucks, chipotle, mcdonald, pizza, cafe, restaurant |
| 2 | groceries | whole foods, trader joe, kroger, safeway, costco, h-e-b |
| 3 | transport | uber, lyft, shell, chevron, parking, metro |
| 4 | housing | mortgage, apartments, landlord |
| 5 | utilities | comcast, xfinity, verizon, electric |
| 6 | entertainment | netflix, spotify, hulu, steam, cinema |
| 7 | health | cvs, walgreens, pharmacy, dental, clinic |
| 8 | shopping | amazon, target, walmart, best buy, ikea |
| 9 | travel | airlines, airbnb, marriott, hilton, expedia |

So `"UBER EATS"` is dining and `"Uber trip"` is transport.

## lib/expenses.ts

- `isValidDate(value)`: true only for a string `YYYY-MM-DD` that is a real calendar date (leap years count).
- `isValidMonth(value)`: true only for a string `YYYY-MM` with month 01 to 12.
- `ExpenseStore` keeps expenses in memory.
- `add(input)`: validate, store and return the new `Expense`. Ids start at 1 and go up by 1. Ids are never reused, even after `remove`.
  - `amountCents` must be an integer greater than 0.
  - `date` must pass `isValidDate`.
  - `merchant` is trimmed and must not be empty.
  - `category`: if missing or `""`, use `categorize(merchant)`. Otherwise it must pass `isCategory`.
  - `note` defaults to `""`.
- `update(id, patch)`: merge the patch into the existing expense, run the same validation, and return the result. Fields not in the patch keep their value (the category is not recomputed). Unknown id throws `NotFoundError`. If validation fails the stored expense is unchanged.
- `remove(id)` returns true if it removed something, else false. `get(id)` returns the expense or `undefined`.
- `list(filter)`: optional `from` and `to` (inclusive), `category` (exact), `merchant` (case-insensitive substring). Sort by date descending, then id ascending.
- Every returned expense is a copy. Mutating it must not change the store.

## lib/budgets.ts

- `budgetStatus(expenses, budgets, month)`: throw `ValidationError` if `month` is not valid or any budget is not a positive integer. Return one `BudgetStatus` for each category that has a budget, in `CATEGORIES` order. Only count expenses of that category whose date is in `month`.
  - `remainingCents = budgetCents - spentCents` (can be negative).
  - `percentUsed = Math.round(spent / budget * 100)`.
  - `alert` is `"over"` when spent >= budget, else `"warning"` when spent >= 80% of budget (use the exact ratio, not the rounded percent), else `"ok"`.
- `budgetAlerts(statuses)` returns the statuses whose alert is not `"ok"`, keeping order.

## lib/recurring.ts

- `expandRule(rule, from, to)`: return every occurrence with `from <= date <= to`, also `date >= rule.startDate` and `date <= rule.endDate` when `endDate` is set. Ascending by date. Each occurrence copies `ruleId` (from `rule.id`), `amountCents`, `merchant` and `category`. If `from > to` return `[]`. Invalid `from`, `to`, `startDate` or `endDate` throws `ValidationError`.
  - `weekly`: occurrences are `startDate`, `startDate + 7 days`, `+14 days`, and so on.
  - `monthly`: one occurrence per calendar month on `dayOfMonth`. If the month is shorter, use its last day (day 31 gives Feb 29 in 2024, Feb 28 in 2023, Apr 30). `dayOfMonth` must be an integer 1 to 31, else `ValidationError`.
  - Use UTC date math so results never depend on the local time zone.
- `expandRules(rules, from, to)`: all occurrences of all rules, sorted by date ascending, then `ruleId` ascending.

## lib/reports.ts

- `monthlySummary(expenses, month)`: throw `ValidationError` for a bad month. Use only expenses dated in `month`.
  - `totalCents` and `count`.
  - `byCategory`: sum per category. Include only categories with at least one expense.
  - `topMerchants`: group by exact merchant string, sort by total descending then merchant ascending, keep the first 3.
  - `dailyAverageCents = Math.round(totalCents / daysInMonth)`, where daysInMonth is the full length of that month.
- `previousMonthOf(month)`: the month before, so `"2025-01"` gives `"2024-12"`. Bad month throws `ValidationError`.
- `monthOverMonth(expenses, month)`: totals for `month` and the previous month. `changePercent = (current - previous) / previous * 100` rounded to 1 decimal with `Math.round(x * 10) / 10`. If previous is 0, `changePercent` is `null`.

## lib/csv.ts

- `toCsv(expenses)`: first line is `CSV_HEADER`. Then one line per expense in the given order: `id,date,amount,merchant,category,note`. `amount` is a plain decimal with two places and no `$` or commas (1250 becomes `12.50`). A field is wrapped in double quotes only if it contains a comma, a double quote, `\r` or `\n`. Inside quotes, `"` becomes `""`. Every line, including the last, ends with `\n`.
- `fromCsv(text)`: never throws. Returns `{ rows, errors }`.
  - Records end at `\n` or `\r\n` outside quotes. A quoted field may contain commas, doubled quotes and line breaks (keep them as they are).
  - Line numbers are 1-based physical lines. A record's line number is the line where it starts. The header is line 1.
  - If the first record is not exactly the header, return no rows and one error with `line: 1`. Empty text counts as a missing header.
  - Skip completely blank lines.
  - Each data record must have 6 fields. The `id` field is ignored. `date` must be valid. `amount` goes through `parseMoney` and must be > 0. `merchant` is trimmed and must not be empty. `category` must be empty or a known category.
  - A bad record adds `{ line, message }` to `errors` (any non-empty message) and is skipped. Good records become `NewExpense` objects `{ date, amountCents, merchant, note }`, plus `category` only when the field is not empty.
  - An unterminated quoted field adds one error for the line where that record starts.

## lib/split.ts

- All functions throw `ValidationError` for an empty list of people, duplicate or empty names, or a total that is not a non-negative integer.
- `splitEven(total, people)`: everyone gets `floor(total / n)`. The leftover cents go 1 each to the first people in input order. Returns `{ person, amountCents }[]` in input order.
- `splitByWeights(total, weights)`: weights must be positive integers. Each person first gets `floor(total * weight / sumOfWeights)`. Hand out the leftover cents 1 each, largest remainder `(total * weight) % sumOfWeights` first, ties to the earlier person. Returns shares in input order.
- `settleUp(payments)`: `paidCents` must be a non-negative integer. Compute each person's share of the total with `splitEven` (input order). Balance is paid minus share. Then loop: pick the most negative balance (the debtor) and the most positive balance (the creditor). On ties pick the earlier person. Add a transfer `{ from: debtor, to: creditor, amountCents: min(debt, credit) }` and update both balances. Stop when no balance is non-zero. Return transfers in the order made.

## lib/summary.ts

- `buildSummary(expenses, budgets, month)` returns a `SummaryResponse`:
  - `summary`: `monthlySummary(expenses, month)`.
  - `budgets`: `budgetStatus(expenses, budgets, month)`.
  - `alerts`: `budgetAlerts` of those statuses.
  - `comparison`: `monthOverMonth(expenses, month)`.
- A bad month or a bad budget throws `ValidationError`.

## lib/ui.ts

- `categoryBreakdown({ byCategory, totalCents })`: one row `{ category, totalCents, percent }` per category present in `byCategory`. `percent = Math.round(cents / totalCents * 1000) / 10` (0 when `totalCents` is 0). Sort by `totalCents` descending. Ties keep `CATEGORIES` order.
- `budgetBarPercent({ percentUsed })`: `percentUsed` clamped to 0..100.
- `alertLabel(alert)`: `"ok"` gives `"On track"`, `"warning"` gives `"Almost there"`, `"over"` gives `"Over budget"`.
- `changeLabel(changePercent)`: `null` gives `"n/a"`. A positive number gets a plus sign: `10` gives `"+10%"`. Zero gives `"0%"`. A negative number keeps its minus: `-68.2` gives `"-68.2%"`. Use the plain `String(x)` form of the number.
- `formToExpenseBody(form)`: trim every value. Always return `date`, `amount` and `merchant`. Add `category` and `note` only when they are not empty after trimming.
- `importSummary({ imported, errors })`: `"Imported N expense."` when N is 1, else `"Imported N expenses."`. When there are errors, append `" 1 row had errors."` or `" M rows had errors."`. Examples: `"Imported 0 expenses."`, `"Imported 2 expenses. 1 row had errors."`.

## The database (lib/db.ts, given)

- `getDb()` returns `{ store, budgets }`. It is created on first use and kept on `globalThis`, so every route and page in one server process shares it.
- `resetDb(budgets?)` swaps in a fresh empty store. Tests call it before each case. Budgets default to `DEFAULT_BUDGETS`.
- Route handlers and the summary page must always call `getDb()` when they run. Never keep the store in a variable at module load time, or tests that call `resetDb()` will see stale data.

## API routes

Every route file exports `const dynamic = "force-dynamic"` (already in place). Route handlers take a standard `Request` and return a standard `Response`. Tests call them directly, for example `await GET(new Request("http://localhost/api/expenses?category=dining"))`.

All JSON responses use `content-type: application/json; charset=utf-8`. Use `json(data, status)` from `lib/http.ts`. Error bodies are `{ "error": "<message>" }` with a non-empty message. Use `errorJson(status, message)`.

### GET /api/expenses

File: `app/api/expenses/route.ts`, export `GET(request)`.

- Query params `from`, `to`, `category`, `merchant` fill the `ExpenseFilter` when present and non-empty. Empty values are ignored.
- `from` or `to` that fails `isValidDate` gives 400. A `category` that fails `isCategory` gives 400.
- 200 with `getDb().store.list(filter)`, a JSON array of `Expense`:

```json
[{ "id": 2, "date": "2024-03-05", "amountCents": 2300, "merchant": "Uber", "category": "transport", "note": "" }]
```

### POST /api/expenses

File: `app/api/expenses/route.ts`, export `POST(request)`.

- The body is JSON: `{ date, amount?, amountCents?, merchant, category?, note? }` (type `ExpenseBody`).
- If `amountCents` is a number, use it. Else if `amount` is a string, parse it with `parseMoney`. Else 400.
- A missing or non-string `date` or `merchant` becomes `""` and fails validation.
- If `category` is present it is passed to the store (a non-string is converted with `String`). If `note` is present it must be a string, else 400.
- 201 with the created `Expense`.
- 400 for a body that is not valid JSON, JSON that is not an object (`null`, arrays, numbers), a missing amount, or any `ValidationError` from the store. Nothing is stored on a 400.

### DELETE /api/expenses/[id]

File: `app/api/expenses/[id]/route.ts`, export `DELETE(request, context)`. `context.params` is a `Promise<{ id: string }>`. Await it.

- If `id` is all digits (`/^\d+$/`) and the store removes it: 204 with an empty body (`new Response(null, { status: 204 })`).
- Otherwise 404 with an error body. This covers `"abc"`, `"1.5"`, `"-1"` and unknown ids.

### GET /api/summary?month=YYYY-MM

File: `app/api/summary/route.ts`, export `GET(request)`.

- A missing or empty `month` gives 400. A month that fails `isValidMonth` gives 400.
- 200 with `buildSummary(store.list(), getDb().budgets, month)`. Example (the `budgets` list is shortened):

```json
{
  "summary": {
    "month": "2024-03",
    "totalCents": 3550,
    "count": 2,
    "byCategory": { "groceries": 1250, "transport": 2300 },
    "topMerchants": [{ "merchant": "Uber", "totalCents": 2300 }, { "merchant": "Whole Foods", "totalCents": 1250 }],
    "dailyAverageCents": 115
  },
  "budgets": [
    { "category": "groceries", "budgetCents": 1500, "spentCents": 1250, "remainingCents": 250, "percentUsed": 83, "alert": "warning" }
  ],
  "alerts": [
    { "category": "groceries", "budgetCents": 1500, "spentCents": 1250, "remainingCents": 250, "percentUsed": 83, "alert": "warning" }
  ],
  "comparison": { "month": "2024-03", "previousMonth": "2024-02", "currentCents": 3550, "previousCents": 0, "changePercent": null }
}
```

### GET /api/export.csv

File: `app/api/export.csv/route.ts`, export `GET()` (no arguments).

- 200 with body `toCsv(getDb().store.list())`. So rows are in list order: date descending, then id ascending.
- Headers: `content-type: text/csv; charset=utf-8` (`CSV_CONTENT_TYPE`) and `content-disposition: attachment; filename="expenses.csv"`.

### POST /api/import

File: `app/api/import/route.ts`, export `POST(request)`.

- The body is raw CSV text (read it with `request.text()`).
- Run `fromCsv`. Add every good row with `store.add`, in order.
- Always 200 with `ImportResponse`: `imported` is the created expenses in order, `errors` is the `errors` array from `fromCsv` unchanged. Error message text is up to you.

```json
{
  "imported": [{ "id": 4, "date": "2024-05-02", "amountCents": 450, "merchant": "Starbucks", "category": "dining", "note": "" }],
  "errors": [{ "line": 2, "message": "expected 6 fields, got 7" }]
}
```

- A wrong header gives `{ "imported": [], "errors": [{ "line": 1, "message": "..." }] }` and stores nothing.

## Pages

Pages are not covered by the tests, but they must type-check, lint and build. They use the helpers in `lib/ui.ts`, which are tested. Show money with `formatMoney`. Use the class names in `app/globals.css` if you like.

### app/page.tsx (Expenses)

- A client component: the file starts with `"use client"`.
- Loads the list from `GET /api/expenses` and shows a table: date, merchant, category, note, amount, and a Delete button per row. Show a total row.
- Filters: a "merchant contains" text input and a category select ("All" plus every category). Changing either reloads the list with the matching query params.
- An add form with date, amount, merchant, category (an "Auto" option with value `""` plus every category) and note. On submit, POST `formToExpenseBody(form)` as JSON. On success clear the form and reload. On a 400 show the `error` message.
- Delete calls `DELETE /api/expenses/:id` and reloads.
- A link to `/api/export.csv`.
- Lint runs the React hooks rules. Do not call `setState` synchronously in an effect body. Setting state in a `fetch(...).then(...)` callback is fine.

### app/summary/page.tsx (Summary)

- A server component (no `"use client"`). It reads the store with `getDb()` and calls `buildSummary`. It does not fetch the API.
- Props: `{ searchParams: Promise<{ month?: string | string[] }> }`. Await them.
- The month is `?month=` when it is a valid month. Otherwise the month of the newest expense. With no expenses, the current UTC month.
- A GET form with `<input type="month" name="month">` to pick the month.
- Stats: total, count, daily average, and the change against the previous month using `changeLabel`.
- A category breakdown table from `categoryBreakdown(summary)` with total and share (`percent`).
- One budget bar per budget status. The bar width is `budgetBarPercent(status)` percent. Show spent, budget and `alertLabel(status.alert)`.
- The top merchants list.

### app/import/page.tsx (Import)

- A client component: the file starts with `"use client"`.
- A textarea for CSV text (start it with the header line) and a file input that loads a chosen file into the textarea.
- An Import button that POSTs the text to `/api/import` with `content-type: text/csv`.
- After an import show `importSummary(result)`, a table of row errors (line and message), and a table of the imported expenses.
