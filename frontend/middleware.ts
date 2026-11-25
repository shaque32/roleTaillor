import { NextResponse, type NextRequest } from "next/server";

const SESSION_COOKIE = "rt_session";
const AUTH_PAGES = ["/login", "/register"];
/** Reachable with or without a session (links from emails). */
const OPEN_PAGES = ["/forgot-password", "/reset-password", "/verify-email"];

export function middleware(req: NextRequest) {
  const { pathname, search } = req.nextUrl;
  const hasSession = Boolean(req.cookies.get(SESSION_COOKIE)?.value);
  const isAuthPage = AUTH_PAGES.includes(pathname);

  if (OPEN_PAGES.includes(pathname)) return NextResponse.next();

  if (!hasSession && !isAuthPage) {
    const url = req.nextUrl.clone();
    url.pathname = "/login";
    url.search = pathname === "/" ? "" : `?next=${encodeURIComponent(pathname + search)}`;
    return NextResponse.redirect(url);
  }
  if (hasSession && (isAuthPage || pathname === "/")) {
    const url = req.nextUrl.clone();
    url.pathname = "/dashboard";
    url.search = "";
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!api/|_next/|favicon.ico|robots.txt).*)"],
};
