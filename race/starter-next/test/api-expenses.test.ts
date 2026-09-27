import { beforeEach, describe, expect, it } from "vitest";
import { DELETE } from "../app/api/expenses/[id]/route";
import { GET, POST } from "../app/api/expenses/route";
import { getDb, resetDb } from "../lib/db";
import { BASE, body, get, postJson, seed } from "./helpers";

function del(id: string): Promise<Response> {
  return DELETE(new Request(`${BASE}/api/expenses/${id}`, { method: "DELETE" }), { params: Promise.resolve({ id }) });
}

async function ids(query: string): Promise<number[]> {
  const res = await GET(get(`/api/expenses${query}`));
  expect(res.status).toBe(200);
  return ((await body(res)) as { id: number }[]).map((e) => e.id);
}

beforeEach(() => {
  resetDb();
});

describe("POST /api/expenses", () => {
  it("creates an expense and GET lists it", async () => {
    const res = await POST(
      postJson("/api/expenses", JSON.stringify({ date: "2024-03-09", amount: "$1,234.50", merchant: "Whole Foods", note: "party" })),
    );
    expect(res.status).toBe(201);
    expect(res.headers.get("content-type")).toBe("application/json; charset=utf-8");
    expect(await body(res)).toEqual({
      id: 1, date: "2024-03-09", amountCents: 123450, merchant: "Whole Foods", category: "groceries", note: "party",
    });

    const res2 = await POST(
      postJson("/api/expenses", JSON.stringify({ date: "2024-03-10", amountCents: 500, merchant: "Lyft", category: "travel" })),
    );
    expect(res2.status).toBe(201);
    expect((await body(res2)).category).toBe("travel");

    const list = await GET(get("/api/expenses"));
    expect(list.status).toBe(200);
    expect(list.headers.get("content-type")).toBe("application/json; charset=utf-8");
    expect(((await body(list)) as { id: number }[]).map((e) => e.id)).toEqual([2, 1]);
  });

  it("returns 400 with an error message for invalid input", async () => {
    for (const payload of [
      JSON.stringify({ date: "2024-02-30", amount: "5", merchant: "Uber" }),
      JSON.stringify({ date: "2024-02-01", amount: "five", merchant: "Uber" }),
      JSON.stringify({ date: "2024-02-01", amount: "-5", merchant: "Uber" }),
      JSON.stringify({ date: "2024-02-01", amount: "5", merchant: "" }),
      JSON.stringify({ date: "2024-02-01", amount: "5", merchant: "Uber", category: "food" }),
      JSON.stringify({ date: "2024-02-01", merchant: "Uber" }),
      JSON.stringify([1, 2]),
      "null",
      "{not json",
    ]) {
      const res = await POST(postJson("/api/expenses", payload));
      expect(res.status, payload).toBe(400);
      expect(res.headers.get("content-type")).toBe("application/json; charset=utf-8");
      expect(typeof (await body(res)).error).toBe("string");
    }
    expect(getDb().store.list()).toEqual([]);
  });
});

describe("GET /api/expenses", () => {
  it("filters with query parameters and ignores empty ones", async () => {
    seed();
    expect(await ids("")).toEqual([3, 2, 1]);
    expect(await ids("?from=2024-03-02&to=2024-03-31")).toEqual([2]);
    expect(await ids("?category=groceries")).toEqual([1]);
    expect(await ids("?merchant=NET")).toEqual([3]);
    expect(await ids("?from=&to=&category=&merchant=")).toEqual([3, 2, 1]);
  });

  it("returns 400 for an invalid date or unknown category filter", async () => {
    seed();
    for (const query of ["?from=2024-13-01", "?to=March", "?category=food", "?category=Groceries"]) {
      const res = await GET(get(`/api/expenses${query}`));
      expect(res.status, query).toBe(400);
      expect(typeof (await body(res)).error).toBe("string");
    }
  });
});

describe("DELETE /api/expenses/[id]", () => {
  it("returns 204 with an empty body, then 404", async () => {
    const store = seed();
    const res = await del("2");
    expect(res.status).toBe(204);
    expect(await res.text()).toBe("");
    expect(store.get(2)).toBeUndefined();
    const again = await del("2");
    expect(again.status).toBe(404);
    expect(typeof (await body(again)).error).toBe("string");
    for (const bad of ["abc", "1.5", "-1", "99"]) {
      expect((await del(bad)).status, bad).toBe(404);
    }
    expect(await ids("")).toEqual([3, 1]);
  });

  it("never reuses a deleted id", async () => {
    seed();
    expect((await del("3")).status).toBe(204);
    const res = await POST(postJson("/api/expenses", JSON.stringify({ date: "2024-05-01", amountCents: 100, merchant: "Kroger" })));
    expect(res.status).toBe(201);
    expect((await body(res)).id).toBe(4);
    expect(await ids("")).toEqual([4, 2, 1]);
  });
});
