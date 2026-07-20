"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { ParcelSitePhoto } from "../../components/ParcelSitePhoto";
import { SitusAddressDisplay } from "../../components/SitusAddressDisplay";
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
  situs_address: string | null;
  situs_address_approximate?: boolean | null;
  mailing_address: string | null;
  zoning_code: string | null;
  zoning_principal_use_symbol: string | null;
  zoning_entitlement_tier: string | null;
  lot_sqft: number | null;
  entitlement_score: number | null;
  strategic_score: number | null;
  identification_score: number | null;
  combined_score: number | null;
  created_at: string;
  suitability: string | null;
  is_vacant_land: boolean | null;
  improvement_ratio: number | null;
  surface_kind?: string | null;
  surface_paved_fraction?: number | null;
  surface_source?: string | null;
  revenue: ParcelRevenueSummary | null;
};

const SUITABILITY_LABEL: Record<string, string> = {
  vacant: "Vacant lot",
  underutilized: "Underutilized",
  improved: "Improved",
  existing_parking: "Already parking",
  unknown: "Unknown",
};

const SURFACE_LABEL: Record<string, string> = {
  paved: "Paved",
  vegetated: "Grass / dirt",
  mixed: "Mixed surface",
  unknown: "Surface ?",
};

function suitabilityBadgeClass(s: string | null): string {
  if (s === "vacant") return "badge badge-ok";
  if (s === "underutilized") return "badge badge-warn";
  if (s === "existing_parking") return "badge badge-err";
  return "badge";
}

function surfaceBadgeClass(s: string | null | undefined): string {
  if (s === "paved") return "badge badge-ok";
  if (s === "vegetated") return "badge badge-warn";
  return "badge";
}

type ScoredList = {
  sort: SortProfile;
  row_count: number;
  qualified_min_entitlement_score?: number;
  revenue_rows_computed?: number;
  rows: ParcelRow[];
};

type PilotCounty = { county_fips: string; county_name: string; priority_market?: boolean; parcels_in_db?: number };

function fmtScore(v: number | null): string {
  return v != null ? v.toFixed(1) : "—";
}

export default function ParcelsPage() {
  const countyLabel = useCountyNames();
  const [limit, setLimit] = useState(25);
  const [sort, setSort] = useState<SortProfile>("combined");
  const [stateFips, setStateFips] = useState("");
  const [countyFips, setCountyFips] = useState("");
  const [zoningTier, setZoningTier] = useState("");
  const [suitability, setSuitability] = useState("vacant");
  const [preferPaved, setPreferPaved] = useState(true);
  const [surfaceOnly, setSurfaceOnly] = useState("");
  const [qualifiedOnly, setQualifiedOnly] = useState(false);
  const [counties, setCounties] = useState<PilotCounty[]>([]);
  const [rows, setRows] = useState<ParcelRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [rowCount, setRowCount] = useState<number | null>(null);
  const [qualifiedFloor, setQualifiedFloor] = useState<number | null>(null);
  const [err, setErr] = useState<string | null>(null);

  // Require an explicit state/county — all-states scans millions of rows and times out under load.
  const hasGeography = Boolean(stateFips || countyFips);

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
    if (!stateFips && !countyFips) {
      setRows([]);
      setRowCount(null);
      setQualifiedFloor(null);
      setErr(null);
      setLoading(false);
      return;
    }
    setErr(null);
    setLoading(true);
    try {
      const params = new URLSearchParams({ limit: String(limit), sort });
      if (countyFips) params.set("county_fips", countyFips);
      else if (stateFips) params.set("state_fips", stateFips);
      if (zoningTier) params.set("zoning_tier", zoningTier);
      if (suitability) params.set("suitability", suitability);
      if (preferPaved) params.set("prefer_paved", "true");
      if (surfaceOnly) params.set("surface", surfaceOnly);
      params.set("include_revenue", "false");
      if (qualifiedOnly) params.set("qualified_only", "true");
      const res = await fetch(bridgeUrl(`internal/parcels/scored-list?${params}`), { cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = (await res.json()) as ScoredList;
      setRows(data.rows);
      setRowCount(data.row_count);
      setQualifiedFloor(data.qualified_min_entitlement_score ?? null);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
      setRows([]);
      setRowCount(null);
    } finally {
      setLoading(false);
    }
  }, [limit, sort, stateFips, countyFips, zoningTier, suitability, preferPaved, surfaceOnly, qualifiedOnly]);

  useEffect(() => {
    void load();
  }, [load]);

  const mdParcelCount = counties.filter((c) => c.county_fips.startsWith("24")).reduce((n, c) => n + (c.parcels_in_db ?? 0), 0);

  const emptyHint = (() => {
    if (loading || rows.length > 0) return null;
    if (!hasGeography) {
      return "Select a state (or county) to load parcels.";
    }
    if (qualifiedOnly && qualifiedFloor != null) {
      return `No parcels score at or above entitlement ${qualifiedFloor} with these filters. Uncheck “High scores only” to see all ingested parcels (including unscored or lower scores).`;
    }
    if (stateFips === "24" || countyFips === "24510") {
      if (mdParcelCount > 0) {
        return `Maryland has ${mdParcelCount.toLocaleString()} parcels in the database but none match these filters. Try “All tiers” and turn off “High scores only”.`;
      }
      return "No Baltimore parcels in the database yet. Run Droplet resources → baltimore_ingest_now or baltimore_zoning_overlay, then refresh.";
    }
    if (stateFips || countyFips || zoningTier || suitability) {
      return "No parcels match these filters. Try “Prospect shortlist”, clear the zoning tier, or pick another county.";
    }
    return "No scored parcels in the database yet. Run county ingest on the Droplet (Baltimore or Washington), then refresh.";
  })();

  const applyProspectShortlist = () => {
    // Default to Washington when no geography is chosen so the shortlist can load.
    if (!stateFips && !countyFips) setStateFips("53");
    setZoningTier("prospect");
    setSuitability("vacant");
    setPreferPaved(true);
    setSurfaceOnly("paved");
    setSort("identification");
    setQualifiedOnly(false);
    setLimit(100);
  };

  return (
    <div className="page-content">
      <p className="muted" style={{ marginTop: 0 }}>
        Ranked prospects for every county: zoning (curated or WAZA provisional), vacant/underutilized sites, and
        demand proximity. Choose a <strong>state</strong> to load parcels (nothing loads until then). Humans review
        before any owner outreach. Use <strong>Prospect shortlist</strong> after picking a state or county.
      </p>
      <div className="panel" style={{ display: "flex", gap: "1rem", alignItems: "center", flexWrap: "wrap" }}>
        <button type="button" className="primary" onClick={applyProspectShortlist}>
          Prospect shortlist
        </button>
        <label className="muted">
          State{" "}
          <select
            value={stateFips}
            onChange={(e) => {
              setStateFips(e.target.value);
              setCountyFips("");
            }}
          >
            <option value="">Select a state</option>
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
          Zoning signal{" "}
          <select value={zoningTier} onChange={(e) => setZoningTier(e.target.value)}>
            <option value="">All tiers</option>
            <option value="prospect">Prospect (P / conditional / WAZA)</option>
            <option value="permitted">Permitted (P)</option>
            <option value="conditional">Conditional</option>
            <option value="provisional">Provisional (WAZA COM/MXU/IND)</option>
            <option value="council">Council ordinance</option>
            <option value="excluded">Not allowed</option>
          </select>
        </label>
        <label className="muted">
          Site suitability{" "}
          <select value={suitability} onChange={(e) => setSuitability(e.target.value)}>
            <option value="vacant">Vacant land</option>
            <option value="vacant_or_underutilized">Vacant or underutilized</option>
            <option value="underutilized">Underutilized</option>
            <option value="not_existing_parking">Hide already-parking</option>
            <option value="existing_parking">Already parking only</option>
            <option value="">Any site</option>
          </select>
        </label>
        <label className="muted" style={{ display: "flex", alignItems: "center", gap: "0.35rem" }}>
          <input
            type="checkbox"
            checked={preferPaved}
            onChange={(e) => setPreferPaved(e.target.checked)}
          />
          Prefer paved (asphalt / commercial vacant first)
        </label>
        <label className="muted">
          Surface{" "}
          <select value={surfaceOnly} onChange={(e) => setSurfaceOnly(e.target.value)}>
            <option value="">Any surface</option>
            <option value="paved">Paved only</option>
            <option value="vegetated">Grass / dirt only</option>
            <option value="mixed">Mixed only</option>
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
        <button
          type="button"
          className="primary"
          onClick={() => void load()}
          disabled={loading || !hasGeography}
        >
          {loading ? "Loading…" : "Refresh"}
        </button>
      </div>

      {rowCount != null ? (
        <p className="muted result-meta">
          Loaded <strong>{rows.length}</strong> parcel{rows.length === 1 ? "" : "s"}
          {qualifiedOnly && qualifiedFloor != null ? ` (entitlement ≥ ${qualifiedFloor})` : ""}
          {zoningTier === "prospect" || zoningTier === "provisional"
            ? " · prospect filters use curated rules + WAZA commercial/mixed/industrial class"
            : ""}
        </p>
      ) : null}

      {err ? <div className="error">{err}</div> : null}

      <div className="panel" style={{ overflowX: "auto" }}>
        {loading && rows.length === 0 ? <p className="muted">Loading parcels…</p> : null}
        <table className="data">
          <thead>
            <tr>
              <th>Photo</th>
              <th>Combined</th>
              <th>Entitlement</th>
              <th>Strategic</th>
              <th>Identification</th>
              <th>APN</th>
              <th>Property address</th>
              <th>County</th>
              <th>Zoning</th>
              <th>Site</th>
              <th>Surface</th>
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
                  <ParcelSitePhoto parcelId={p.parcel_id} variant="thumb" />
                </td>
                <td>
                  <strong>{fmtScore(p.combined_score)}</strong>
                </td>
                <td>{fmtScore(p.entitlement_score)}</td>
                <td>{fmtScore(p.strategic_score)}</td>
                <td>{fmtScore(p.identification_score)}</td>
                <td>{p.apn}</td>
              <td>
                {p.situs_address ? (
                  <>
                    <SitusAddressDisplay
                      address={p.situs_address}
                      approximate={p.situs_address_approximate}
                    />
                    {p.mailing_address ? (
                      <div className="muted" style={{ marginTop: "0.2rem", fontSize: "0.8rem" }}>
                        Mailing: {p.mailing_address}
                      </div>
                    ) : null}
                  </>
                ) : (
                  <span className="muted">No property address on file</span>
                )}
              </td>
                <td>{countyLine(countyLabel, p.county_fips)}</td>
                <td>{p.zoning_code ?? "—"}</td>
                <td>
                  {p.suitability ? (
                    <span className={suitabilityBadgeClass(p.suitability)}>
                      {SUITABILITY_LABEL[p.suitability] ?? p.suitability}
                    </span>
                  ) : (
                    "—"
                  )}
                </td>
                <td>
                  {p.surface_kind ? (
                    <span className={surfaceBadgeClass(p.surface_kind)} title={p.surface_source ?? undefined}>
                      {SURFACE_LABEL[p.surface_kind] ?? p.surface_kind}
                    </span>
                  ) : (
                    "—"
                  )}
                </td>
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
        {!loading && rows.length === 0 ? (
          <p className="muted empty-state">{emptyHint ?? "No parcels match this filter."}</p>
        ) : null}
      </div>
    </div>
  );
}
