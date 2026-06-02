"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { bridgeUrl } from "../../lib/paths";
import { countyLine, useCountyNames } from "../../lib/useCountyNames";

type SortProfile = "combined" | "entitlement" | "strategic" | "identification";

type ParcelRow = {
  parcel_id: string;
  apn: string;
  county_fips: string;
  zoning_code: string | null;
  lot_sqft: number | null;
  entitlement_score: number | null;
  strategic_score: number | null;
  identification_score: number | null;
  combined_score: number | null;
  created_at: string;
};

type ScoredList = {
  sort: SortProfile;
  row_count: number;
  rows: ParcelRow[];
};

function fmtScore(v: number | null): string {
  return v != null ? v.toFixed(1) : "—";
}

export default function ParcelsPage() {
  const countyLabel = useCountyNames();
  const [limit, setLimit] = useState(100);
  const [sort, setSort] = useState<SortProfile>("combined");
  const [rows, setRows] = useState<ParcelRow[]>([]);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    setErr(null);
    try {
      const res = await fetch(
        bridgeUrl(`internal/parcels/scored-list?limit=${limit}&sort=${sort}`),
        { cache: "no-store" },
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = (await res.json()) as ScoredList;
      setRows(data.rows);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }, [limit, sort]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="page-content">
      <div className="panel" style={{ display: "flex", gap: "1rem", alignItems: "center", flexWrap: "wrap" }}>
        <label className="muted">
          Sort by{" "}
          <select value={sort} onChange={(e) => setSort(e.target.value as SortProfile)}>
            <option value="combined">Combined (avg of agents)</option>
            <option value="entitlement">Entitlement (Atlas)</option>
            <option value="strategic">Strategic (Beacon)</option>
            <option value="identification">Identification (Cartographer)</option>
          </select>
        </label>
        <label className="muted">
          Max rows{" "}
          <select value={limit} onChange={(e) => setLimit(Number(e.target.value))}>
            {[25, 50, 100, 200, 500].map((n) => (
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
              <th>Combined</th>
              <th>Entitlement</th>
              <th>Strategic</th>
              <th>Identification</th>
              <th>APN</th>
              <th>County</th>
              <th>Zoning</th>
              <th>Lot sqft</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.map((p) => (
              <tr key={p.parcel_id}>
                <td>
                  <strong>{fmtScore(p.combined_score)}</strong>
                </td>
                <td>{fmtScore(p.entitlement_score)}</td>
                <td>{fmtScore(p.strategic_score)}</td>
                <td>{fmtScore(p.identification_score)}</td>
                <td>{p.apn}</td>
                <td>{countyLine(countyLabel, p.county_fips)}</td>
                <td>{p.zoning_code ?? "—"}</td>
                <td>{p.lot_sqft != null ? Math.round(p.lot_sqft).toLocaleString() : "—"}</td>
                <td>
                  <Link href={`/parcels/${p.parcel_id}`}>Detail →</Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {rows.length === 0 && !err ? <p className="muted">No parcels returned.</p> : null}
      </div>
    </div>
  );
}
