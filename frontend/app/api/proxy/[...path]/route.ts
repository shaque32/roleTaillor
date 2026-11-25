import { NextResponse, type NextRequest } from "next/server";
import {
  MAX_PROXY_BODY_BYTES,
  SESSION_COOKIE,
  apiBaseUrl,
  clientAddressHeaders,
  errorResponse,
  isSameOrigin,
  readBodyLimited,
} from "@/lib/server-config";
import { clearSessionCookie } from "@/lib/session-cookie";

export const dynamic = "force-dynamic";

const FORWARD_REQUEST_HEADERS = ["content-type", "accept", "idempotency-key", "x-correlation-id"];
const FORWARD_RESPONSE_HEADERS = ["content-type", "content-disposition", "x-correlation-id", "retry-after"];
const SAFE_METHODS = new Set(["GET", "HEAD"]);

async function handle(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }): Promise<Response> {
  const { path } = await ctx.params;
  if (path.some((seg) => seg === ".." || seg === "." || seg.includes("/"))) {
    return errorResponse(400, "invalid_path", "Invalid path.");
  }
  // Auth endpoints that mint tokens go through /api/session only.
  if (path[0] === "auth" && path[1] !== "logout") {
    return errorResponse(404, "not_found", "Use /api/session for login and registration.");
  }
  if (!SAFE_METHODS.has(req.method) && !isSameOrigin(req)) {
    return errorResponse(403, "forbidden_origin", "Cross-origin request rejected.");
  }

  const token = req.cookies.get(SESSION_COOKIE)?.value;
  if (!token) return errorResponse(401, "unauthenticated", "Please sign in.");

  const headers = new Headers();
  for (const name of FORWARD_REQUEST_HEADERS) {
    const v = req.headers.get(name);
    if (v) headers.set(name, v);
  }
  if (!headers.has("x-correlation-id")) headers.set("x-correlation-id", crypto.randomUUID());
  headers.set("Authorization", `Bearer ${token}`);
  for (const [name, value] of Object.entries(clientAddressHeaders(req))) headers.set(name, value);

  let requestBody: ArrayBuffer | undefined;
  if (!SAFE_METHODS.has(req.method)) {
    const read = await readBodyLimited(req, MAX_PROXY_BODY_BYTES);
    if (read === null) return errorResponse(413, "payload_too_large", "That request is too large.");
    requestBody = read;
  }

  const target = `${apiBaseUrl()}/${path.map(encodeURIComponent).join("/")}${req.nextUrl.search}`;
  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: req.method,
      headers,
      body: requestBody,
      cache: "no-store",
      redirect: "manual",
    });
  } catch {
    return errorResponse(502, "upstream_unavailable", "We couldn't reach RoleTailor. Please try again shortly.");
  }

  const resHeaders = new Headers();
  for (const name of FORWARD_RESPONSE_HEADERS) {
    const v = upstream.headers.get(name);
    if (v) resHeaders.set(name, v);
  }
  resHeaders.set("Cache-Control", "no-store");
  const body = upstream.status === 204 || upstream.status === 304 ? null : upstream.body;
  const res = new NextResponse(body, { status: upstream.status, headers: resHeaders });
  if (upstream.status === 401) clearSessionCookie(res);
  return res;
}

export { handle as GET, handle as POST, handle as PATCH, handle as PUT, handle as DELETE };
