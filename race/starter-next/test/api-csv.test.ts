import { beforeEach, describe, expect, it } from "vitest";
import { GET } from "../app/api/export.csv/route";
import { POST } from "../app/api/import/route";
import { getDb, resetDb } from "../lib/db";
import { body, postText, seed } from "./helpers";

beforeEach(() => {
  resetDb();
});

describe("GET /api/export.csv", () => {
  it("returns every expense as CSV in list order", async () => {
    const store = seed();
    store.update(2, { note: "to airport, late" });
    const res = await GET();
    expect(res.status).toBe(200);
    expect(res.headers.get("content-type")).toBe("text/csv; charset=utf-8");
    expect(res.headers.get("content-disposition")).toBe('attachment; filename="expenses.csv"');
    expect(await res.text()).toBe(
      "id,date,amount,merchant,category,note\n" +
        "3,2024-04-02,9.99,Netflix,entertainment,\n" +
        '2,2024-03-05,23.00,Uber,transport,"to airport, late"\n' +
        "1,2024-03-01,12.50,Whole Foods,groceries,\n",
    );
  });
});

describe("POST /api/import", () => {
  it("adds the good rows in order and reports bad rows by line", async () => {
    seed();
    const csv = [
      "id,date,amount,merchant,category,note",
      "x,2024-05-01,$1,000.00,Sunset Apartments,,rent",
      "x,2024-05-02,4.50,Starbucks,,",
      "x,2024-05-31,abc,Uber,,",
      "x,2024-05-03,9.00,Uber,food,",
      'x,2024-05-04,"$1,000.00",Sunset Apartments,,rent',
    ].join("\n");
    const res = await POST(postText("/api/import", csv));
    expect(res.status).toBe(200);
    expect(res.headers.get("content-type")).toBe("application/json; charset=utf-8");
    const data = await body(res);
    expect(data.imported).toEqual([
      { id: 4, date: "2024-05-02", amountCents: 450, merchant: "Starbucks", category: "dining", note: "" },
      { id: 5, date: "2024-05-04", amountCents: 100000, merchant: "Sunset Apartments", category: "housing", note: "rent" },
    ]);
    expect(data.errors.map((e: { line: number }) => e.line)).toEqual([2, 4, 5]);
    expect(getDb().store.list().map((e) => e.id)).toEqual([5, 4, 3, 2, 1]);

    const bad = await body(await POST(postText("/api/import", "date,amount\n2024-01-01,5\n")));
    expect(bad).toEqual({ imported: [], errors: [{ line: 1, message: expect.any(String) }] });
    expect(getDb().store.list()).toHaveLength(5);
  });

  it("round-trips an export into an empty store", async () => {
    const store = seed();
    store.update(1, { note: 'said "hi"\nbye' });
    const before = store.list().map(({ id: _id, ...rest }) => rest);
    const csv = await (await GET()).text();
    resetDb();
    const data = await body(await POST(postText("/api/import", csv)));
    expect(data.errors).toEqual([]);
    expect(data.imported.map((e: { id: number }) => e.id)).toEqual([1, 2, 3]);
    expect(getDb().store.list().map(({ id: _id, ...rest }) => rest)).toEqual(before);
  });
});
