import { NextResponse } from "next/server";
import { AUTH_COOKIE_NAME } from "../../../../lib/auth/constants";

export async function POST() {
  const res = NextResponse.json({ ok: true });
  const secure = process.env.NODE_ENV === "production";
  res.cookies.set(AUTH_COOKIE_NAME, "", { httpOnly: true, sameSite: "lax", path: "/", secure, maxAge: 0 });
  return res;
}
