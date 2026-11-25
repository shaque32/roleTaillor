import { NextResponse, type NextRequest } from "next/server";
import { apiBaseUrl, clientAddressHeaders, errorResponse, isSameOrigin, readBodyLimited } from "@/lib/server-config";
import { clearSessionCookie } from "@/lib/session-cookie";

export const dynamic = "force-dynamic";

/** Public, token-less auth actions. Token-minting ones (login, register) live in /api/session. */
const ACTIONS = new Set(["forgot-password", "reset-password", "verify-email"]);

export async function POST(req: NextRequest, ctx: { params: Promise<{ action: string }> }) {
  const { action } = await ctx.params;
  if (!ACTIONS.has(action)) return errorResponse(404, "not_found", "Not found.");
  if (!isSameOrigin(req)) return errorResponse(403, "forbidden_origin", "Cross-origin request rejected.");

  let body: unknown;
  try {
    const raw = await readBodyLimited(req, 16 * 1024);
    if (raw === null) return errorResponse(413, "payload_too_large", "That request is too large.");
    body = JSON.parse(new TextDecoder().decode(raw));
  } catch {
    return errorResponse(400, "invalid_body", "Expected a JSON body.");
  }
  if (!body || typeof body !== "object" || Array.isArray(body)) {
    return errorResponse(400, "invalid_body", "Expected a JSON body.");
  }

  const correlationId = req.headers.get("x-correlation-id") ?? crypto.randomUUID();
  let upstream: Response;
  try {
    upstream = await fetch(`${apiBaseUrl()}/auth/${action}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Correlation-ID": correlationId, ...clientAddressHeaders(req) },
      body: JSON.stringify(body),
      cache: "no-store",
    });
  } catch {
    return errorResponse(502, "upstream_unavailable", "We couldn't reach RoleTailor. Please try again shortly.");
  }

  const text = await upstream.text();
  const headers: Record<string, string> = { "Content-Type": upstream.headers.get("content-type") ?? "application/json" };
  const retryAfter = upstream.headers.get("retry-after");
  if (retryAfter) headers["Retry-After"] = retryAfter;
  const res = new NextResponse(text || null, { status: upstream.status, headers });
  // A successful reset revokes every session of the user, so the cookie is dead anyway.
  if (action === "reset-password" && upstream.ok) clearSessionCookie(res);
  return res;
}
