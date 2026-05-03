import { NextResponse } from "next/server";
import { constantTimeEqual } from "../../../../lib/auth/password";
import { signUiSession } from "../../../../lib/auth/jwt";
import { AUTH_COOKIE_NAME } from "../../../../lib/auth/constants";
import { readAuthEnvForLogin } from "../../../../lib/auth/runtime-env";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(req: Request) {
  const e = readAuthEnvForLogin();
  if (!e.authSecret) {
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

  const idLower = identifier.toLowerCase();

  let role: "admin" | "viewer" | null = null;

  if (e.adminEmail && idLower === e.adminEmail && constantTimeEqual(password, e.adminPass)) {
    role = "admin";
  } else if (e.viewerUser && idLower === e.viewerUser && constantTimeEqual(password, e.viewerPass)) {
    role = "viewer";
  }

  if (!role) {
    return NextResponse.json({ detail: "invalid credentials" }, { status: 401 });
  }

  const sub = role === "admin" ? e.adminEmailDisplay : e.viewerUserDisplay;

  const token = await signUiSession({ role, sub }, e.authSecret);
  const res = NextResponse.json({ ok: true });
  const secure = e.nodeEnv === "production";
  res.cookies.set(AUTH_COOKIE_NAME, token, {
    httpOnly: true,
    sameSite: "lax",
    path: "/",
    secure,
    maxAge: 60 * 60 * 24 * 7,
  });
  return res;
}
