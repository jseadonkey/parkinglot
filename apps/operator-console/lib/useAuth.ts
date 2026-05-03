"use client";

import { useCallback, useEffect, useState } from "react";
import { publicBasePath } from "./auth/publicBasePath";

export type AuthState =
  | { loading: true }
  | { loading: false; authEnabled: false }
  | { loading: false; authEnabled: true; role: "admin" | "viewer" | null };

/** True when approve/reject and other mutations should be shown (admin only when auth is on). */
export function canMutate(state: AuthState): boolean {
  if (state.loading) return false;
  if (!state.authEnabled) return true;
  return state.role === "admin";
}

export function useAuth(): AuthState {
  const [state, setState] = useState<AuthState>({ loading: true });

  const refresh = useCallback(async () => {
    const bp = publicBasePath();
    const res = await fetch(`${bp}/api/auth/session`, { credentials: "same-origin", cache: "no-store" });
    const data = (await res.json()) as { authEnabled?: boolean; role?: string | null };
    if (!data.authEnabled) {
      setState({ loading: false, authEnabled: false });
      return;
    }
    const role = data.role === "admin" || data.role === "viewer" ? data.role : null;
    setState({ loading: false, authEnabled: true, role });
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return state;
}
