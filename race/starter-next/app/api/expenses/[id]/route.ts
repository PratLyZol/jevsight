import { notImplemented } from "../../../../lib/http";

export const dynamic = "force-dynamic";

/** DELETE /api/expenses/:id (see SPEC.md) */
export async function DELETE(request: Request, context: { params: Promise<{ id: string }> }): Promise<Response> {
  return notImplemented();
}
