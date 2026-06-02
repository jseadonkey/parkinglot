"use client";

import Link from "next/link";
import { Fragment, useEffect, useState } from "react";
import { bridgeUrl } from "../../lib/paths";
import { countyLine, useCountyNames } from "../../lib/useCountyNames";

type PortfolioRow = {
  normalized_owner_key: string;
  qualified_parcel_count: number;
};

type PeerParcel = {
  parcel_id: string;
  apn: string;
  county_fips: string;
  latest_entitlement_score: number;
};

type Board = {
  qualified_min_entitlement_score: number;
  min_peers: number;
  portfolios: PortfolioRow[];
};

export default function OwnersPage() {
  const countyLabel = useCountyNames();
  const [board, setBoard] = useState<Board | null>(null);
  const [expandedKey, setExpandedKey] = useState<string | null>(null);
  const [peers, setPeers] = useState<PeerParcel[]>([]);
  const [peersLoading, setPeersLoading] = useState(false);
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

  async function loadPeers(ownerKey: string) {
    if (expandedKey === ownerKey) {
      setExpandedKey(null);
      setPeers([]);
      return;
    }
    setExpandedKey(ownerKey);
    setPeersLoading(true);
    setPeers([]);
    try {
      const q = encodeURIComponent(ownerKey);
      const res = await fetch(bridgeUrl(`internal/owners/peers-by-key?normalized_owner_key=${q}&limit=50`), {
        cache: "no-store",
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = (await res.json()) as { parcels: PeerParcel[] };
      setPeers(data.parcels ?? []);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setPeersLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  const rows = board?.portfolios ?? [];

  return (
    <div className="page-content">
      <div className="page-actions">
        <button type="button" className="outline" onClick={() => void load()} disabled={loading}>
          {loading ? "Loading…" : "Refresh"}
        </button>
      </div>

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
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <Fragment key={r.normalized_owner_key}>
                  <tr>
                    <td>
                      <code className="owner-key">{r.normalized_owner_key}</code>
                    </td>
                    <td>
                      <strong>{r.qualified_parcel_count}</strong>
                    </td>
                    <td>
                      <button type="button" className="outline" onClick={() => void loadPeers(r.normalized_owner_key)}>
                        {expandedKey === r.normalized_owner_key ? "Hide parcels" : "Show parcels"}
                      </button>
                    </td>
                  </tr>
                  {expandedKey === r.normalized_owner_key ? (
                    <tr>
                      <td colSpan={3} className="portfolio-expand">
                        {peersLoading ? (
                          <p className="muted">Loading parcels…</p>
                        ) : peers.length === 0 ? (
                          <p className="muted">No qualified peer parcels returned.</p>
                        ) : (
                          <table className="data portfolio-peer-table">
                            <thead>
                              <tr>
                                <th>APN</th>
                                <th>County</th>
                                <th>Score</th>
                                <th />
                              </tr>
                            </thead>
                            <tbody>
                              {peers.map((p) => (
                                <tr key={p.parcel_id}>
                                  <td>{p.apn}</td>
                                  <td className="muted">{countyLine(countyLabel, p.county_fips)}</td>
                                  <td>{p.latest_entitlement_score.toFixed(0)}</td>
                                  <td>
                                    <Link href={`/parcels/${p.parcel_id}`} className="btn-link">
                                      Open →
                                    </Link>
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        )}
                      </td>
                    </tr>
                  ) : null}
                </Fragment>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="panel panel-inset" style={{ marginTop: "1rem" }}>
        <strong className="muted">How owner keys work</strong>
        <p className="muted" style={{ margin: "0.35rem 0 0" }}>
          Keys are normalized names from county assessor data. Verify contacts via skip trace on each parcel before
          outreach.
        </p>
      </div>
    </div>
  );
}
