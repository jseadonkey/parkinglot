"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { bridgeUrl } from "../lib/paths";

export default function OverviewPage() {
  const [readiness, setReadiness] = useState<unknown>(null);
  const [summary, setSummary] = useState<unknown>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setErr(null);
      try {
        const [r1, r2] = await Promise.all([
          fetch(bridgeUrl("internal/stats/export-readiness"), { cache: "no-store" }),
          fetch(bridgeUrl("internal/stats/scoring-summary"), { cache: "no-store" }),
        ]);
        if (!r1.ok) throw new Error(`export-readiness ${r1.status}`);
        if (!r2.ok) throw new Error(`scoring-summary ${r2.status}`);
        const j1 = await r1.json();
        const j2 = await r2.json();
        if (!cancelled) {
          setReadiness(j1);
          setSummary(j2);
        }
      } catch (e) {
        if (!cancelled) setErr(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <main>
      <h1>Operator overview</h1>
      <p className="muted">
        Readiness gaps and scoring totals (via secure server bridge to <code>/internal/*</code>). Public parcel data
        uses the browser-facing API URL.
      </p>

      {err ? <div className="error">{err}</div> : null}

      <div className="cols" style={{ marginTop: "1rem" }}>
        {summary && typeof summary === "object" && summary !== null && "total_parcels" in summary ? (
          <>
            <div className="stat">
              <div className="muted">Parcels in DB</div>
              <div className="n">{String((summary as { total_parcels: number }).total_parcels)}</div>
            </div>
            <div className="stat">
              <div className="muted">With entitlement score</div>
              <div className="n">{String((summary as { parcels_with_latest_entitlement_score: number }).parcels_with_latest_entitlement_score)}</div>
            </div>
            <div className="stat">
              <div className="muted">With strategic score</div>
              <div className="n">{String((summary as { parcels_with_latest_strategic_score: number }).parcels_with_latest_strategic_score)}</div>
            </div>
            <div className="stat">
              <div className="muted">With identification score</div>
              <div className="n">{String((summary as { parcels_with_latest_identification_score: number }).parcels_with_latest_identification_score)}</div>
            </div>
          </>
        ) : (
          !err && <p className="muted">Loading scoring summary…</p>}
      </div>

      <h2>Export readiness (JSON)</h2>
      <div className="panel">
        {readiness ? <pre className="json">{JSON.stringify(readiness, null, 2)}</pre> : !err ? <p className="muted">Loading…</p> : null}
      </div>

      <h2>Outreach candidates</h2>
      <p className="muted">
        See <Link href="/outreach">Outreach pipeline</Link> for all parcels that meet the entitlement score floor, with deal
        workflow status and brief/approval columns.
      </p>

      <h2>Agent ↔ owner “conversations”</h2>
      <div className="panel">
        <p className="muted" style={{ marginTop: 0 }}>
          Structured outreach lives on each parcel as <code>owner_outreach_brief</code> (see Parcels → detail). Automated
          Atlas/Beacon discussions post to <strong>Slack</strong> when configured — this console does not ingest Slack
          history yet.
        </p>
      </div>
    </main>
  );
}
