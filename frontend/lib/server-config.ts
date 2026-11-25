import "server-only";

/** Backend base URL. API_BASE_URL (runtime) wins over NEXT_PUBLIC_API_BASE_URL (build time). */
export function apiBaseUrl(): string {
  const raw = process.env["API_BASE_URL"] || process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000/v1";
  return raw.replace(/\/+$/, "");
}

export const SESSION_COOKIE = "rt_session";

export function cookieSecure(): boolean {
  const flag = process.env["COOKIE_SECURE"];
  if (flag === "true") return true;
  if (flag === "false") return false;
  return process.env.NODE_ENV === "production";
}

/** Same-origin check for mutating requests (CSRF defence in depth on top of SameSite=Lax). */
export function isSameOrigin(req: Request): boolean {
  const host = req.headers.get("x-forwarded-host") ?? req.headers.get("host");
  const origin = req.headers.get("origin");
  if (origin) {
    const extra = (process.env["ALLOWED_ORIGINS"] ?? "").split(",").map((o) => o.trim()).filter(Boolean);
    if (extra.includes(origin)) return true;
    try {
      return new URL(origin).host === host;
    } catch {
      return false;
    }
  }
  // Browsers always send Origin on cross-origin mutating requests; fall back to Fetch Metadata.
  const site = req.headers.get("sec-fetch-site");
  return site === "same-origin";
}

export function errorResponse(status: number, code: string, message: string): Response {
  return Response.json({ error: { code, message, details: {} } }, { status });
}
