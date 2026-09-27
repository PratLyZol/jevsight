import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { ExpenseStore } from "./expenses";

/**
 * Create (but do not start) an HTTP server for the JSON API and the static page.
 * The caller calls server.listen(port). See SPEC.md for the routes.
 */
export function createServer(store: ExpenseStore): http.Server {
  throw new Error("not implemented");
}

// Start the server when this file is run directly (npm start).
const isMain = process.argv[1] !== undefined && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (isMain) {
  const port = Number(process.env.PORT ?? 3000);
  const server = createServer(new ExpenseStore());
  server.listen(port, () => {
    console.log(`Expense tracker running at http://localhost:${port}`);
  });
}
