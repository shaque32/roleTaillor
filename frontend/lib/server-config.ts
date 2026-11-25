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

/**
 * Headers that tell the API which browser a proxied request came from, so its rate limits
 * are per visitor and not per web server. The address is read from the header the platform
 * edge sets itself (CLIENT_IP_HEADER, e.g. "fly-client-ip"); X-Forwarded-For is not used
 * because a client can send it. The API believes the address only with the shared secret.
 */
export function clientAddressHeaders(req: Request): Record<string, string> {
  const secret = process.env["API_PROXY_SECRET"];
  const header = process.env["CLIENT_IP_HEADER"];
  if (!secret || !header) return {};
  const address = req.headers.get(header)?.trim();
  return address ? { "X-RT-Client-IP": address, "X-RT-Proxy-Secret": secret } : {};
}

/** Largest body the proxy relays: the API's 10 MB upload cap plus multipart overhead. */
export const MAX_PROXY_BODY_BYTES = 10 * 1024 * 1024 + 64 * 1024;

/** Read a request body, or return null once it passes `limit` bytes (declared or actual). */
export async function readBodyLimited(req: Request, limit: number): Promise<ArrayBuffer | null> {
  const declared = Number(req.headers.get("content-length") ?? "0");
  if (Number.isFinite(declared) && declared > limit) return null;
  if (!req.body) return new ArrayBuffer(0);
  const reader = req.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    total += value.byteLength;
    if (total > limit) {
      await reader.cancel();
      return null;
    }
    chunks.push(value);
  }
  const out = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    out.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return out.buffer;
}
