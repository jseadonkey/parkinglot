"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { STATE_NAMES } from "../../lib/marketScope";
import { bridgeUrl } from "../../lib/paths";
import { formatMonthlyGross, formatStallRange, type ParcelRevenueSummary } from "../../lib/revenueDisplay";
import { tierBadgeClass, tierLabel } from "../../lib/zoningEntitlement";
import { countyLine, useCountyNames } from "../../lib/useCountyNames";

type SortProfile = "combined" | "entitlement" | "strategic" | "identification";

type ParcelRow = {
  parcel_id: string;
  apn: string;
  county_fips: string;
  zoning_code: string | null;
  zoning_principal_use_symbol: string | null;
  zoning_entitlement_tier: string | null;
  lot_sqft: number | null;
  entitlement_score: number | null;
  strategic_score: number | null;
  identification_score: number | null;
  combined_score: number | null;
  created_at: string;
  revenue: ParcelRevenueSummary | null;
};

type ScoredList = {
  sort: SortProfile;
  row_count: number;
  qualified_min_entitlement_score?: number;
  revenue_rows_computed?: number;
  rows: ParcelRow[];
};

type PilotCounty = { county_fips: string; county_name: string; priority_market?: boolean };

function fmtScore(v: number | null): string {
  return v != null ? v.toFixed(1) : "—";
}

export default function ParcelsPage() {
  const countyLabel = useCountyNames();
  const [limit, setLimit] = useState(100);
  const [sort, setSort] = useState<SortProfile>("combined");
  const [stateFips, setStateFips] = useState("");
  const [countyFips, setCountyFips] = useState("");
  const [zoningTier, setZoningTier] = useState("");
  const [qualifiedOnly, setQualifiedOnly] = useState(true);
  const [counties, setCounties] = useState<PilotCounty[]>([]);
  const [rows, setRows] = useState<ParcelRow[]>([]);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(bridgeUrl("internal/stats/pilot-scope"), { cache: "no-store" });
        if (!res.ok) return;
        const data = (await res.json()) as { counties?: PilotCounty[] };
        if (!cancelled && data.counties) setCounties(data.counties);
      } catch {
        /* ignore */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const countyOptions = counties.filter((c) => !stateFips || c.county_fips.startsWith(stateFips));

  const load = useCallback(async () => {
    setErr(null);
    try {
      const params = new URLSearchParams({ limit: String(limit), sort });
      if (countyFips) params.set("county_fips", countyFips);
      else if (stateFips) params.set("state_fips", stateFips);
      if (zoningTier) params.set("zoning_tier", zoningTier);
      params.set("include_revenue", "true");
      if (qualifiedOnly) params.set("qualified_only", "true");
      const res = await fetch(bridgeUrl(`internal/parcels/scored-list?${params}`), { cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = (await res.json()) as ScoredList;
      setRows(data.rows);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }, [limit, sort, stateFips, countyFips, zoningTier, qualifiedOnly]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="page-content">
      <p className="muted" style={{ marginTop: 0 }}>
        Scored parcels across pilot markets (MD, WA, and more). High-scoring rows include illustrative revenue from
        nearby paid parking comps and estimated stall counts. Filter by state or county.
      </p>
      <div className="panel" style={{ display: "flex", gap: "1rem", alignItems: "center", flexWrap: "wrap" }}>
        <label className="muted">
          State{" "}
          <select
            value={stateFips}
            onChange={(e) => {
              setStateFips(e.target.value);
              setCountyFips("");
            }}
          >
            <option value="">All states</option>
            <option value="24">{STATE_NAMES["24"]} (MD)</option>
            <option value="53">{STATE_NAMES["53"]} (WA)</option>
          </select>
        </label>
        <label className="muted">
          County{" "}
          <select
            value={countyFips}
            onChange={(e) => setCountyFips(e.target.value)}
            disabled={countyOptions.length === 0}
          >
            <option value="">All counties{stateFips ? " in state" : ""}</option>
            {countyOptions
              .slice()
              .sort(
                (a, b) =>
                  (b.priority_market ? 1 : 0) - (a.priority_market ? 1 : 0) ||
                  a.county_name.localeCompare(b.county_name),
              )
              .map((c) => (
                <option key={c.county_fips} value={c.county_fips}>
                  {c.county_name}
                  {c.priority_market ? " ★" : ""} ({c.county_fips})
                </option>
              ))}
          </select>
        </label>
        <label className="muted">
          Zoning tier{" "}
          <select value={zoningTier} onChange={(e) => setZoningTier(e.target.value)}>
            <option value="">All tiers</option>
            <option value="permitted">Permitted (P)</option>
            <option value="conditional">Conditional (BMZA)</option>
            <option value="council">Council ordinance</option>
            <option value="excluded">Not allowed</option>
          </select>
        </label>
        <label className="muted" style={{ display: "flex", alignItems: "center", gap: "0.35rem" }}>
          <input
            type="checkbox"
            checked={qualifiedOnly}
            onChange={(e) => setQualifiedOnly(e.target.checked)}
          />
          High scores only (entitlement ≥ pilot floor)
        </label>
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
              <th>Zoning tier</th>
              <th>Est. stalls</th>
              <th>Est. gross/mo</th>
              <th>$/hr (weighted)</th>
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
                <td>
                  {p.zoning_entitlement_tier ? (
                    <span className={tierBadgeClass(p.zoning_entitlement_tier)}>{tierLabel(p.zoning_entitlement_tier)}</span>
                  ) : (
                    "—"
                  )}
                </td>
                <td>{formatStallRange(p.revenue)}</td>
                <td>
                  {p.revenue?.revenue_available ? (
                    <>
                      <strong>{formatMonthlyGross(p.revenue.monthly_gross_usd)}</strong>
                      {p.revenue.monthly_gross_low_usd != null && p.revenue.monthly_gross_high_usd != null ? (
                        <span className="muted" style={{ display: "block", fontSize: "0.85em" }}>
                          {formatMonthlyGross(p.revenue.monthly_gross_low_usd)}–
                          {formatMonthlyGross(p.revenue.monthly_gross_high_usd)}
                        </span>
                      ) : null}
                    </>
                  ) : (
                    "—"
                  )}
                </td>
                <td>
                  {p.revenue?.hourly_rate_weighted_usd != null
                    ? `$${p.revenue.hourly_rate_weighted_usd.toFixed(2)}`
                    : "—"}
                </td>
                <td>{p.lot_sqft != null ? Math.round(p.lot_sqft).toLocaleString() : "—"}</td>
                <td>
                  <Link href={`/parcels/${p.parcel_id}`}>Detail →</Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {rows.length === 0 ? <p className="muted">No parcels match this filter.</p> : null}
      </div>
    </div>
  );
}
