import { NextResponse } from "next/server";
import { constantTimeEqual } from "../../../../lib/auth/password";
import { signUiSession } from "../../../../lib/auth/jwt";
import { AUTH_COOKIE_NAME } from "../../../../lib/auth/constants";

export async function POST(req: Request) {
  const secret = process.env.AUTH_SECRET?.trim();
  if (!secret) {
    return NextResponse.json({ detail: "AUTH_SECRET not configured" }, { status: 503 });
  }

  let body: { identifier?: string; password?: string };
  try {
    body = (await req.json()) as { identifier?: string; password?: string };
  } catch {
    return NextResponse.json({ detail: "invalid JSON" }, { status: 400 });
  }

  const identifier = String(body.identifier ?? "").trim();
  const password = String(body.password ?? "");
  if (!identifier || !password) {
    return NextResponse.json({ detail: "identifier and password required" }, { status: 400 });
  }

  const adminEmail = process.env.AUTH_ADMIN_EMAIL?.trim().toLowerCase() ?? "";
  const adminPass = process.env.AUTH_ADMIN_PASSWORD ?? "";
  const viewerUser = process.env.AUTH_VIEWER_USERNAME?.trim().toLowerCase() ?? "";
  const viewerPass = process.env.AUTH_VIEWER_PASSWORD ?? "";

  const idLower = identifier.toLowerCase();

  let role: "admin" | "viewer" | null = null;

  if (adminEmail && idLower === adminEmail && constantTimeEqual(password, adminPass)) {
    role = "admin";
  } else if (viewerUser && idLower === viewerUser && constantTimeEqual(password, viewerPass)) {
    role = "viewer";
  }

  if (!role) {
    return NextResponse.json({ detail: "invalid credentials" }, { status: 401 });
  }

  const sub =
    role === "admin" ? process.env.AUTH_ADMIN_EMAIL!.trim() : process.env.AUTH_VIEWER_USERNAME!.trim();

  const token = await signUiSession({ role, sub }, secret);
  const res = NextResponse.json({ ok: true });
  const secure = process.env.NODE_ENV === "production";
  res.cookies.set(AUTH_COOKIE_NAME, token, {
    httpOnly: true,
    sameSite: "lax",
    path: "/",
    secure,
    maxAge: 60 * 60 * 24 * 7,
  });
  return res;
}
