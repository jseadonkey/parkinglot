import { type NextRequest, NextResponse } from "next/server";
import { jwtVerify } from "jose";
import { AUTH_COOKIE_NAME } from "./lib/auth/constants";

/** Full browser path (includes /operator prefix) for ?next= after signing in at the shared /login page. */
function operatorReturnUrlPath(internalPathname: string): string {
  const prefix = (process.env.NEXT_PUBLIC_BASE_PATH ?? "").replace(/\/$/, "") || "/operator";
  if (internalPathname === "/" || internalPathname === "") return prefix;
  return `${prefix}${internalPathname.startsWith("/") ? internalPathname : `/${internalPathname}`}`;
}

function redirectToGeneralLogin(req: NextRequest, internalPathname: string): NextResponse {
  const url = new URL("/login", req.nextUrl.origin);
  url.searchParams.set("next", operatorReturnUrlPath(internalPathname));
  return NextResponse.redirect(url);
}

export async function middleware(req: NextRequest) {
  const secret = process.env.AUTH_SECRET?.trim();
  if (!secret) return NextResponse.next();

  const { pathname } = req.nextUrl;
  if (
    pathname.startsWith("/login") ||
    pathname.startsWith("/api/auth") ||
    pathname.startsWith("/platform") ||
    pathname.startsWith("/api/platform-showcase") ||
    pathname.startsWith("/_next") ||
    pathname === "/favicon.ico"
  ) {
    return NextResponse.next();
  }

  const token = req.cookies.get(AUTH_COOKIE_NAME)?.value;
  if (!token) {
    return redirectToGeneralLogin(req, pathname);
  }

  try {
    await jwtVerify(token, new TextEncoder().encode(secret));
    return NextResponse.next();
  } catch {
    return redirectToGeneralLogin(req, pathname);
  }
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
