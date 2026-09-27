# Expense Tracker Spec

Implement every function and method in `src/` that currently throws `new Error("not implemented")`.
Do not change exported names, signatures or types. Do not edit `test/`, `public/` or `src/errors.ts`.
You are done when `npm run typecheck` and `npm test` both pass.

## General rules

- Money is always an integer number of cents (`Cents`).
- Dates are strings `YYYY-MM-DD`. Months are strings `YYYY-MM`. Compare them as strings.
- Bad input throws `ValidationError`. A missing id in `update` throws `NotFoundError`. Both live in `src/errors.ts`.
- String order means plain `<` / `>` comparison (not `localeCompare`).
- No external packages. Use only Node built-ins.

## money.ts

- `parseMoney(input)`: trim the input. Accepted form: optional `-`, then optional `$`, then digits, then optional `.` with 1 or 2 digits. The whole part is either plain digits (`1234`) or correctly grouped with commas (`1,234,567`). Return cents, so `"12.5"` is 1250 and `"-$3.20"` is -320. Anything else throws `ValidationError`, including `""`, `"12."`, `".5"`, `"12.345"`, `"1,23"`, `"$-3"` and `"1 000"`.
- `formatMoney(cents)`: `"$1,234.56"` with comma thousands separators and exactly two decimals. Negative values get a leading minus: `"-$3.20"`. Non-integers throw `ValidationError`.
- `addMoney(a, b)` returns `a + b`. `sumMoney(values)` sums a list (0 for empty). Any non-integer input throws `ValidationError`.

## categories.ts

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

## expenses.ts

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

## budgets.ts

- `budgetStatus(expenses, budgets, month)`: throw `ValidationError` if `month` is not valid or any budget is not a positive integer. Return one `BudgetStatus` for each category that has a budget, in `CATEGORIES` order. Only count expenses of that category whose date is in `month`.
  - `remainingCents = budgetCents - spentCents` (can be negative).
  - `percentUsed = Math.round(spent / budget * 100)`.
  - `alert` is `"over"` when spent >= budget, else `"warning"` when spent >= 80% of budget (use the exact ratio, not the rounded percent), else `"ok"`.
- `budgetAlerts(statuses)` returns the statuses whose alert is not `"ok"`, keeping order.

## recurring.ts

- `expandRule(rule, from, to)`: return every occurrence with `from <= date <= to`, also `date >= rule.startDate` and `date <= rule.endDate` when `endDate` is set. Ascending by date. Each occurrence copies `ruleId` (from `rule.id`), `amountCents`, `merchant` and `category`. If `from > to` return `[]`. Invalid `from`, `to`, `startDate` or `endDate` throws `ValidationError`.
  - `weekly`: occurrences are `startDate`, `startDate + 7 days`, `+14 days`, and so on.
  - `monthly`: one occurrence per calendar month on `dayOfMonth`. If the month is shorter, use its last day (day 31 gives Feb 29 in 2024, Feb 28 in 2023, Apr 30). `dayOfMonth` must be an integer 1 to 31, else `ValidationError`.
  - Use UTC date math so results never depend on the local time zone.
- `expandRules(rules, from, to)`: all occurrences of all rules, sorted by date ascending, then `ruleId` ascending.

## reports.ts

- `monthlySummary(expenses, month)`: throw `ValidationError` for a bad month. Use only expenses dated in `month`.
  - `totalCents` and `count`.
  - `byCategory`: sum per category. Include only categories with at least one expense.
  - `topMerchants`: group by exact merchant string, sort by total descending then merchant ascending, keep the first 3.
  - `dailyAverageCents = Math.round(totalCents / daysInMonth)`, where daysInMonth is the full length of that month.
- `previousMonthOf(month)`: the month before, so `"2025-01"` gives `"2024-12"`. Bad month throws `ValidationError`.
- `monthOverMonth(expenses, month)`: totals for `month` and the previous month. `changePercent = (current - previous) / previous * 100` rounded to 1 decimal with `Math.round(x * 10) / 10`. If previous is 0, `changePercent` is `null`.

## csv.ts

- `toCsv(expenses)`: first line is `CSV_HEADER`. Then one line per expense in the given order: `id,date,amount,merchant,category,note`. `amount` is a plain decimal with two places and no `$` or commas (1250 becomes `12.50`). A field is wrapped in double quotes only if it contains a comma, a double quote, `\r` or `\n`. Inside quotes, `"` becomes `""`. Every line, including the last, ends with `\n`.
- `fromCsv(text)`: never throws. Returns `{ rows, errors }`.
  - Records end at `\n` or `\r\n` outside quotes. A quoted field may contain commas, doubled quotes and line breaks (keep them as they are).
  - Line numbers are 1-based physical lines. A record's line number is the line where it starts. The header is line 1.
  - If the first record is not exactly the header, return no rows and one error with `line: 1`. Empty text counts as a missing header.
  - Skip completely blank lines.
  - Each data record must have 6 fields. The `id` field is ignored. `date` must be valid. `amount` goes through `parseMoney` and must be > 0. `merchant` is trimmed and must not be empty. `category` must be empty or a known category.
  - A bad record adds `{ line, message }` to `errors` (any non-empty message) and is skipped. Good records become `NewExpense` objects `{ date, amountCents, merchant, note }`, plus `category` only when the field is not empty.
  - An unterminated quoted field adds one error for the line where that record starts.

## split.ts

- All functions throw `ValidationError` for an empty list of people, duplicate or empty names, or a total that is not a non-negative integer.
- `splitEven(total, people)`: everyone gets `floor(total / n)`. The leftover cents go 1 each to the first people in input order. Returns `{ person, amountCents }[]` in input order.
- `splitByWeights(total, weights)`: weights must be positive integers. Each person first gets `floor(total * weight / sumOfWeights)`. Hand out the leftover cents 1 each, largest remainder `(total * weight) % sumOfWeights` first, ties to the earlier person. Returns shares in input order.
- `settleUp(payments)`: `paidCents` must be a non-negative integer. Compute each person's share of the total with `splitEven` (input order). Balance is paid minus share. Then loop: pick the most negative balance (the debtor) and the most positive balance (the creditor). On ties pick the earlier person. Add a transfer `{ from: debtor, to: creditor, amountCents: min(debt, credit) }` and update both balances. Stop when no balance is non-zero. Return transfers in the order made.

## server.ts

`createServer(store)` returns a `node:http` Server that is not listening yet. All JSON responses use `content-type: application/json; charset=utf-8`. Error bodies are `{ "error": "<message>" }`.

| Method and path | Behavior |
|---|---|
| `GET /` | 200, the file `public/index.html` with `content-type: text/html; charset=utf-8`. Resolve the path from `import.meta.url`, not the working directory. |
| `GET /api/expenses` | 200, `store.list(filter)`. Query params `from`, `to`, `category`, `merchant` fill the filter when present and non-empty. |
| `POST /api/expenses` | JSON body `{ date, amount?, amountCents?, merchant, category?, note? }`. If `amountCents` is a number use it, else parse the `amount` string with `parseMoney`. Return 201 with the created expense. Bad JSON, a body that is not a JSON object, a missing amount, or any `ValidationError` gives 400. |
| `DELETE /api/expenses/:id` | 204 with an empty body if removed. 404 if the id is not a whole number or does not exist. |
| `GET /api/summary?month=YYYY-MM` | 200, `monthlySummary(store.list(), month)`. Missing or invalid month gives 400. |
| anything else | 404. |

The main block at the bottom of `server.ts` is already written. `npm start` runs it on `PORT` or 3000.
