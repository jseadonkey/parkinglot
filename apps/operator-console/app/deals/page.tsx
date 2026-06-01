"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

type WorkflowRun = {
  id: string;
  parcel_id: string;
  status: string;
  current_step: string | null;
  error: string | null;
  updated_at: string;
};

const apiBase = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

export default function DealsPage() {
  const [runs, setRuns] = useState<WorkflowRun[]>([]);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setErr(null);
      try {
        const res = await fetch(`${apiBase}/workflow-runs?limit=200`, { cache: "no-store" });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = (await res.json()) as WorkflowRun[];
        if (!cancelled) setRuns(data);
      } catch (e) {
        if (!cancelled) setErr(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const byStatus = useMemo(() => {
    const m = new Map<string, WorkflowRun[]>();
    for (const r of runs) {
      const k = r.status || "unknown";
      const arr = m.get(k) ?? [];
      arr.push(r);
      m.set(k, arr);
    }
    return m;
  }, [runs]);

  const statuses = Array.from(byStatus.keys()).sort();

  return (
    <main>
      <h1>Deal progress</h1>
      <p className="muted">
        Latest workflow runs across parcels — grouped by <code>status</code>. Open a parcel for outreach brief and
        scores.
      </p>

      {err ? <div className="error">{err}</div> : null}

      {statuses.map((st) => (
        <section key={st}>
          <h2>
            <span className="badge">{st}</span>
            <span className="muted" style={{ marginLeft: "0.5rem", fontWeight: 400 }}>
              ({byStatus.get(st)?.length ?? 0})
            </span>
          </h2>
          <div className="deal-grid">
            {(byStatus.get(st) ?? []).map((r) => (
              <div key={r.id} className="deal-card">
                <div className="status">{r.current_step ?? "—"}</div>
                <div className="muted" style={{ marginTop: "0.35rem", fontSize: "0.78rem" }}>
                  parcel{" "}
                  <Link href={`/parcels/${r.parcel_id}`}>{r.parcel_id.slice(0, 8)}…</Link>
                </div>
                {r.error ? <div className="error" style={{ marginTop: "0.35rem", fontSize: "0.78rem" }}>{r.error}</div> : null}
                <div className="muted" style={{ marginTop: "0.35rem" }}>
                  updated {r.updated_at?.slice(0, 19)}
                </div>
              </div>
            ))}
          </div>
        </section>
      ))}

      {runs.length === 0 && !err ? <p className="muted">No workflow runs yet.</p> : null}
    </main>
  );
}
