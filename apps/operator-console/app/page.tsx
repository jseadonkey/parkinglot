"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { bridgeUrl } from "../lib/paths";

type QualifiedMinScores = {
  entitlement: number;
  strategic: number;
  identification: number;
};

type ScoringSummary = {
  total_parcels: number;
  parcels_with_latest_entitlement_score: number;
  parcels_with_latest_strategic_score: number;
  parcels_with_latest_identification_score: number;
  parcels_with_both_profiles_scored: number;
  qualified_count_entitlement: number;
  qualified_count_strategic: number;
  qualified_count_identification: number;
  qualified_min_score: QualifiedMinScores;
  pilot_region: string;
};

type ExportReadiness = {
  parcel_row_total: number;
  parcels_missing_owner_outreach_brief: { count: number; pct: number };
};

type PilotCounty = {
  county_fips: string;
  county_name: string;
  parcels_in_db: number;
};

type PilotScope = {
  region_name: string;
  state_fips: string;
  state_name: string;
  primary_metro_cbsa: string | null;
  primary_metro_label: string | null;
  pilot_county_count: number;
  counties_with_ingested_parcels: number;
  parcels_in_pilot_counties: number;
  min_lot_sqft: number;
  qualified_min_score: QualifiedMinScores;
  counties: PilotCounty[];
};

type FunnelStep = {
  key: string;
  label: string;
  detail: string;
  count: number | null;
};

function isScoringSummary(s: unknown): s is ScoringSummary {
  return typeof s === "object" && s !== null && "total_parcels" in s;
}

function isPilotScope(s: unknown): s is PilotScope {
  return typeof s === "object" && s !== null && "counties" in s && Array.isArray((s as PilotScope).counties);
}

function isExportReadiness(s: unknown): s is ExportReadiness {
  return typeof s === "object" && s !== null && "parcel_row_total" in s;
}

function formatCount(n: number | null): string {
  if (n === null) return "—";
  return n.toLocaleString();
}

function funnelWidthPct(count: number, base: number): number {
  if (base <= 0) return 8;
  return Math.max(8, Math.round((count / base) * 100));
}

export default function OverviewPage() {
  const [readiness, setReadiness] = useState<unknown>(null);
  const [summary, setSummary] = useState<unknown>(null);
  const [scope, setScope] = useState<unknown>(null);
  const [showAllCounties, setShowAllCounties] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setErr(null);
      try {
        const [rScope, rSummary, rReady] = await Promise.all([
          fetch(bridgeUrl("internal/stats/pilot-scope"), { cache: "no-store" }),
          fetch(bridgeUrl("internal/stats/scoring-summary"), { cache: "no-store" }),
          fetch(bridgeUrl("internal/stats/export-readiness"), { cache: "no-store" }),
        ]);
        if (!rScope.ok) throw new Error(`pilot-scope ${rScope.status}`);
        if (!rSummary.ok) throw new Error(`scoring-summary ${rSummary.status}`);
        if (!rReady.ok) throw new Error(`export-readiness ${rReady.status}`);
        const [jScope, jSummary, jReady] = await Promise.all([rScope.json(), rSummary.json(), rReady.json()]);
        if (!cancelled) {
          setScope(jScope);
          setSummary(jSummary);
          setReadiness(jReady);
        }
      } catch (e) {
        if (!cancelled) setErr(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const funnelSteps = useMemo((): FunnelStep[] => {
    if (!isScoringSummary(summary)) return [];
    const ready = isExportReadiness(readiness) ? readiness : null;
    const withBrief = ready
      ? Math.max(0, ready.parcel_row_total - ready.parcels_missing_owner_outreach_brief.count)
      : null;
    const floors = summary.qualified_min_score;

    return [
      {
        key: "ingested",
        label: "Parcels ingested",
        detail:
          "Only APNs we have loaded from county GIS exports (or WaTech pulls) — not every parcel in Washington.",
        count: summary.total_parcels,
      },
      {
        key: "identification",
        label: "Identification prescreen",
        detail:
          "Lightweight Cartographer score at ingest from geometry + zoning + lot size + demand distance. No owner lookup yet.",
        count: summary.parcels_with_latest_identification_score,
      },
      {
        key: "pipeline",
        label: "Full pipeline scored",
        detail:
          "Atlas (entitlement) + Beacon (strategic) scores — runs only when `run_pipeline` is enqueued, not on every ingested APN.",
        count: summary.parcels_with_both_profiles_scored,
      },
      {
        key: "qualified",
        label: `Qualified (entitlement ≥ ${floors.entitlement})`,
        detail: "Parcels meeting the pilot floor for deal outreach and operator boards.",
        count: summary.qualified_count_entitlement,
      },
      {
        key: "brief",
        label: "Owner outreach brief",
        detail: "Deep enrichment: owners, registry stub, vendor lookup, contact points, memo + contract draft.",
        count: withBrief,
      },
    ];
  }, [summary, readiness]);

  const countiesToShow = useMemo(() => {
    if (!isPilotScope(scope)) return [];
    const sorted = [...scope.counties].sort((a, b) => b.parcels_in_db - a.parcels_in_db || a.county_name.localeCompare(b.county_name));
    if (showAllCounties) return sorted;
    const withData = sorted.filter((c) => c.parcels_in_db > 0);
    return withData.length > 0 ? withData : sorted.slice(0, 8);
  }, [scope, showAllCounties]);

  const funnelBase = funnelSteps[0]?.count ?? 0;

  return (
    <main>
      <h1>Operator overview</h1>
      <p className="muted page-lead">
        Pilot scope, scoring totals, and how parcels narrow from statewide ingest to qualified outreach candidates.
      </p>

      {err ? <div className="error">{err}</div> : null}

      <h2>Geographic scope</h2>
      {isPilotScope(scope) ? (
        <div className="panel scope-panel">
          <div className="scope-headline">
            <div>
              <div className="scope-region">{scope.region_name}</div>
              <p className="muted scope-sub">
                {scope.state_name} (FIPS {scope.state_fips}) · {scope.pilot_county_count} counties in pilot config
                {scope.primary_metro_label ? (
                  <>
                    {" "}
                    · Primary metro: <strong>{scope.primary_metro_label}</strong>
                  </>
                ) : null}
              </p>
            </div>
            <div className="scope-badges">
              <span className="badge">Min lot {scope.min_lot_sqft.toLocaleString()} sqft</span>
              <span className="badge">
                Qualified floor {scope.qualified_min_score.entitlement} (entitlement)
              </span>
            </div>
          </div>

          <p className="muted scope-note">
            Ingest skips parcels outside the county FIPS list in <code>config/pilot.yaml</code>. We have loaded parcels
            in <strong>{scope.counties_with_ingested_parcels}</strong> of {scope.pilot_county_count} pilot counties (
            {scope.parcels_in_pilot_counties.toLocaleString()} rows in DB).
          </p>

          <table className="data scope-county-table">
            <thead>
              <tr>
                <th>County</th>
                <th>FIPS</th>
                <th>Parcels in DB</th>
              </tr>
            </thead>
            <tbody>
              {countiesToShow.map((c) => (
                <tr key={c.county_fips}>
                  <td>{c.county_name}</td>
                  <td className="muted">{c.county_fips}</td>
                  <td>{c.parcels_in_db.toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>

          {isPilotScope(scope) && scope.counties.length > countiesToShow.length ? (
            <button type="button" className="outline scope-toggle" onClick={() => setShowAllCounties((v) => !v)}>
              {showAllCounties ? "Show counties with data only" : `Show all ${scope.pilot_county_count} pilot counties`}
            </button>
          ) : null}
        </div>
      ) : (
        !err && <p className="muted">Loading geographic scope…</p>
      )}

      <h2>Scoring totals</h2>
      <div className="cols" style={{ marginTop: "0.5rem" }}>
        {isScoringSummary(summary) ? (
          <>
            <div className="stat">
              <div className="muted">Parcels in DB</div>
              <div className="n">{formatCount(summary.total_parcels)}</div>
            </div>
            <div className="stat">
              <div className="muted">Identification prescreen</div>
              <div className="n">{formatCount(summary.parcels_with_latest_identification_score)}</div>
            </div>
            <div className="stat">
              <div className="muted">Full pipeline (both scores)</div>
              <div className="n">{formatCount(summary.parcels_with_both_profiles_scored)}</div>
            </div>
            <div className="stat">
              <div className="muted">Qualified (entitlement)</div>
              <div className="n">{formatCount(summary.qualified_count_entitlement)}</div>
            </div>
          </>
        ) : (
          !err && <p className="muted">Loading scoring summary…</p>
        )}
      </div>

      <h2>Outreach candidates</h2>
      <p className="muted">
        See <Link href="/outreach">Outreach pipeline</Link> for parcels at or above the entitlement score floor, with deal
        workflow status and brief/approval columns.
      </p>

      <h2>Data funnel</h2>
      <p className="muted">
        We do <strong>not</strong> pull owner enrichment, deal memos, or contracts on every APN in Washington. Parcels
        narrow through ingest boundaries, lightweight prescreening, and optional full pipeline runs.
      </p>

      {funnelSteps.length > 0 ? (
        <div className="panel funnel-viz">
          {funnelSteps.map((step, idx) => {
            const width = funnelWidthPct(step.count ?? 0, funnelBase);
            const prev = idx > 0 ? funnelSteps[idx - 1].count : null;
            const drop =
              prev !== null && step.count !== null && prev > 0
                ? Math.round((1 - step.count / prev) * 100)
                : null;
            return (
              <div className="funnel-stage" key={step.key}>
                <div className="funnel-bar-wrap">
                  <div className="funnel-bar" style={{ width: `${width}%` }}>
                    <span className="funnel-bar-label">{step.label}</span>
                    <span className="funnel-bar-n">{formatCount(step.count)}</span>
                  </div>
                </div>
                <p className="muted funnel-detail">{step.detail}</p>
                {drop !== null && drop > 0 ? (
                  <p className="muted funnel-drop">{drop}% fewer than prior stage</p>
                ) : null}
              </div>
            );
          })}

          <div className="funnel-legend panel-inset">
            <strong>What runs when</strong>
            <ul className="funnel-list muted">
              <li>
                <strong>Ingest</strong> — polygon + assessor attributes only; writes identification prescreen score.
              </li>
              <li>
                <strong>Full pipeline</strong> — enqueued selectively (manual, batch, or post-ingest cap) — scoring,
                owner enrichment, outreach brief, memo, contract draft.
              </li>
              <li>
                <strong>Operator views</strong> — outreach and deal boards focus on entitlement-qualified parcels, not
                the full statewide inventory.
              </li>
            </ul>
          </div>
        </div>
      ) : (
        !err && <p className="muted">Loading funnel…</p>
      )}

      <details className="panel export-readiness-details">
        <summary className="export-readiness-summary">Export readiness (technical JSON)</summary>
        {readiness ? <pre className="json">{JSON.stringify(readiness, null, 2)}</pre> : !err ? <p className="muted">Loading…</p> : null}
      </details>
    </main>
  );
}
