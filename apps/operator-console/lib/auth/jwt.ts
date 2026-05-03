import { SignJWT, jwtVerify } from "jose";

export type UiRole = "admin" | "viewer";

export async function signUiSession(
  payload: { role: UiRole; sub: string },
  secret: string,
): Promise<string> {
  return new SignJWT({ role: payload.role, sub: payload.sub })
    .setProtectedHeader({ alg: "HS256" })
    .setIssuedAt()
    .setExpirationTime("7d")
    .sign(new TextEncoder().encode(secret));
}

export async function verifyUiSession(
  token: string,
  secret: string,
): Promise<{ role: UiRole; sub: string }> {
  const { payload } = await jwtVerify(token, new TextEncoder().encode(secret));
  const role = payload.role === "admin" || payload.role === "viewer" ? payload.role : null;
  const sub = typeof payload.sub === "string" ? payload.sub : "";
  if (!role || !sub) throw new Error("invalid session");
  return { role, sub };
}
