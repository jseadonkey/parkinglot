"use client";

import { useEffect, useState } from "react";
import { bridgeUrl } from "../../lib/paths";

export default function OwnersPage() {
  const [raw, setRaw] = useState<string>("");
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setErr(null);
      try {
        const res = await fetch(
          bridgeUrl("internal/owners/portfolios-ranked?min_peers=2&limit=40"),
          { cache: "no-store" },
        );
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const text = await res.text();
        if (!cancelled) setRaw(text);
      } catch (e) {
        if (!cancelled) setErr(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  let formatted = raw;
  try {
    if (raw) formatted = JSON.stringify(JSON.parse(raw), null, 2);
  } catch {
    /* keep raw */
  }

  return (
    <main>
      <h1>Owner portfolios</h1>
      <p className="muted">
        Ranked portfolios from <code>GET /internal/owners/portfolios-ranked</code> (requires operator-console{" "}
        <code>INTERNAL_API_KEY</code> server-side).
      </p>

      {err ? <div className="error">{err}</div> : null}

      <div className="panel">{raw ? <pre className="json">{formatted}</pre> : !err ? <p className="muted">Loading…</p> : null}</div>
    </main>
  );
}
