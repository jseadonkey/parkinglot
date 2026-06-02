"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { OperatorGuide, QuickStartCards } from "../components/OperatorGuide";
import { bridgeUrl } from "../lib/paths";
import { formatStatesLabel } from "../lib/marketScope";
import { PILOT_SCOPE_DEFAULTS } from "../lib/pilotScopeDefaults";

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
  priority_market?: boolean;
};

type StateScope = {
  state_fips: string;
  state_name: string;
  county_count: number;
};

type PilotScope = {
  region_name: string;
  state_fips: string;
  state_name: string;
  states_in_scope?: StateScope[];
  primary_market_name?: string;
  primary_market_state_fips?: string;
  priority_county_fips?: string[];
  parcels_in_priority_counties?: number;
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

async function fetchJson(path: string): Promise<unknown> {
  const res = await fetch(bridgeUrl(path), { cache: "no-store" });
  if (!res.ok) throw new Error(`${path} ${res.status}`);
  return res.json();
}

export default function OverviewPage() {
  const [readiness, setReadiness] = useState<unknown>(null);
  const [summary, setSummary] = useState<unknown>(null);
  const [scope, setScope] = useState<unknown>(null);
  const [scopeLoading, setScopeLoading] = useState(true);
  const [summaryLoading, setSummaryLoading] = useState(true);
  const [readinessLoading, setReadinessLoading] = useState(false);
  const [scopeErr, setScopeErr] = useState<string | null>(null);
  const [summaryErr, setSummaryErr] = useState<string | null>(null);
  const [readinessErr, setReadinessErr] = useState<string | null>(null);
  const [showAllCounties, setShowAllCounties] = useState(false);
  const [exportDetailsOpen, setExportDetailsOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setScopeLoading(true);
    setScopeErr(null);
    fetchJson("internal/stats/pilot-scope")
      .then((data) => {
        if (!cancelled) setScope(data);
      })
      .catch((e) => {
        if (!cancelled) setScopeErr(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) setScopeLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    setSummaryLoading(true);
    setSummaryErr(null);
    fetchJson("internal/stats/scoring-summary")
      .then((data) => {
        if (!cancelled) setSummary(data);
      })
      .catch((e) => {
        if (!cancelled) setSummaryErr(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) setSummaryLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!exportDetailsOpen || readiness !== null || readinessLoading) return;
    let cancelled = false;
    setReadinessLoading(true);
    setReadinessErr(null);
    fetchJson("internal/stats/export-readiness")
      .then((data) => {
        if (!cancelled) setReadiness(data);
      })
      .catch((e) => {
        if (!cancelled) setReadinessErr(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) setReadinessLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [exportDetailsOpen, readiness, readinessLoading]);

  const scopeView = isPilotScope(scope) ? scope : null;
  const regionName = scopeView?.region_name ?? PILOT_SCOPE_DEFAULTS.region_name;
  const statesLabel =
    scopeView?.states_in_scope && scopeView.states_in_scope.length > 0
      ? formatStatesLabel(scopeView.states_in_scope)
      : (scopeView?.state_name ?? PILOT_SCOPE_DEFAULTS.state_name);
  const primaryMarket = scopeView?.primary_market_name ?? PILOT_SCOPE_DEFAULTS.primary_market_name;
  const priorityFips = new Set(
    scopeView?.priority_county_fips ?? [...PILOT_SCOPE_DEFAULTS.priority_county_fips],
  );
  const countyCount = scopeView?.pilot_county_count ?? PILOT_SCOPE_DEFAULTS.pilot_county_count;
  const metroLabel = scopeView?.primary_metro_label ?? PILOT_SCOPE_DEFAULTS.primary_metro_label;
  const minLot = scopeView?.min_lot_sqft ?? PILOT_SCOPE_DEFAULTS.min_lot_sqft;
  const qualFloor =
    scopeView?.qualified_min_score.entitlement ?? PILOT_SCOPE_DEFAULTS.qualified_min_entitlement;

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
          "Only APNs loaded from county GIS (Baltimore EGIS, Washington assessor/WaTech) — not every parcel in configured markets.",
        count: summary.total_parcels,
      },
      {
        key: "identification",
        label: `Identification prescreen (≥ ${floors.identification})`,
        detail:
          "Cartographer score at ingest — only parcels at or above this floor should enter the full pipeline (owner lookup, memo, contract).",
        count: summary.qualified_count_identification,
      },
      {
        key: "pipeline",
        label: "Full pipeline scored",
        detail:
          "Atlas (entitlement) first — if below floor, Beacon and enrichment are skipped. If Atlas passes, Beacon runs; enrichment only when both pass.",
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
        detail: ready
          ? "Deep enrichment: owners, registry stub, vendor lookup, contact points, memo + contract draft."
          : "Deep enrichment counts load when you expand Export readiness below.",
        count: withBrief,
      },
    ];
  }, [summary, readiness]);

  const countiesToShow = useMemo(() => {
    if (!scopeView) return [];
    const sorted = [...scopeView.counties].sort(
      (a, b) =>
        (b.priority_market ? 1 : 0) - (a.priority_market ? 1 : 0) ||
        b.parcels_in_db - a.parcels_in_db ||
        a.county_name.localeCompare(b.county_name),
    );
    if (showAllCounties) return sorted;
    const withData = sorted.filter((c) => c.parcels_in_db > 0);
    return withData.length > 0 ? withData : sorted.slice(0, 8);
  }, [scopeView, showAllCounties]);

  const countiesWithData = useMemo(() => {
    if (!scopeView) return [];
    return scopeView.counties
      .filter((c) => c.parcels_in_db > 0)
      .sort((a, b) => b.parcels_in_db - a.parcels_in_db);
  }, [scopeView]);

  const funnelBase = funnelSteps[0]?.count ?? 0;

  return (
    <div className="page-content">
      <QuickStartCards />

      <details className="panel partner-banner">
        <summary>
          <strong>Sharing with partners?</strong>
        </summary>
        <p className="muted" style={{ margin: "0.5rem 0" }}>
          Send them <Link href="/platform">Platform showcase</Link> — live metrics and redacted samples, no login
          required.
        </p>
        <Link href="/platform" className="btn-link btn-link-primary">
          Open platform showcase →
        </Link>
      </details>

      <OperatorGuide />

      <h2>Geographic scope</h2>
      <div className="panel scope-panel">
        <div className="scope-headline">
          <div>
            <div className="scope-region">{regionName}</div>
            <p className="muted scope-sub">
              <strong>{statesLabel}</strong> · <strong>{countyCount} counties</strong> in config (not all loaded) ·
              Priority market: <strong>{primaryMarket}</strong>
              {metroLabel ? (
                <>
                  {" "}
                  · Metro: <strong>{metroLabel}</strong>
                </>
              ) : null}
            </p>
          </div>
          <div className="scope-badges">
            <span className="badge badge-priority">Priority: Baltimore City + County</span>
            <span className="badge">Min lot {minLot.toLocaleString()} sqft</span>
            <span className="badge">Qualified floor {qualFloor} (entitlement)</span>
          </div>
        </div>

        <p className="muted scope-note">
          <strong>Config scope</strong> — ingest loads county GIS for Baltimore (EGIS) and Washington (WaTech/assessor);
          any of the {countyCount} FIPS in <code>config/pilot.yaml</code> + <code>config/geo_markets.yaml</code>. Parcels
          outside that list are skipped. Washington statewide ingest is paced; Baltimore is prioritized in the pipeline.
          {scopeView ? (
            <>
              {" "}
              <strong>Data loaded</strong> —{" "}
              <strong>{scopeView.parcels_in_pilot_counties.toLocaleString()}</strong> parcel rows in{" "}
              <strong>{scopeView.counties_with_ingested_parcels}</strong> of {scopeView.pilot_county_count} counties
              {scopeView.parcels_in_priority_counties != null && scopeView.parcels_in_priority_counties > 0 ? (
                <>
                  {" "}
                  (<strong>{scopeView.parcels_in_priority_counties.toLocaleString()}</strong> in priority Maryland
                  counties)
                </>
              ) : null}
              {countiesWithData.length > 0 ? (
                <>
                  :{" "}
                  {countiesWithData
                    .map((c) => `${c.county_name} (${c.county_fips}): ${c.parcels_in_db.toLocaleString()}`)
                    .join("; ")}
                </>
              ) : (
                " (none yet)"
              )}
              . The other {scopeView.pilot_county_count - scopeView.counties_with_ingested_parcels} counties are
              configured but have no GIS ingest yet.
            </>
          ) : scopeLoading ? (
            <> Parcel counts by county are loading…</>
          ) : null}
        </p>

        {scopeErr ? <div className="error">{scopeErr}</div> : null}

        {scopeView ? (
          <>
            <table className="data scope-county-table">
              <thead>
                <tr>
                  <th>County</th>
                  <th>FIPS</th>
                  <th>Market</th>
                  <th>Parcels in DB</th>
                </tr>
              </thead>
              <tbody>
                {countiesToShow.map((c) => (
                  <tr
                    key={c.county_fips}
                    className={c.priority_market || priorityFips.has(c.county_fips) ? "scope-priority-row" : undefined}
                  >
                    <td>{c.county_name}</td>
                    <td className="muted">{c.county_fips}</td>
                    <td>
                      {c.priority_market || priorityFips.has(c.county_fips) ? (
                        <span className="badge badge-priority">Priority</span>
                      ) : (
                        <span className="muted">WA pilot</span>
                      )}
                    </td>
                    <td>{c.parcels_in_db.toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>

            {scopeView.counties.length > countiesToShow.length ? (
              <button type="button" className="outline scope-toggle" onClick={() => setShowAllCounties((v) => !v)}>
                {showAllCounties ? "Show counties with data only" : `Show all ${scopeView.pilot_county_count} pilot counties`}
              </button>
            ) : null}
          </>
        ) : scopeLoading ? (
          <div className="scope-loading panel-inset" aria-busy="true">
            <p className="muted" style={{ margin: 0 }}>
              Loading parcel counts by county…
            </p>
          </div>
        ) : null}
      </div>

      <h2>Scoring totals</h2>
      {summaryErr ? <div className="error">{summaryErr}</div> : null}
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
        ) : summaryLoading ? (
          <p className="muted">Loading scoring totals…</p>
        ) : null}
      </div>

      <h2>Outreach candidates</h2>
      <p className="muted">
        <Link href="/outreach">Outreach pipeline</Link> lists parcels at or above the entitlement score floor, sorted
        by score. Use <strong>Needs action</strong> for blocked deals, errors, or pending approvals.{" "}
        <Link href="/deals">Deal progress</Link> shows the same pipeline runs with a step-by-step progress bar for
        every parcel that has started enrichment — not just qualified ones.
      </p>

      <h2>Data funnel</h2>
      <p className="muted">
        We do <strong>not</strong> pull owner enrichment, deal memos, or contracts on every ingested APN. Parcels narrow
        through market boundaries, prescreening, and selective full pipeline runs (Baltimore counties first in the queue).
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
                <strong>Operator views</strong> — outreach and deal boards focus on entitlement-qualified parcels, not the
                full multi-county inventory.
              </li>
            </ul>
          </div>
        </div>
      ) : summaryLoading ? (
        <p className="muted">Loading funnel…</p>
      ) : null}

      <details
        className="panel export-readiness-details"
        onToggle={(e) => setExportDetailsOpen((e.target as HTMLDetailsElement).open)}
      >
        <summary className="export-readiness-summary">Export readiness (technical JSON)</summary>
        {readinessErr ? <div className="error">{readinessErr}</div> : null}
        {readiness ? (
          <pre className="json">{JSON.stringify(readiness, null, 2)}</pre>
        ) : readinessLoading ? (
          <p className="muted">Loading export readiness…</p>
        ) : exportDetailsOpen ? null : (
          <p className="muted">Open to load gap diagnostics (skipped on initial page load).</p>
        )}
      </details>
    </div>
  );
}
