"use client";

import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "../lib/useAuth";
import { publicBasePath } from "../lib/auth/publicBasePath";

export function AuthToolbar() {
  const router = useRouter();
  const pathname = usePathname();
  const auth = useAuth();
  const bp = publicBasePath();

  if (pathname === "/login") return null;

  async function logout() {
    await fetch(`${bp}/api/auth/logout`, { method: "POST", credentials: "same-origin" });
    router.replace(`${bp}/login`);
    router.refresh();
  }

  if (auth.loading || !auth.authEnabled) return null;

  const label =
    auth.role === "admin" ? "Admin" : auth.role === "viewer" ? "View only" : "Signed out";

  return (
    <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", fontSize: "0.9rem" }}>
      <span className="muted">{label}</span>
      {auth.role ? (
        <button type="button" className="outline" onClick={() => void logout()}>
          Sign out
        </button>
      ) : null}
    </div>
  );
}
