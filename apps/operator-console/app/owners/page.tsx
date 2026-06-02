"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { bridgeUrl } from "../../lib/paths";

type PortfolioRow = {
  normalized_owner_key: string;
  qualified_parcel_count: number;
};

type Board = {
  qualified_min_entitlement_score: number;
  min_peers: number;
  portfolios: PortfolioRow[];
};

export default function OwnersPage() {
  const [board, setBoard] = useState<Board | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  async function load() {
    setLoading(true);
    setErr(null);
    try {
      const res = await fetch(
        bridgeUrl("internal/owners/portfolios-ranked?min_peers=2&limit=40"),
        { cache: "no-store" },
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setBoard((await res.json()) as Board);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  const rows = board?.portfolios ?? [];

  return (
    <main>
      <header className="page-header">
        <div>
          <h1>Owner portfolios</h1>
          <p className="muted page-lead">
            Owners (normalized from assessor roll) with <strong>two or more</strong> entitlement-qualified parcels.
            Useful for portfolio outreach — one conversation may cover multiple lots.
          </p>
        </div>
        <button type="button" className="outline" onClick={() => void load()} disabled={loading}>
          {loading ? "Loading…" : "Refresh"}
        </button>
      </header>

      {board ? (
        <p className="muted result-meta">
          Showing <strong>{rows.length}</strong> portfolios · qualified floor entitlement ≥{" "}
          {board.qualified_min_entitlement_score}
        </p>
      ) : null}

      {err ? <div className="error">{err}</div> : null}

      <div className="panel panel-flush">
        {loading && !board ? (
          <p className="muted empty-state">Loading portfolios…</p>
        ) : rows.length === 0 && !err ? (
          <p className="muted empty-state">
            No multi-parcel owners yet at the qualified floor. As more top deals complete enrichment, repeat owners
            will appear here.
          </p>
        ) : (
          <table className="data">
            <thead>
              <tr>
                <th>Owner key</th>
                <th>Qualified parcels</th>
                <th>Next step</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.normalized_owner_key}>
                  <td>
                    <code className="owner-key">{r.normalized_owner_key}</code>
                  </td>
                  <td>
                    <strong>{r.qualified_parcel_count}</strong>
                  </td>
                  <td className="muted">
                    Open each parcel from{" "}
                    <Link href="/outreach">Outreach</Link> or{" "}
                    <Link href="/parcels">Parcels</Link> — search by owner in the brief on parcel detail.
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="panel panel-inset" style={{ marginTop: "1rem" }}>
        <strong className="muted">How owner keys work</strong>
        <p className="muted" style={{ margin: "0.35rem 0 0" }}>
          Keys are normalized names from county assessor data (LLC/trust spelling variants collapsed). They are not
          verified legal entities — use skip-trace contacts on each parcel before outreach.
        </p>
      </div>
    </main>
  );
}
