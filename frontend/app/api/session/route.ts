import { NextResponse, type NextRequest } from "next/server";
import {
  SESSION_COOKIE,
  apiBaseUrl,
  clientAddressHeaders,
  errorResponse,
  isSameOrigin,
  readBodyLimited,
} from "@/lib/server-config";
import { clearSessionCookie, setSessionCookie } from "@/lib/session-cookie";

export const dynamic = "force-dynamic";

/** GET: is there a session cookie? (The token itself is never exposed to JS.) */
export async function GET(req: NextRequest) {
  return NextResponse.json({ authenticated: Boolean(req.cookies.get(SESSION_COOKIE)?.value) });
}

/**
 * POST { action: "login" | "register", ...body }
 * Proxies to /auth/login or /auth/register, stores the token in an httpOnly cookie,
 * and returns { user, organization } without the token.
 */
export async function POST(req: NextRequest) {
  if (!isSameOrigin(req)) return errorResponse(403, "forbidden_origin", "Cross-origin request rejected.");

  let payload: Record<string, unknown>;
  try {
    const raw = await readBodyLimited(req, 16 * 1024);
    if (raw === null) return errorResponse(413, "payload_too_large", "That request is too large.");
    payload = JSON.parse(new TextDecoder().decode(raw)) as Record<string, unknown>;
  } catch {
    return errorResponse(400, "invalid_body", "Expected a JSON body.");
  }
  const { action, ...body } = payload;
  if (action !== "login" && action !== "register") {
    return errorResponse(400, "invalid_action", "action must be login or register.");
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
  if (!upstream.ok) {
    return new NextResponse(text || null, {
      status: upstream.status,
      headers: { "Content-Type": upstream.headers.get("content-type") ?? "application/json" },
    });
  }

  const data = JSON.parse(text) as { token: string; expires_at?: string; user: unknown; organization: unknown };
  const res = NextResponse.json({ user: data.user, organization: data.organization }, { status: upstream.status });
  setSessionCookie(res, data.token, data.expires_at);
  return res;
}

/** DELETE: logout upstream (best effort) and clear the cookie. */
export async function DELETE(req: NextRequest) {
  if (!isSameOrigin(req)) return errorResponse(403, "forbidden_origin", "Cross-origin request rejected.");
  const token = req.cookies.get(SESSION_COOKIE)?.value;
  if (token) {
    try {
      await fetch(`${apiBaseUrl()}/auth/logout`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        cache: "no-store",
      });
    } catch {
      /* cookie is cleared regardless */
    }
  }
  const res = new NextResponse(null, { status: 204 });
  clearSessionCookie(res);
  return res;
}
