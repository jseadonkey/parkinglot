"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { publicBasePath } from "../../lib/auth/publicBasePath";

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const nextPath = params.get("next") || "/";
  const bp = publicBasePath();

  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    setBusy(true);
    try {
      const res = await fetch(`${bp}/api/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ identifier, password }),
      });
      if (!res.ok) {
        const j = (await res.json().catch(() => ({}))) as { detail?: string };
        setErr(j.detail ?? `Login failed (${res.status})`);
        return;
      }
      router.replace(nextPath.startsWith("/") ? nextPath : "/");
      router.refresh();
    } finally {
      setBusy(false);
    }
  }

  return (
    <main style={{ maxWidth: 420 }}>
      <h1>Sign in</h1>
      <p className="muted">Use your admin email or view-only username.</p>
      <form className="panel" onSubmit={(e) => void onSubmit(e)} style={{ marginTop: "1rem" }}>
        <label className="muted" htmlFor="id">
          Email or username
        </label>
        <div style={{ marginTop: "0.35rem" }}>
          <input
            id="id"
            autoComplete="username"
            value={identifier}
            onChange={(e) => setIdentifier(e.target.value)}
            style={{ width: "100%", boxSizing: "border-box" }}
          />
        </div>
        <label className="muted" htmlFor="pw" style={{ display: "block", marginTop: "1rem" }}>
          Password
        </label>
        <div style={{ marginTop: "0.35rem" }}>
          <input
            id="pw"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            style={{ width: "100%", boxSizing: "border-box" }}
          />
        </div>
        {err ? <div className="error">{err}</div> : null}
        <div style={{ marginTop: "1.25rem" }}>
          <button type="submit" className="primary" disabled={busy}>
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </div>
      </form>
    </main>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={<main><p className="muted">Loading…</p></main>}>
      <LoginForm />
    </Suspense>
  );
}
