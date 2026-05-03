import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { AUTH_COOKIE_NAME } from "../../../../lib/auth/constants";
import { verifyUiSession } from "../../../../lib/auth/jwt";

export async function GET() {
  const secret = process.env.AUTH_SECRET?.trim();
  if (!secret) {
    return NextResponse.json({ authEnabled: false, role: null });
  }

  const cookieStore = await cookies();
  const raw = cookieStore.get(AUTH_COOKIE_NAME)?.value;
  if (!raw) {
    return NextResponse.json({ authEnabled: true, role: null });
  }

  try {
    const session = await verifyUiSession(raw, secret);
    return NextResponse.json({ authEnabled: true, role: session.role, sub: session.sub });
  } catch {
    return NextResponse.json({ authEnabled: true, role: null });
  }
}
