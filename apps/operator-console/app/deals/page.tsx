"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { bridgeUrl } from "../../lib/paths";
import {
  PIPELINE_STEPS,
  formatRelativeTime,
  pipelineProgressPercent,
  pipelineStepLabel,
  stageBadgeClass,
  statusLabel,
} from "../../lib/dealProgress";
import { MarketFilters } from "../../components/MarketFilters";
import { countyLine, useCountyNames } from "../../lib/useCountyNames";
import { marketFilterParams, usePilotScope } from "../../lib/usePilotScope";

type Row = {
  parcel_id: string;
  apn: string;
  county_fips: string;
  workflow_run_id: string;
  workflow_status: string;
  workflow_step: string | null;
  workflow_error: string | null;
  workflow_updated_at: string | null;
  pending_approval_count: number;
  pipeline_stage: string;
};

type Board = {
  summary: {
    total_parcels: number;
    by_status: Record<string, number>;
    by_step: Record<string, number>;
  };
  row_count: number;
  rows: Row[];
};

type StatusFilter = "all" | "running" | "blocked" | "completed" | "failed" | "action";

function matchesFilter(row: Row, filter: StatusFilter): boolean {
  switch (filter) {
    case "running":
      return row.pipeline_stage === "running";
    case "blocked":
      return row.pipeline_stage === "blocked";
    case "completed":
      return row.pipeline_stage === "completed";
    case "failed":
      return row.pipeline_stage === "failed";
    case "action":
      return (
        row.pipeline_stage === "blocked" ||
        row.pipeline_stage === "failed" ||
        row.pending_approval_count > 0
      );
    default:
      return true;
  }
}

function ProgressBar({ row }: { row: Row }) {
  const pct = pipelineProgressPercent(row);
  const currentIdx = row.workflow_step
    ? PIPELINE_STEPS.indexOf(row.workflow_step as (typeof PIPELINE_STEPS)[number])
    : -1;

  return (
    <div className="progress-wrap" title={`${pct}% through pipeline`}>
      <div className="progress-track">
        <div
          className={`progress-fill ${row.pipeline_stage === "failed" ? "progress-fill-err" : ""}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <div className="progress-steps muted">
        {PIPELINE_STEPS.map((step, i) => (
          <span
            key={step}
            className={
              row.pipeline_stage === "completed"
                ? "step-done"
                : i === currentIdx
                  ? "step-current"
                  : i < currentIdx
                    ? "step-done"
                    : ""
            }
          >
            {pipelineStepLabel(step)}
          </span>
        ))}
      </div>
    </div>
  );
}

export default function DealsPage() {
  const countyLabel = useCountyNames();
  const { scope, priorityFips } = usePilotScope();
  const [board, setBoard] = useState<Board | null>(null);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<StatusFilter>("all");
  const [search, setSearch] = useState("");
  const [stateFips, setStateFips] = useState("");
  const [countyFips, setCountyFips] = useState("");
  const [err, setErr] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setErr(null);
    try {
      const geo = marketFilterParams(stateFips, countyFips);
      const qs = new URLSearchParams({ limit: "500" });
      geo.forEach((v, k) => qs.set(k, v));
      const res = await fetch(bridgeUrl(`internal/pipeline/deal-progress?${qs}`), {
        cache: "no-store",
      });
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
  }, [stateFips, countyFips]);

  const summary = board?.summary;
  const filtered = useMemo(() => {
    let rows = board?.rows ?? [];
    rows = rows.filter((r) => matchesFilter(r, filter));
    const q = search.trim().toLowerCase();
    if (q) rows = rows.filter((r) => r.apn.toLowerCase().includes(q));
    return rows;
  }, [board, filter, search]);

  const filters: { key: StatusFilter; label: string; count: number }[] = [
    { key: "all", label: "All parcels", count: summary?.total_parcels ?? 0 },
    { key: "action", label: "Needs you", count: (board?.rows ?? []).filter((r) => matchesFilter(r, "action")).length },
    { key: "running", label: "Processing", count: summary?.by_status.running ?? 0 },
    { key: "blocked", label: "Blocked", count: summary?.by_status.blocked ?? 0 },
    { key: "completed", label: "Complete", count: summary?.by_status.completed ?? 0 },
    { key: "failed", label: "Failed", count: summary?.by_status.failed ?? 0 },
  ];

  const stepCounts = summary?.by_step ?? {};

  const mdParcelCount =
    scope?.counties
      .filter((c) => c.county_fips.startsWith("24"))
      .reduce((n, c) => n + c.parcels_in_db, 0) ?? null;
  const emptyGeoHint =
    !loading && board && board.row_count === 0 && (stateFips || countyFips)
      ? stateFips === "24" && mdParcelCount && mdParcelCount > 0
        ? `Maryland has ${mdParcelCount.toLocaleString()} parcels in the database, but none have a pipeline run yet. Open the Outreach pipeline for scored deals, or enqueue Baltimore priority pipelines from the Droplet.`
        : "No parcels in this market have a pipeline run yet. Ingest and scoring can exist without a run — use Outreach pipeline or Parcels for inventory."
      : null;

  return (
    <div className="page-content main-wide">
      <p className="muted" style={{ marginTop: 0 }}>
        Parcels that have started the enrichment pipeline (workflow run). For qualified inventory before a run exists,
        use <Link href="/outreach">Outreach pipeline</Link> or <Link href="/parcels">Parcels</Link>.
      </p>
      <div className="page-actions">
        <button type="button" className="outline" onClick={() => void load()} disabled={loading}>
          {loading ? "Loading…" : "Refresh"}
        </button>
      </div>

      {summary ? (
        <div className="cols pipeline-stats">
          <div className="stat">
            <div className="n">{summary.by_status.running ?? 0}</div>
            <div className="muted">Processing now</div>
          </div>
          <div className="stat">
            <div className="n">{summary.by_status.blocked ?? 0}</div>
            <div className="muted">Waiting on you</div>
          </div>
          <div className="stat">
            <div className="n">{summary.by_status.completed ?? 0}</div>
            <div className="muted">Complete</div>
          </div>
          <div className="stat">
            <div className="n">{summary.by_status.failed ?? 0}</div>
            <div className="muted">Failed</div>
          </div>
        </div>
      ) : null}

      {Object.keys(stepCounts).length > 0 ? (
        <div className="panel funnel-panel">
          <div className="muted" style={{ marginBottom: "0.5rem" }}>
            Currently processing — step breakdown
          </div>
          <div className="funnel-row">
            {PIPELINE_STEPS.map((step) => {
              const n = stepCounts[step] ?? 0;
              if (n === 0 && step !== "enrich") return null;
              return (
                <div key={step} className="funnel-item">
                  <span className="funnel-n">{n}</span>
                  <span className="muted">{pipelineStepLabel(step)}</span>
                </div>
              );
            })}
          </div>
        </div>
      ) : null}

      <div className="panel toolbar">
        <div className="filter-chips" role="tablist" aria-label="Deal status filter">
          {filters.map((f) => (
            <button
              key={f.key}
              type="button"
              role="tab"
              aria-selected={filter === f.key}
              className={filter === f.key ? "chip chip-active" : "chip"}
              onClick={() => setFilter(f.key)}
            >
              {f.label}
              <span className="chip-count">{f.count}</span>
            </button>
          ))}
        </div>
        <div className="toolbar-row">
          <MarketFilters
            stateFips={stateFips}
            countyFips={countyFips}
            counties={scope?.counties ?? []}
            priorityFips={priorityFips}
            onStateChange={setStateFips}
            onCountyChange={setCountyFips}
          />
          <label className="toolbar-field">
            <span className="muted">Search APN</span>
            <input
              type="search"
              placeholder="e.g. 033-0006800036"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </label>
        </div>
      </div>

      {board ? (
        <p className="muted result-meta">
          Showing <strong>{filtered.length}</strong> of <strong>{board.row_count}</strong> parcels
        </p>
      ) : null}

      {err ? <div className="error">{err}</div> : null}
      {emptyGeoHint ? <div className="panel muted">{emptyGeoHint}</div> : null}

      {loading && !board ? (
        <div className="panel muted">Loading deal progress…</div>
      ) : (
        <div className="panel panel-flush">
          {filtered.length === 0 && !err ? (
            <p className="muted empty-state">No parcels match this filter.</p>
          ) : (
            <table className="data pipeline-table">
              <thead>
                <tr>
                  <th>Parcel</th>
                  <th>Progress</th>
                  <th>Status</th>
                  <th>Updated</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {filtered.map((r) => (
                  <tr
                    key={r.parcel_id}
                    className={
                      r.pipeline_stage === "blocked" || r.pending_approval_count > 0
                        ? "row-attention"
                        : undefined
                    }
                  >
                    <td>
                      <Link href={`/parcels/${r.parcel_id}`} className="apn-link">
                        {r.apn}
                      </Link>
                      <div className="muted cell-sub">{countyLine(countyLabel, r.county_fips)}</div>
                    </td>
                    <td style={{ minWidth: "14rem" }}>
                      <ProgressBar row={r} />
                    </td>
                    <td>
                      <span className={stageBadgeClass(r.pipeline_stage)}>
                        {statusLabel(r.pipeline_stage, r.workflow_step, r.pending_approval_count)}
                      </span>
                      {r.workflow_error ? (
                        <div className="error cell-sub">{r.workflow_error.slice(0, 100)}</div>
                      ) : null}
                      {r.pending_approval_count > 0 ? (
                        <div className="muted cell-sub">
                          {r.pending_approval_count} approval{r.pending_approval_count > 1 ? "s" : ""} pending
                        </div>
                      ) : null}
                    </td>
                    <td className="muted">{formatRelativeTime(r.workflow_updated_at)}</td>
                    <td>
                      <div className="action-stack">
                        <Link href={`/parcels/${r.parcel_id}`} className="btn-link">
                          Open
                        </Link>
                        {r.pending_approval_count > 0 ? (
                          <Link href="/approvals" className="btn-link btn-link-primary">
                            Approve
                          </Link>
                        ) : null}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}
