"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { bridgeUrl } from "../../lib/paths";

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
  pending_approval_count: number;
  pipeline_stage: string;
};

type Board = {
  qualified_min_entitlement_score: number;
  row_count: number;
  rows: Row[];
};

export default function OutreachPipelinePage() {
  const [board, setBoard] = useState<Board | null>(null);
  const [limit, setLimit] = useState(100);
  const [stageFilter, setStageFilter] = useState<string>("");
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setErr(null);
      try {
        const res = await fetch(bridgeUrl(`internal/pipeline/outreach-board?limit=${limit}`), {
          cache: "no-store",
        });
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
  }, [limit]);

  const stages = useMemo(() => {
    const s = new Set<string>();
    for (const r of board?.rows ?? []) s.add(r.pipeline_stage);
    return Array.from(s).sort();
  }, [board]);

  const filtered = useMemo(() => {
    const rows = board?.rows ?? [];
    if (!stageFilter) return rows;
    return rows.filter((r) => r.pipeline_stage === stageFilter);
  }, [board, stageFilter]);

  return (
    <main>
      <h1>Outreach pipeline</h1>
      <p className="muted">
        Parcels whose <strong>latest entitlement score</strong> meets the pilot floor — candidates worth tracking for
        owner outreach. Columns combine workflow status, outreach brief, and pending approvals.
      </p>

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
            <option value="">All</option>
            {stages.map((st) => (
              <option key={st} value={st}>
                {st}
              </option>
            ))}
          </select>
        </label>
      </div>

      {board ? (
        <p className="muted">
          Floor entitlement ≥ <strong>{board.qualified_min_entitlement_score}</strong> · showing{" "}
          <strong>{filtered.length}</strong> of <strong>{board.row_count}</strong> loaded
        </p>
      ) : null}

      {err ? <div className="error">{err}</div> : null}

      <div className="panel" style={{ overflowX: "auto" }}>
        <table className="data">
          <thead>
            <tr>
              <th>Stage</th>
              <th>APN</th>
              <th>County</th>
              <th>Ent / Id scores</th>
              <th>Workflow</th>
              <th>Brief</th>
              <th>Pending approvals</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {filtered.map((r) => (
              <tr key={r.parcel_id}>
                <td>
                  <span className="badge">{r.pipeline_stage}</span>
                </td>
                <td>{r.apn}</td>
                <td>{r.county_fips}</td>
                <td className="muted">
                  {r.entitlement_score != null ? r.entitlement_score.toFixed(1) : "—"} /{" "}
                  {r.identification_score != null ? r.identification_score.toFixed(1) : "—"}
                </td>
                <td>
                  <span className="muted">{r.workflow_status ?? "—"}</span>
                  {r.workflow_step ? (
                    <span className="muted">
                      <br />
                      {r.workflow_step}
                    </span>
                  ) : null}
                  {r.workflow_error ? (
                    <span className="error" style={{ fontSize: "0.78rem" }}>
                      <br />
                      {r.workflow_error.slice(0, 120)}
                    </span>
                  ) : null}
                  {r.workflow_updated_at ? (
                    <span className="muted">
                      <br />
                      {r.workflow_updated_at.slice(0, 19)}
                    </span>
                  ) : null}
                </td>
                <td>{r.has_outreach_brief ? "yes" : "no"}</td>
                <td>{r.pending_approval_count}</td>
                <td>
                  <Link href={`/parcels/${r.parcel_id}`}>Parcel →</Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {filtered.length === 0 && !err ? <p className="muted">No rows (or still loading).</p> : null}
      </div>
    </main>
  );
}
