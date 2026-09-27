import { getDb } from "../../../../lib/db";
import { errorJson } from "../../../../lib/http";

export const dynamic = "force-dynamic";

/** DELETE /api/expenses/:id */
export async function DELETE(request: Request, context: { params: Promise<{ id: string }> }): Promise<Response> {
  const { id } = await context.params;
  const num = /^\d+$/.test(id) ? Number(id) : Number.NaN;
  if (Number.isNaN(num) || !getDb().store.remove(id)) {
    return errorJson(404, `expense ${id} not found`);
  }
  return new Response(null, { status: 204 });
}
