"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { OperatorGuide, QuickStartCards } from "../components/OperatorGuide";
import { needsAction } from "../lib/outreachLabels";
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

type GapStat = {
  count: number;
  pct: number;
  floor?: number;
  target_count?: number;
  entitlement_floor?: number;
  strategic_floor?: number;
};

type ExportReadiness = {
  parcel_row_total: number;
  parcels_missing_footprint: GapStat;
  parcels_missing_zoning_code: GapStat;
  parcels_missing_lot_sqft: GapStat;
  parcels_missing_distance_to_nearest_demand_m: GapStat;
  parcels_missing_poi_commercial_count_400m: GapStat;
  parcels_poi_density_candidates: GapStat;
  parcels_missing_poi_commercial_count_400m_all?: GapStat;
  parcels_missing_score_identification: GapStat;
  parcels_missing_score_entitlement: GapStat;
  parcels_missing_score_strategic: GapStat;
  parcels_missing_entitlement_or_strategic: GapStat;
  parcels_prescreen_qualified: GapStat;
  parcels_pipeline_funnel_backlog: GapStat;
  parcels_ruled_out_by_prescreen: GapStat;
  parcels_ruled_out_at_atlas: GapStat;
  parcels_owner_outreach_targets: GapStat;
  parcels_missing_owner_outreach_brief: GapStat;
  recommended_next_steps: string[];
};

type OutreachRow = {
  pipeline_stage: string;
  workflow_status: string | null;
  workflow_step: string | null;
  workflow_error: string | null;
  pending_approval_count: number;
  has_outreach_brief: boolean;
};

type OutreachBoard = {
  qualified_min_entitlement_score: number;
  owner_outreach_min_entitlement_score: number;
  owner_outreach_min_strategic_score: number;
  row_count: number;
  rows: OutreachRow[];
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

type ActionCard = {
  key: string;
  title: string;
  detail: string;
  href?: string;
  linkLabel?: string;
  tone: "ok" | "warn" | "err" | "run";
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

function isOutreachBoard(s: unknown): s is OutreachBoard {
  return (
    typeof s === "object" &&
    s !== null &&
    "rows" in s &&
    Array.isArray((s as OutreachBoard).rows) &&
    "row_count" in s
  );
}

function formatCount(n: number | null): string {
  if (n === null) return "—";
  return n.toLocaleString();
}

function formatPct(n: number | null): string {
  if (n === null) return "—";
  return `${n.toFixed(n >= 10 ? 0 : 1)}%`;
}

function funnelWidthPct(count: number, base: number): number {
  if (base <= 0) return 8;
  return Math.max(8, Math.round((count / base) * 100));
}

function gapTone(gap: GapStat | null): "ok" | "warn" | "err" {
  if (!gap || gap.count === 0) return "ok";
  if (gap.pct >= 50) return "err";
  return "warn";
}

function coveragePct(total: number, gap: GapStat | null): number | null {
  if (!gap || total <= 0) return null;
  return Math.max(0, Math.min(100, 100 - gap.pct));
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
  const [outreachBoard, setOutreachBoard] = useState<unknown>(null);
  const [scopeLoading, setScopeLoading] = useState(true);
  const [summaryLoading, setSummaryLoading] = useState(true);
  const [readinessLoading, setReadinessLoading] = useState(true);
  const [outreachLoading, setOutreachLoading] = useState(true);
  const [scopeErr, setScopeErr] = useState<string | null>(null);
  const [summaryErr, setSummaryErr] = useState<string | null>(null);
  const [readinessErr, setReadinessErr] = useState<string | null>(null);
  const [outreachErr, setOutreachErr] = useState<string | null>(null);
  const [showAllCounties, setShowAllCounties] = useState(false);

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
  }, []);

  useEffect(() => {
    let cancelled = false;
    setOutreachLoading(true);
    setOutreachErr(null);
    fetchJson("internal/pipeline/outreach-board?limit=250&revenue_hints=1")
      .then((data) => {
        if (!cancelled) setOutreachBoard(data);
      })
      .catch((e) => {
        if (!cancelled) setOutreachErr(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) setOutreachLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const scopeView = isPilotScope(scope) ? scope : null;
  const summaryView = isScoringSummary(summary) ? summary : null;
  const readinessView = isExportReadiness(readiness) ? readiness : null;
  const outreachView = isOutreachBoard(outreachBoard) ? outreachBoard : null;
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
    if (!summaryView) return [];
    const ownerTargetTotal = readinessView?.parcels_owner_outreach_targets?.count ?? null;
    const withBrief = readinessView
      ? Math.max(
          0,
          (readinessView.parcels_missing_owner_outreach_brief.target_count ??
            ownerTargetTotal ??
            readinessView.parcel_row_total) - readinessView.parcels_missing_owner_outreach_brief.count,
        )
      : null;
    const floors = summaryView.qualified_min_score;

    return [
      {
        key: "ingested",
        label: "Parcels ingested",
        detail:
          "Only APNs loaded from county GIS (Baltimore EGIS, Washington assessor/WaTech) — not every parcel in configured markets.",
        count: summaryView.total_parcels,
      },
      {
        key: "identification",
        label: `Identification prescreen (≥ ${floors.identification})`,
        detail:
          "Cartographer score at ingest — only parcels at or above this floor should enter the full pipeline (owner lookup, memo, contract).",
        count: summaryView.qualified_count_identification,
      },
      {
        key: "pipeline",
        label: "Full pipeline scored",
        detail:
          "Atlas (entitlement) first — if below floor, Beacon and enrichment are skipped. If Atlas passes, Beacon runs; enrichment only when both pass.",
        count: summaryView.parcels_with_both_profiles_scored,
      },
      {
        key: "qualified",
        label: `Qualified (entitlement ≥ ${floors.entitlement})`,
        detail: "Parcels meeting the pilot floor for deal outreach and operator boards.",
        count: summaryView.qualified_count_entitlement,
      },
      {
        key: "brief",
        label: "Target owner outreach brief",
        detail: readinessView
          ? "Deep enrichment only for dual-high-score owner outreach targets: owners, registry stub, vendor lookup, contact points, memo + contract draft."
          : "Deep enrichment counts load with export readiness.",
        count: withBrief,
      },
    ];
  }, [summaryView, readinessView]);

  const outreachStats = useMemo(() => {
    const rows = outreachView?.rows ?? [];
    return {
      loaded: rows.length,
      total: outreachView?.row_count ?? null,
      needsAction: rows.filter(needsAction).length,
      ready: rows.filter((r) => r.pipeline_stage === "completed").length,
      blocked: rows.filter((r) => r.pipeline_stage === "blocked").length,
      failed: rows.filter((r) => r.pipeline_stage === "failed").length,
      running: rows.filter((r) => r.pipeline_stage === "running").length,
      pendingApprovals: rows.filter((r) => r.pending_approval_count > 0).length,
      missingBrief: rows.filter((r) => !r.has_outreach_brief).length,
    };
  }, [outreachView]);

  const coverageCards = useMemo(() => {
    if (!readinessView) return [];
    const total = readinessView.parcel_row_total;
    const ownerTargetTotal =
      readinessView.parcels_missing_owner_outreach_brief.target_count ??
      readinessView.parcels_owner_outreach_targets?.count ??
      total;
    return [
      {
        key: "zoning",
        label: "Zoning attached",
        detail: "Phase B overlay coverage",
        value: coveragePct(total, readinessView.parcels_missing_zoning_code),
        missing: readinessView.parcels_missing_zoning_code,
      },
      {
        key: "demand",
        label: "Demand distance",
        detail: "Revenue and strategic signal",
        value: coveragePct(total, readinessView.parcels_missing_distance_to_nearest_demand_m),
        missing: readinessView.parcels_missing_distance_to_nearest_demand_m,
      },
      {
        key: "poi",
        label: "POI density",
        detail: "Occupancy confidence for qualified POI candidates",
        value: coveragePct(
          readinessView.parcels_poi_density_candidates?.count ?? total,
          readinessView.parcels_missing_poi_commercial_count_400m,
        ),
        missing: readinessView.parcels_missing_poi_commercial_count_400m,
      },
      {
        key: "brief",
        label: "Target owner briefs",
        detail: "Phase C readiness for owner outreach target lots",
        value: coveragePct(ownerTargetTotal, readinessView.parcels_missing_owner_outreach_brief),
        missing: readinessView.parcels_missing_owner_outreach_brief,
      },
    ];
  }, [readinessView]);

  const actionCards = useMemo((): ActionCard[] => {
    const cards: ActionCard[] = [];
    if (outreachStats.pendingApprovals > 0) {
      cards.push({
        key: "approvals",
        title: `${outreachStats.pendingApprovals.toLocaleString()} approval queue item${
          outreachStats.pendingApprovals === 1 ? "" : "s"
        }`,
        detail: "Human approval is the fastest unblock for deals already prepared by the pipeline.",
        href: "/approvals",
        linkLabel: "Review approvals",
        tone: "warn",
      });
    }
    if (outreachStats.failed > 0) {
      cards.push({
        key: "failed",
        title: `${outreachStats.failed.toLocaleString()} failed pipeline run${
          outreachStats.failed === 1 ? "" : "s"
        }`,
        detail: "Open the outreach board to inspect workflow errors and decide whether to rerun or skip.",
        href: "/outreach",
        linkLabel: "Open outreach board",
        tone: "err",
      });
    }
    if (outreachStats.blocked > 0) {
      cards.push({
        key: "blocked",
        title: `${outreachStats.blocked.toLocaleString()} blocked deal${
          outreachStats.blocked === 1 ? "" : "s"
        }`,
        detail: "These parcels are past scoring but need a human decision, missing input, or workflow cleanup.",
        href: "/deals",
        linkLabel: "Open deal progress",
        tone: "warn",
      });
    }
    if (readinessView && readinessView.parcels_pipeline_funnel_backlog.count > 0) {
      cards.push({
        key: "pipeline-backlog",
        title: `${readinessView.parcels_pipeline_funnel_backlog.count.toLocaleString()} prescreen-qualified parcel${
          readinessView.parcels_pipeline_funnel_backlog.count === 1 ? "" : "s"
        } need full scoring`,
        detail: "This is the clean backlog for run_pipeline: Atlas/Beacon should run before owner enrichment decisions.",
        href: "/deals",
        linkLabel: "View pipeline progress",
        tone: "run",
      });
    }
    if (readinessView && readinessView.parcels_missing_zoning_code.count > 0) {
      cards.push({
        key: "zoning",
        title: `${readinessView.parcels_missing_zoning_code.count.toLocaleString()} parcel${
          readinessView.parcels_missing_zoning_code.count === 1 ? "" : "s"
        } missing zoning`,
        detail: "Phase B remains the highest-leverage data gap: build/merge overlays so entitlement scores are defensible.",
        href: "/parcels",
        linkLabel: "Review parcel inventory",
        tone: gapTone(readinessView.parcels_missing_zoning_code) === "err" ? "err" : "warn",
      });
    }
    if (readinessView && readinessView.parcels_missing_distance_to_nearest_demand_m.count > 0) {
      cards.push({
        key: "demand",
        title: `${readinessView.parcels_missing_distance_to_nearest_demand_m.count.toLocaleString()} parcel${
          readinessView.parcels_missing_distance_to_nearest_demand_m.count === 1 ? "" : "s"
        } missing demand distance`,
        detail: "Refresh demand distances after demand-generator config changes to improve strategic ranking and revenue confidence.",
        href: "/parcels",
        linkLabel: "Review parcels",
        tone: "warn",
      });
    }
    if (cards.length === 0 && outreachStats.ready > 0) {
      cards.push({
        key: "ready",
        title: `${outreachStats.ready.toLocaleString()} outreach-ready deal${
          outreachStats.ready === 1 ? "" : "s"
        } in the loaded set`,
        detail: "The next highest-value move is human review of the ready list and owner/operator outreach decisions.",
        href: "/outreach",
        linkLabel: "Open ready deals",
        tone: "ok",
      });
    }
    if (cards.length === 0) {
      cards.push({
        key: "loading-or-clear",
        title: outreachLoading || readinessLoading ? "Building the action picture…" : "No urgent blocker detected",
        detail:
          outreachLoading || readinessLoading
            ? "Readiness and outreach samples are still loading."
            : "Use Outreach for ready deals, or continue with the next market zoning/revenue enrichment batch.",
        href: "/outreach",
        linkLabel: "Open outreach board",
        tone: "ok",
      });
    }
    return cards.slice(0, 4);
  }, [outreachStats, readinessView, outreachLoading, readinessLoading]);

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

      <h2>Executive action dashboard</h2>
      <div className="panel action-dashboard">
        <div className="action-dashboard-head">
          <div>
            <div className="scope-region">Opportunity pipeline health</div>
            <p className="muted scope-sub">
              A business-readable view of what is ready, what needs a person, and which data gaps are blocking better
              parcel decisions.
            </p>
          </div>
          <div className="scope-badges">
            <span className="badge badge-priority">Baltimore-first operating loop</span>
            <span className="badge">Sample: top {formatCount(outreachStats.loaded)} qualified rows</span>
          </div>
        </div>

        {(readinessErr || outreachErr) && (
          <div className="action-errors">
            {readinessErr ? <div className="error">Readiness: {readinessErr}</div> : null}
            {outreachErr ? <div className="error">Outreach board: {outreachErr}</div> : null}
          </div>
        )}

        <div className="executive-metrics">
          <div className="stat stat-emphasis">
            <div className="muted">Outreach-ready</div>
            <div className="n">{outreachLoading ? "…" : formatCount(outreachStats.ready)}</div>
            <div className="cell-sub muted">Completed pipeline in loaded qualified set</div>
          </div>
          <div className="stat stat-emphasis">
            <div className="muted">Need a person</div>
            <div className="n">{outreachLoading ? "…" : formatCount(outreachStats.needsAction)}</div>
            <div className="cell-sub muted">Blocked, failed, or approvals waiting</div>
          </div>
          <div className="stat stat-emphasis">
            <div className="muted">Pipeline backlog</div>
            <div className="n">
              {readinessLoading ? "…" : formatCount(readinessView?.parcels_pipeline_funnel_backlog.count ?? null)}
            </div>
            <div className="cell-sub muted">Prescreen-qualified parcels needing Atlas/Beacon</div>
          </div>
          <div className="stat stat-emphasis">
            <div className="muted">Owner outreach floor</div>
            <div className="n">
              {outreachLoading
                ? "…"
                : outreachView
                  ? `${formatCount(outreachView.owner_outreach_min_entitlement_score ?? null)} / ${formatCount(
                      outreachView.owner_outreach_min_strategic_score ?? null,
                    )}`
                  : "—"}
            </div>
            <div className="cell-sub muted">Atlas / Beacon thresholds for outreach board</div>
          </div>
        </div>

        <div className="action-card-grid">
          {actionCards.map((card) => (
            <div key={card.key} className={`action-card action-card-${card.tone}`}>
              <strong>{card.title}</strong>
              <p className="muted">{card.detail}</p>
              {card.href ? (
                <Link href={card.href} className="btn-link btn-link-primary">
                  {card.linkLabel ?? "Open"}
                </Link>
              ) : null}
            </div>
          ))}
        </div>

        {coverageCards.length > 0 ? (
          <div className="readiness-grid">
            {coverageCards.map((card) => {
              const tone = gapTone(card.missing);
              return (
                <div key={card.key} className={`readiness-card readiness-card-${tone}`}>
                  <div className="readiness-card-top">
                    <strong>{card.label}</strong>
                    <span>{formatPct(card.value)}</span>
                  </div>
                  <div className="progress-track readiness-track">
                    <div
                      className={`progress-fill ${tone === "err" ? "progress-fill-err" : ""}`}
                      style={{ width: `${card.value ?? 0}%` }}
                    />
                  </div>
                  <p className="muted">
                    {card.detail} · missing {card.missing.count.toLocaleString()} ({formatPct(card.missing.pct)})
                  </p>
                </div>
              );
            })}
          </div>
        ) : readinessLoading ? (
          <p className="muted">Loading readiness blockers…</p>
        ) : null}
      </div>

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
            <span className="badge badge-priority">Priority: Baltimore City</span>
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
        {summaryView ? (
          <>
            <div className="stat">
              <div className="muted">Parcels in DB</div>
              <div className="n">{formatCount(summaryView.total_parcels)}</div>
            </div>
            <div className="stat">
              <div className="muted">Identification prescreen</div>
              <div className="n">{formatCount(summaryView.parcels_with_latest_identification_score)}</div>
            </div>
            <div className="stat">
              <div className="muted">Full pipeline (both scores)</div>
              <div className="n">{formatCount(summaryView.parcels_with_both_profiles_scored)}</div>
            </div>
            <div className="stat">
              <div className="muted">Qualified (entitlement)</div>
              <div className="n">{formatCount(summaryView.qualified_count_entitlement)}</div>
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
      >
        <summary className="export-readiness-summary">Technical export-readiness JSON</summary>
        {readinessErr ? <div className="error">{readinessErr}</div> : null}
        {readiness ? (
          <pre className="json">{JSON.stringify(readiness, null, 2)}</pre>
        ) : readinessLoading ? (
          <p className="muted">Loading export readiness…</p>
        ) : (
          <p className="muted">No readiness payload loaded.</p>
        )}
      </details>
    </div>
  );
}
