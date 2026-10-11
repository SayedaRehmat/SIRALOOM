import { NextRequest, NextResponse } from "next/server";

const WORKSPACE_FIRST_MODE = "lab";
const PUBLIC_ALWAYS_ALLOWED = new Set(["/login", "/signup", "/onboarding", "/privacy", "/terms"]);

export function middleware(request: NextRequest) {
  const mode = process.env.NEXT_PUBLIC_SIRALOOM_DEPLOYMENT_MODE ?? process.env.SIRALOOM_DEPLOYMENT_MODE ?? "platform";
  if (mode !== WORKSPACE_FIRST_MODE) return NextResponse.next();

  const pathname = request.nextUrl.pathname;
  if (
    pathname === "/app" ||
    pathname.startsWith("/app/") ||
    PUBLIC_ALWAYS_ALLOWED.has(pathname) ||
    pathname.startsWith("/onboarding/") ||
    pathname.startsWith("/_next/") ||
    pathname === "/favicon.ico" ||
    pathname === "/robots.txt"
  ) {
    return NextResponse.next();
  }

  const login = request.nextUrl.clone();
  login.pathname = "/login";
  login.search = "";
  return NextResponse.redirect(login);
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
