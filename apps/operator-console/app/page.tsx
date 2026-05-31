"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { OperationsModelPanel } from "../components/OperationsModelPanel";
import { PilotDataFunnel } from "../components/PilotDataFunnel";
import { ScoringMethodologyPanel } from "../components/ScoringMethodologyPanel";
import { bridgeUrl } from "../lib/paths";

type ScoringSummary = {
  total_parcels: number;
  parcels_with_latest_entitlement_score: number;
  parcels_with_latest_strategic_score: number;
  parcels_with_latest_identification_score: number;
  pilot_region?: string;
};

type IngestStatus = {
  ingest_active: boolean;
  phase: string;
  headline: string;
  detail: string;
  candidate_feature_count: number | null;
  parcels_in_scope_db: number;
  parcels_with_entitlement_score: number;
};

function isScoringSummary(s: unknown): s is ScoringSummary {
  return typeof s === "object" && s !== null && "total_parcels" in s;
}

function isIngestStatus(s: unknown): s is IngestStatus {
  return typeof s === "object" && s !== null && "phase" in s && "headline" in s;
}

export default function OverviewPage() {
  const [readiness, setReadiness] = useState<unknown>(null);
  const [summary, setSummary] = useState<unknown>(null);
  const [ingestStatus, setIngestStatus] = useState<IngestStatus | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    setErr(null);
    try {
      const [r1, r2, r3] = await Promise.all([
        fetch(bridgeUrl("internal/stats/export-readiness"), { cache: "no-store" }),
        fetch(bridgeUrl("internal/stats/scoring-summary"), { cache: "no-store" }),
        fetch(bridgeUrl("internal/stats/ingest-status"), { cache: "no-store" }),
      ]);
      if (!r1.ok) throw new Error(`export-readiness ${r1.status}`);
      if (!r2.ok) throw new Error(`scoring-summary ${r2.status}`);
      if (!r3.ok) throw new Error(`ingest-status ${r3.status}`);
      const j1 = await r1.json();
      const j2 = await r2.json();
      const j3 = await r3.json();
      setReadiness(j1);
      setSummary(j2);
      if (isIngestStatus(j3)) setIngestStatus(j3);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      if (cancelled) return;
      await load();
    };
    void tick();
    const timer = window.setInterval(() => void tick(), 60_000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [load]);

  const showBanner =
    ingestStatus &&
    ingestStatus.phase !== "idle" &&
    (ingestStatus.phase === "ingesting" ||
      ingestStatus.phase === "ingest_pending" ||
      ingestStatus.phase === "scoring_backlog");

  return (
    <main>
      <h1>Operator overview</h1>
      <div className="status-banner status-banner--scope" role="note">
        <strong>Pilot geography (current restrictions)</strong>
        <p style={{ margin: "0.35rem 0" }}>
          {isScoringSummary(summary) && summary.pilot_region ? (
            <span>{summary.pilot_region} · </span>
          ) : null}
          All counts, parcel lists, and outreach views on this console are limited to{" "}
          <strong>in-scope</strong> parcels only — not all of King County or Washington State.
        </p>
        <ul className="scope-list">
          <li>
            <strong>Included:</strong> City of Kent (city limits) plus unincorporated King County land in the pilot
            area (outside other cities&apos; boundaries).
          </li>
          <li>
            <strong>Excluded:</strong> Seattle, Bellevue, Renton, Federal Way, and other incorporated King County
            cities (except Kent). Parcels outside the pilot may still exist in the database from earlier samples but
            are hidden from default views.
          </li>
          <li>
            <strong>County:</strong> King County, Washington (FIPS 53033) — no statewide ingest in this pilot.
          </li>
        </ul>
      </div>
      <p className="muted">
        Readiness gaps and scoring totals below reflect in-scope parcels only. Public parcel detail pages use the
        browser-facing API.
      </p>

      {err ? <div className="error">{err}</div> : null}

      {showBanner && ingestStatus ? (
        <div
          className={`status-banner status-banner--${
            ingestStatus.phase === "ingesting"
              ? "ingesting"
              : ingestStatus.phase === "ingest_pending"
                ? "warning"
                : "scoring"
          }`}
          role="status"
        >
          <strong>{ingestStatus.headline}</strong>
          <p>{ingestStatus.detail}</p>
          {ingestStatus.candidate_feature_count != null && ingestStatus.phase === "ingesting" ? (
            <p className="muted" style={{ marginBottom: 0 }}>
              Target after load: ~{ingestStatus.candidate_feature_count.toLocaleString()} in-scope candidates · currently{" "}
              {ingestStatus.parcels_in_scope_db.toLocaleString()} in DB
            </p>
          ) : null}
          {ingestStatus.phase === "scoring_backlog" ? (
            <p className="muted" style={{ marginBottom: 0 }}>
              Entitlement scored: {ingestStatus.parcels_with_entitlement_score.toLocaleString()} /{" "}
              {ingestStatus.parcels_in_scope_db.toLocaleString()}
            </p>
          ) : null}
        </div>
      ) : null}

      <div className="cols" style={{ marginTop: "1rem" }}>
        {isScoringSummary(summary) ? (
          <>
            <div className="stat">
              <div className="muted">Parcels in DB</div>
              <div className="n">{String(summary.total_parcels)}</div>
              {ingestStatus?.phase === "ingesting" ? (
                <div className="stat-note">Updates when load finishes</div>
              ) : null}
            </div>
            <div className="stat">
              <div className="muted">With entitlement score</div>
              <div className="n">{String(summary.parcels_with_latest_entitlement_score)}</div>
              <div className="stat-note">Atlas · full pipeline</div>
              {ingestStatus?.phase === "ingesting" ? (
                <div className="stat-note">Fills in after load</div>
              ) : null}
            </div>
            <div className="stat">
              <div className="muted">With strategic score</div>
              <div className="n">{String(summary.parcels_with_latest_strategic_score)}</div>
              <div className="stat-note">Beacon · full pipeline</div>
            </div>
            <div className="stat">
              <div className="muted">With identification score</div>
              <div className="n">{String(summary.parcels_with_latest_identification_score)}</div>
              <div className="stat-note">Cartographer · at ingest</div>
            </div>
          </>
        ) : (
          !err && <p className="muted">Loading scoring summary…</p>
        )}
      </div>

      <OperationsModelPanel />

      <ScoringMethodologyPanel variant="compact" />

      <h2>Export readiness (JSON)</h2>
      <div className="panel">
        {readiness ? <pre className="json">{JSON.stringify(readiness, null, 2)}</pre> : !err ? <p className="muted">Loading…</p> : null}
      </div>

      <h2>Outreach candidates</h2>
      <p className="muted">
        See <Link href="/outreach">Outreach pipeline</Link> for dual-qualified parcels (entitlement + strategic floors),
        or <Link href="/deals">Deal progress</Link> for all parcels grouped by operator-friendly deal stage.
      </p>

      <h2>Agent ↔ owner “conversations”</h2>
      <div className="panel">
        <p className="muted" style={{ marginTop: 0 }}>
          Structured outreach lives on each parcel as <code>owner_outreach_brief</code> (see Parcels → detail). Automated
          Atlas/Beacon discussions post to <strong>Slack</strong> when configured — this console does not ingest Slack
          history yet.
        </p>
      </div>

      <PilotDataFunnel />
    </main>
  );
}
