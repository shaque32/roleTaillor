import "server-only";
import type { NextResponse } from "next/server";
import { SESSION_COOKIE, cookieSecure } from "./server-config";

const DEFAULT_MAX_AGE = 60 * 60 * 24 * 14; // 14 days; backend expiry is authoritative.

export function setSessionCookie(res: NextResponse, token: string, expiresAt?: string): void {
  let maxAge = DEFAULT_MAX_AGE;
  if (expiresAt) {
    const secs = Math.floor((Date.parse(expiresAt) - Date.now()) / 1000);
    if (Number.isFinite(secs) && secs > 0) maxAge = secs;
  }
  res.cookies.set({
    name: SESSION_COOKIE,
    value: token,
    httpOnly: true,
    secure: cookieSecure(),
    sameSite: "lax",
    path: "/",
    maxAge,
  });
}

export function clearSessionCookie(res: NextResponse): void {
  res.cookies.set({
    name: SESSION_COOKIE,
    value: "",
    httpOnly: true,
    secure: cookieSecure(),
    sameSite: "lax",
    path: "/",
    maxAge: 0,
  });
}
