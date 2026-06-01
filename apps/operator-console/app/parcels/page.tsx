"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { bridgeUrl } from "../../lib/paths";

type ParcelRow = {
  id: string;
  apn: string;
  county_fips: string;
  zoning_code: string | null;
  lot_sqft: number | null;
  created_at: string;
};

export default function ParcelsPage() {
  const [limit, setLimit] = useState(50);
  const [rows, setRows] = useState<ParcelRow[]>([]);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    setErr(null);
    try {
      const res = await fetch(bridgeUrl(`parcels?limit=${limit}`), { cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = (await res.json()) as ParcelRow[];
      setRows(data);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }, [limit]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <main>
      <h1>Parcels</h1>
      <p className="muted">Latest parcel rows from the API (newest first).</p>

      <div className="panel" style={{ display: "flex", gap: "1rem", alignItems: "center", flexWrap: "wrap" }}>
        <label className="muted">
          Limit{" "}
          <select value={limit} onChange={(e) => setLimit(Number(e.target.value))}>
            {[25, 50, 100, 200].map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>
        <button type="button" className="primary" onClick={() => void load()}>
          Refresh
        </button>
      </div>

      {err ? <div className="error">{err}</div> : null}

      <div className="panel" style={{ overflowX: "auto" }}>
        <table className="data">
          <thead>
            <tr>
              <th>APN</th>
              <th>County FIPS</th>
              <th>Zoning</th>
              <th>Lot sqft</th>
              <th>Created</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.map((p) => (
              <tr key={p.id}>
                <td>{p.apn}</td>
                <td>{p.county_fips}</td>
                <td>{p.zoning_code ?? "—"}</td>
                <td>{p.lot_sqft != null ? Math.round(p.lot_sqft) : "—"}</td>
                <td className="muted">{p.created_at?.slice(0, 19) ?? ""}</td>
                <td>
                  <Link href={`/parcels/${p.id}`}>Detail →</Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {rows.length === 0 && !err ? <p className="muted">No parcels returned.</p> : null}
      </div>
    </main>
  );
}
