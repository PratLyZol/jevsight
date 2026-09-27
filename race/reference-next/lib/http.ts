// Response helpers for the API routes. This file is complete; you do not need to change it.

export const JSON_CONTENT_TYPE = "application/json; charset=utf-8";
export const CSV_CONTENT_TYPE = "text/csv; charset=utf-8";

/** A JSON response with `content-type: application/json; charset=utf-8`. */
export function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), { status, headers: { "content-type": JSON_CONTENT_TYPE } });
}

/** An error response. The body is `{ "error": message }`. */
export function errorJson(status: number, message: string): Response {
  return json({ error: message }, status);
}

/** 501 placeholder used by unfinished route handlers. */
export function notImplemented(): Response {
  return errorJson(501, "not implemented");
}
