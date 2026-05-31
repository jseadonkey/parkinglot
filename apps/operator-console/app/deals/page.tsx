"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { ScoringMethodologyPanel } from "../../components/ScoringMethodologyPanel";
import { bridgeUrl } from "../../lib/paths";
import { DUAL_QUALIFICATION_NOTE, SCORE_COLUMN_LEGEND } from "../../lib/scoringMethodology";
import { DEAL_STAGE_OPTIONS, dealStageBadgeClass } from "../../lib/pilotFunnelContent";

type Row = {
  parcel_id: string;
  apn: string;
  county_fips: string;
  entitlement_score: number | null;
  strategic_score: number | null;
  identification_score: number | null;
  deal_stage: string;
  deal_stage_label: string;
  workflow_status: string | null;
  workflow_step: string | null;
  workflow_error: string | null;
  workflow_updated_at: string | null;
  owner_research_tier: string | null;
  pending_approval_count: number;
  has_approved_memo: boolean;
  has_approved_contract: boolean;
};

type Board = {
  qualified_min_entitlement_score: number;
  qualified_min_strategic_score: number;
  stage_counts: Record<string, number>;
  row_count: number;
  rows: Row[];
};

export default function DealsPage() {
  const [board, setBoard] = useState<Board | null>(null);
  const [limit, setLimit] = useState(500);
  const [stageFilter, setStageFilter] = useState("");
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setErr(null);
      try {
        const qs = new URLSearchParams({ limit: String(limit) });
        if (stageFilter) qs.set("stage", stageFilter);
        const res = await fetch(bridgeUrl(`internal/pipeline/deal-progress?${qs}`), { cache: "no-store" });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = (await res.json()) as Board;
        if (!cancelled) setBoard(data);
      } catch (e) {
        if (!cancelled) setErr(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [limit, stageFilter]);

  const stageSummary = useMemo(() => {
    if (!board?.stage_counts) return [];
    return DEAL_STAGE_OPTIONS.filter((o) => o.id).map((o) => ({
      ...o,
      count: board.stage_counts[o.id] ?? 0,
    }));
  }, [board]);

  return (
    <main>
      <h1>Deal progress</h1>
      <p className="muted">
        One row per in-scope parcel (latest pipeline run). Stages are operator-friendly — not raw{" "}
        <code>completed / enrich</code> labels. {DUAL_QUALIFICATION_NOTE}
      </p>

      <ScoringMethodologyPanel variant="full" />

      <div className="panel" style={{ display: "flex", gap: "1rem", flexWrap: "wrap", alignItems: "center" }}>
        <label className="muted">
          Max rows{" "}
          <select value={limit} onChange={(e) => setLimit(Number(e.target.value))}>
            {[100, 250, 500, 1000, 2000].map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>
        <label className="muted">
          Stage{" "}
          <select value={stageFilter} onChange={(e) => setStageFilter(e.target.value)}>
            {DEAL_STAGE_OPTIONS.map((o) => (
              <option key={o.id || "all"} value={o.id}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      {board ? (
        <div className="stage-summary">
          {stageSummary.map((s) => (
            <button
              key={s.id}
              type="button"
              className={`stage-chip ${stageFilter === s.id ? "stage-chip--active" : ""}`}
              onClick={() => setStageFilter(stageFilter === s.id ? "" : s.id)}
            >
              <span className={`badge ${dealStageBadgeClass(s.id)}`}>{s.count}</span>
              <span>{s.label}</span>
            </button>
          ))}
        </div>
      ) : null}

      {board ? (
        <p className="muted">
          Floors: entitlement (Atlas) ≥ <strong>{board.qualified_min_entitlement_score}</strong> · strategic (Beacon) ≥{" "}
          <strong>{board.qualified_min_strategic_score}</strong> · showing <strong>{board.row_count}</strong> parcel(s)
          {stageFilter ? ` in “${DEAL_STAGE_OPTIONS.find((o) => o.id === stageFilter)?.label ?? stageFilter}”` : ""}.
        </p>
      ) : null}

      {err ? <div className="error">{err}</div> : null}

      <div className="panel" style={{ overflowX: "auto" }}>
        <table className="data">
          <thead>
            <tr>
              <th>Deal stage</th>
              <th>APN</th>
              <th title={SCORE_COLUMN_LEGEND}>Ent / Str / Id</th>
              <th>Owner tier</th>
              <th>Approvals</th>
              <th>Updated</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {(board?.rows ?? []).map((r) => (
              <tr key={r.parcel_id}>
                <td>
                  <span className={`badge ${dealStageBadgeClass(r.deal_stage)}`}>{r.deal_stage_label}</span>
                  {r.workflow_error ? (
                    <div className="error" style={{ fontSize: "0.75rem", marginTop: "0.25rem" }}>
                      {r.workflow_error.slice(0, 100)}
                    </div>
                  ) : null}
                </td>
                <td>{r.apn}</td>
                <td className="muted">
                  {r.entitlement_score != null ? r.entitlement_score.toFixed(1) : "—"} /{" "}
                  {r.strategic_score != null ? r.strategic_score.toFixed(1) : "—"} /{" "}
                  {r.identification_score != null ? r.identification_score.toFixed(1) : "—"}
                </td>
                <td className="muted">{r.owner_research_tier ?? "—"}</td>
                <td className="muted">
                  {r.pending_approval_count > 0 ? (
                    <span>{r.pending_approval_count} pending</span>
                  ) : r.has_approved_memo && r.has_approved_contract ? (
                    <span>Memo + contract approved</span>
                  ) : (
                    "—"
                  )}
                </td>
                <td className="muted">{r.workflow_updated_at?.slice(0, 19) ?? "—"}</td>
                <td>
                  <Link href={`/parcels/${r.parcel_id}`}>Open parcel</Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!board && !err ? <p className="muted">Loading…</p> : null}
        {board && board.rows.length === 0 ? <p className="muted">No parcels in this stage.</p> : null}
      </div>
    </main>
  );
}
