"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { bridgeUrl } from "../../lib/paths";
import {
  formatRelativeTime,
  needsAction,
  stageBadgeClass,
  statusDetail,
  statusHeadline,
} from "../../lib/outreachLabels";
import { MarketFilters } from "../../components/MarketFilters";
import { countyLine, useCountyNames } from "../../lib/useCountyNames";
import {
  formatMonthlyGross,
  formatStallRange,
  type ParcelRevenueSummary,
} from "../../lib/revenueDisplay";
import { marketFilterParams, usePilotScope } from "../../lib/usePilotScope";

type Row = {
  parcel_id: string;
  apn: string;
  county_fips: string;
  entitlement_score: number | null;
  identification_score: number | null;
  workflow_run_id: string | null;
  workflow_status: string | null;
  workflow_step: string | null;
  workflow_error: string | null;
  workflow_updated_at: string | null;
  has_outreach_brief: boolean;
  owner_contact_decision: string;
  pending_approval_count: number;
  pipeline_stage: string;
  monthly_gross_usd: number | null;
  revenue_available: boolean;
  revenue: ParcelRevenueSummary | null;
};

type Board = {
  qualified_min_entitlement_score: number;
  row_count: number;
  rows: Row[];
};

type QuickFilter = "all" | "action" | "blocked" | "completed" | "failed" | "running";
type SortKey = "score" | "updated" | "approvals";

function matchesQuickFilter(row: Row, filter: QuickFilter): boolean {
  switch (filter) {
    case "action":
      return needsAction(row);
    case "blocked":
      return row.pipeline_stage === "blocked";
    case "completed":
      return row.pipeline_stage === "completed";
    case "failed":
      return row.pipeline_stage === "failed";
    case "running":
      return row.pipeline_stage === "running";
    default:
      return true;
  }
}

function sortRows(rows: Row[], sort: SortKey): Row[] {
  const copy = [...rows];
  copy.sort((a, b) => {
    if (sort === "score") {
      return (b.entitlement_score ?? 0) - (a.entitlement_score ?? 0);
    }
    if (sort === "approvals") {
      return b.pending_approval_count - a.pending_approval_count;
    }
    const ta = a.workflow_updated_at ? new Date(a.workflow_updated_at).getTime() : 0;
    const tb = b.workflow_updated_at ? new Date(b.workflow_updated_at).getTime() : 0;
    return tb - ta;
  });
  return copy;
}

export default function OutreachPipelinePage() {
  const countyLabel = useCountyNames();
  const { scope, priorityFips } = usePilotScope();
  const [board, setBoard] = useState<Board | null>(null);
  const [loading, setLoading] = useState(true);
  const [limit, setLimit] = useState(100);
  const [stateFips, setStateFips] = useState("24");
  const [countyFips, setCountyFips] = useState("");
  const [quickFilter, setQuickFilter] = useState<QuickFilter>("action");
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<SortKey>("score");
  const [err, setErr] = useState<string | null>(null);

  async function loadBoard() {
    setErr(null);
    setLoading(true);
    try {
      const geo = marketFilterParams(stateFips, countyFips);
      const qs = new URLSearchParams({ limit: String(limit), revenue_hints: "0" });
      geo.forEach((v, k) => qs.set(k, v));
      const res = await fetch(bridgeUrl(`internal/pipeline/outreach-board?${qs}`), {
        cache: "no-store",
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = (await res.json()) as Board;
      setBoard(data);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadBoard();
  }, [limit, stateFips, countyFips]);

  const stats = useMemo(() => {
    const rows = board?.rows ?? [];
    return {
      total: rows.length,
      action: rows.filter(needsAction).length,
      blocked: rows.filter((r) => r.pipeline_stage === "blocked").length,
      completed: rows.filter((r) => r.pipeline_stage === "completed").length,
      failed: rows.filter((r) => r.pipeline_stage === "failed").length,
      running: rows.filter((r) => r.pipeline_stage === "running").length,
      withApprovals: rows.filter((r) => r.pending_approval_count > 0).length,
      approvedContact: rows.filter((r) => r.owner_contact_decision === "approved").length,
    };
  }, [board]);

  const filtered = useMemo(() => {
    let rows = board?.rows ?? [];
    rows = rows.filter((r) => matchesQuickFilter(r, quickFilter));
    const q = search.trim().toLowerCase();
    if (q) {
      rows = rows.filter(
        (r) => r.apn.toLowerCase().includes(q) || r.parcel_id.toLowerCase().includes(q),
      );
    }
    return sortRows(rows, sort);
  }, [board, quickFilter, search, sort]);

  const quickFilters: { key: QuickFilter; label: string; count: number }[] = [
    { key: "action", label: "Needs action", count: stats.action },
    { key: "all", label: "All", count: stats.total },
    { key: "blocked", label: "Blocked", count: stats.blocked },
    { key: "completed", label: "Review", count: stats.completed },
    { key: "failed", label: "Failed", count: stats.failed },
    { key: "running", label: "Running", count: stats.running },
  ];

  return (
    <div className="page-content main-wide">
      <p className="muted" style={{ marginTop: 0 }}>
        Qualified deals for outreach. Defaults to <strong>Maryland</strong> while Baltimore loads; switch state to see
        Washington inventory.
      </p>
      <div className="page-actions">
        <button type="button" className="outline" onClick={() => void loadBoard()} disabled={loading}>
          {loading ? "Loading…" : "Refresh"}
        </button>
      </div>

      <div className="cols pipeline-stats">
        <div className="stat">
          <div className="n">{stats.action}</div>
          <div className="muted">Need your attention</div>
        </div>
        <div className="stat">
          <div className="n">{stats.withApprovals}</div>
          <div className="muted">Pending approvals</div>
        </div>
        <div className="stat">
          <div className="n">{stats.approvedContact}</div>
          <div className="muted">Approved for contact</div>
        </div>
        <div className="stat">
          <div className="n">{board?.qualified_min_entitlement_score ?? "—"}</div>
          <div className="muted">Score floor</div>
        </div>
      </div>

      <div className="panel toolbar">
        <div className="filter-chips" role="tablist" aria-label="Pipeline filter">
          {quickFilters.map((f) => (
            <button
              key={f.key}
              type="button"
              role="tab"
              aria-selected={quickFilter === f.key}
              className={quickFilter === f.key ? "chip chip-active" : "chip"}
              onClick={() => setQuickFilter(f.key)}
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
          <label className="toolbar-field">
            <span className="muted">Sort by</span>
            <select value={sort} onChange={(e) => setSort(e.target.value as SortKey)}>
              <option value="score">Entitlement score</option>
              <option value="updated">Last updated</option>
              <option value="approvals">Pending approvals</option>
            </select>
          </label>
          <label className="toolbar-field">
            <span className="muted">Load up to</span>
            <select value={limit} onChange={(e) => setLimit(Number(e.target.value))}>
              {[100, 250, 500, 1000, 2000].map((n) => (
                <option key={n} value={n}>
                  {n} parcels
                </option>
              ))}
            </select>
          </label>
        </div>
      </div>

      {board ? (
        <p className="muted result-meta">
          Showing <strong>{filtered.length}</strong> of <strong>{board.row_count}</strong> loaded
          {search.trim() ? ` matching “${search.trim()}”` : ""}
          {quickFilter !== "all" ? ` · filter: ${quickFilter}` : ""}
        </p>
      ) : null}

      {err ? <div className="error">{err}</div> : null}

      {loading && !board ? (
        <div className="panel muted">Loading pipeline…</div>
      ) : (
        <div className="panel panel-flush">
          {filtered.length === 0 && !err ? (
            <p className="muted empty-state">
              {quickFilter === "action"
                ? "Nothing needs action in the loaded set — try All or increase “Load up to”."
                : "No parcels match this filter."}
            </p>
          ) : (
            <table className="data pipeline-table">
              <thead>
                <tr>
                  <th>Parcel</th>
                  <th>Score</th>
                  <th>Est. gross</th>
                  <th>Status</th>
                  <th>Updated</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((r) => {
                  const headline = statusHeadline(r);
                  const detail = statusDetail(r);
                  const actionNeeded = needsAction(r);
                  return (
                    <tr key={r.parcel_id} className={actionNeeded ? "row-attention" : undefined}>
                      <td>
                        <Link href={`/parcels/${r.parcel_id}`} className="apn-link">
                          {r.apn}
                        </Link>
                        <div className="muted cell-sub">{countyLine(countyLabel, r.county_fips)}</div>
                      </td>
                      <td>
                        <div className="score-main">
                          {r.entitlement_score != null ? r.entitlement_score.toFixed(0) : "—"}
                        </div>
                        <div className="muted cell-sub">
                          id {r.identification_score != null ? r.identification_score.toFixed(0) : "—"}
                        </div>
                      </td>
                      <td className="muted">
                        {r.revenue?.revenue_available || r.revenue_available ? (
                          <>
                            <div>{formatMonthlyGross(r.revenue?.monthly_gross_usd ?? r.monthly_gross_usd)}</div>
                            <div className="cell-sub">
                              {formatStallRange(r.revenue)} stalls
                              {r.revenue?.hourly_rate_weighted_usd != null
                                ? ` · $${r.revenue.hourly_rate_weighted_usd.toFixed(2)}/hr`
                                : ""}
                            </div>
                          </>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td>
                        <div className="status-line">
                          <span className={stageBadgeClass(r.pipeline_stage)}>{headline}</span>
                        </div>
                        {detail ? (
                          <div className={`cell-sub ${r.workflow_error ? "error" : "muted"}`}>{detail}</div>
                        ) : null}
                        {r.has_outreach_brief ? (
                          <div className="muted cell-sub">
                            Brief ready · {r.owner_contact_decision.replaceAll("_", " ")}
                          </div>
                        ) : null}
                      </td>
                      <td className="muted">{formatRelativeTime(r.workflow_updated_at)}</td>
                      <td>
                        <div className="action-stack">
                          <Link href={`/parcels/${r.parcel_id}`} className="btn-link">
                            Open parcel
                          </Link>
                          {r.pending_approval_count > 0 ? (
                            <Link href="/approvals" className="btn-link btn-link-primary">
                              Review approval{r.pending_approval_count > 1 ? "s" : ""}
                            </Link>
                          ) : null}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}
