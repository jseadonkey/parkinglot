"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

type Parcel = {
  id: string;
  apn: string;
  county_fips: string;
  lot_sqft: number | null;
  zoning_code: string | null;
  zoning_allows_surface_parking: boolean;
  is_corner_lot: boolean;
  distance_to_nearest_demand_m: number | null;
  owner_outreach_brief: Record<string, unknown> | null;
  created_at: string;
};

type WorkflowRun = {
  id: string;
  parcel_id: string;
  status: string;
  current_step: string | null;
  error: string | null;
  created_at: string;
  updated_at: string;
};

type Score = {
  score_profile: string;
  total_score: number;
  created_at: string;
};

const apiBase = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

export default function ParcelDetailPage() {
  const params = useParams();
  const id = typeof params.id === "string" ? params.id : "";
  const [parcel, setParcel] = useState<Parcel | null>(null);
  const [runs, setRuns] = useState<WorkflowRun[]>([]);
  const [score, setScore] = useState<Score | null>(null);
  const [scoreErr, setScoreErr] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    (async () => {
      setErr(null);
      try {
        const [rp, rr] = await Promise.all([
          fetch(`${apiBase}/parcels/${id}`, { cache: "no-store" }),
          fetch(`${apiBase}/parcels/${id}/workflow-runs?limit=20`, { cache: "no-store" }),
        ]);
        if (!rp.ok) throw new Error(`parcel ${rp.status}`);
        if (!rr.ok) throw new Error(`workflow-runs ${rr.status}`);
        const p = (await rp.json()) as Parcel;
        const w = (await rr.json()) as WorkflowRun[];
        if (!cancelled) {
          setParcel(p);
          setRuns(w);
        }
        const rs = await fetch(`${apiBase}/parcels/${id}/score?profile=entitlement`, { cache: "no-store" });
        if (rs.ok) {
          const s = (await rs.json()) as Score;
          if (!cancelled) setScore(s);
        } else {
          if (!cancelled) setScoreErr(`No entitlement score (${rs.status})`);
        }
      } catch (e) {
        if (!cancelled) setErr(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [id]);

  return (
    <main>
      <p className="muted">
        <Link href="/parcels">← Parcels</Link>
      </p>
      <h1>Parcel</h1>

      {err ? <div className="error">{err}</div> : null}

      {parcel ? (
        <>
          <div className="panel">
            <div className="row">
              <div>
                <strong>{parcel.apn}</strong>
                <span className="muted" style={{ marginLeft: "0.5rem" }}>
                  {parcel.county_fips}
                </span>
              </div>
              <span className="badge">{parcel.id}</span>
            </div>
            <div className="row">
              <span className="muted">Zoning</span>
              <span>{parcel.zoning_code ?? "—"}</span>
            </div>
            <div className="row">
              <span className="muted">Lot sqft</span>
              <span>{parcel.lot_sqft != null ? Math.round(parcel.lot_sqft) : "—"}</span>
            </div>
            <div className="row">
              <span className="muted">Demand distance (m)</span>
              <span>{parcel.distance_to_nearest_demand_m?.toFixed?.(1) ?? "—"}</span>
            </div>
            <div className="row">
              <span className="muted">Corner / zoning parking</span>
              <span>
                corner={String(parcel.is_corner_lot)} · surface_ok={String(parcel.zoning_allows_surface_parking)}
              </span>
            </div>
          </div>

          <h2>Scores</h2>
          <div className="panel">
            {score ? (
              <p>
                Latest <strong>entitlement</strong>: {score.total_score.toFixed(1)}{" "}
                <span className="muted">({score.created_at?.slice(0, 19)})</span>
              </p>
            ) : (
              <p className="muted">{scoreErr ?? "No score loaded."}</p>
            )}
          </div>

          <h2>Deal / workflow</h2>
          <div className="panel">
            {runs.length === 0 ? (
              <p className="muted">No workflow runs yet.</p>
            ) : (
              runs.map((r) => (
                <div key={r.id} className="row">
                  <div>
                    <span className="badge">{r.status}</span>
                    <span className="muted" style={{ marginLeft: "0.5rem" }}>
                      {r.current_step ?? "—"}
                    </span>
                    {r.error ? (
                      <div className="error" style={{ marginTop: "0.35rem" }}>
                        {r.error}
                      </div>
                    ) : null}
                  </div>
                  <span className="muted">{r.updated_at?.slice(0, 19)}</span>
                </div>
              ))
            )}
          </div>

          <h2>Owner outreach brief (structured)</h2>
          <p className="muted">
            This JSON is what the pipeline recorded for agent-assisted outreach — not a live SMS/email thread. For Atlas /
            Beacon chat-style logs, check Slack.
          </p>
          <div className="panel">
            {parcel.owner_outreach_brief ? (
              <pre className="json">{JSON.stringify(parcel.owner_outreach_brief, null, 2)}</pre>
            ) : (
              <p className="muted">No brief yet — run pipeline / Phase C enrichment.</p>
            )}
          </div>
        </>
      ) : !err ? (
        <p className="muted">Loading…</p>
      ) : null}
    </main>
  );
}
