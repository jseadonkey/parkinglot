"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { DetailRow } from "../../../components/DetailRow";
import { FieldLabel } from "../../../components/FieldLabel";
import { OwnerRecordPanel, type OwnerRecord } from "../../../components/OwnerRecordPanel";
import {
  FIELD_HELP,
  demandProximityNote,
  formatCompRate,
  formatDistanceMeters,
  parkingCompNote,
  zoningDetailHint,
} from "../../../lib/parcelFieldHelp";
import { SCORE_PROFILE_BY_ID, type ScoreProfileId } from "../../../lib/scoringMethodology";

type ScoreBreakdown = {
  zoning_component?: number;
  lot_size_component?: number;
  corner_component?: number;
  demand_proximity_component?: number;
  notes?: string[];
};

type Score = {
  id: string;
  score_profile: string;
  total_score: number;
  breakdown: ScoreBreakdown;
  pilot_snapshot: Record<string, unknown> | null;
  created_at: string;
};

type Owner = {
  id: string;
  display_name: string;
  kind: string;
  confidence: number;
  source: string;
  normalized_owner_key: string | null;
  created_at: string;
};

type Memo = {
  id: string;
  title: string;
  body_md: string;
  open_questions: unknown[] | null;
  created_at: string;
};

type Contract = {
  id: string;
  s3_key: string;
  version: number;
  created_at: string;
};

type Approval = {
  id: string;
  type: string;
  status: string;
  payload: Record<string, unknown>;
  approved_by: string | null;
  created_at: string;
};

type WorkflowRun = {
  id: string;
  status: string;
  current_step: string | null;
  error: string | null;
  created_at: string;
  updated_at: string;
};

type Qualification = {
  meets_entitlement_floor: boolean;
  meets_strategic_floor: boolean;
  dual_qualified: boolean;
  qualified_min_entitlement: number;
  qualified_min_strategic: number;
  latest_entitlement_score: number | null;
  latest_strategic_score: number | null;
};

type ParcelDetail = {
  id: string;
  apn: string;
  county_fips: string;
  lot_sqft: number | null;
  zoning_code: string | null;
  zoning_allows_surface_parking: boolean;
  is_corner_lot: boolean;
  distance_to_nearest_demand_m: number | null;
  distance_to_nearest_comp_parking_m: number | null;
  nearest_parking_comp: {
    id?: string;
    name?: string;
    kind?: string;
    rate_usd_per_day?: number;
    rate_usd_per_hour?: number;
    distance_m?: number;
    notes?: string;
  } | null;
  pilot_in_scope: boolean;
  has_footprint: boolean;
  centroid_lat: number | null;
  centroid_lon: number | null;
  owner_outreach_brief: Record<string, unknown> | null;
  raw_properties: Record<string, unknown> | null;
  assessor_summary: Record<string, string>;
  created_at: string;
  pilot_region: string;
  qualification: Qualification;
  scores: Score[];
  owners: Owner[];
  memos: Memo[];
  contract_drafts: Contract[];
  approvals: Approval[];
  workflow_runs: WorkflowRun[];
  owner_record: OwnerRecord;
};

const SCORE_META: Record<string, { label: string; floor: number; help: string }> = {
  entitlement: {
    label: SCORE_PROFILE_BY_ID.entitlement.title,
    floor: SCORE_PROFILE_BY_ID.entitlement.floor,
    help: FIELD_HELP.entitlementScore,
  },
  strategic: {
    label: SCORE_PROFILE_BY_ID.strategic.title,
    floor: SCORE_PROFILE_BY_ID.strategic.floor,
    help: FIELD_HELP.strategicScore,
  },
  identification: {
    label: SCORE_PROFILE_BY_ID.identification.title,
    floor: SCORE_PROFILE_BY_ID.identification.floor,
    help: FIELD_HELP.identificationScore,
  },
};

const apiBase = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

function scoreByProfile(scores: Score[], profile: string): Score | undefined {
  return scores.find((s) => s.score_profile === profile);
}

function scoreIncompleteNote(profile: string, score: Score | undefined): string | null {
  if (!score) return null;
  const info = SCORE_PROFILE_BY_ID[profile as ScoreProfileId];
  if (!info?.incompleteWhen) return null;
  const snap = score.pilot_snapshot ?? {};
  const source = typeof snap.demand_signal_source === "string" ? snap.demand_signal_source : null;
  if (profile === "identification") return info.incompleteWhen;
  if (profile === "strategic" && (source === "poi" || source === "none" || score.breakdown?.demand_proximity_component === 0)) {
    return info.incompleteWhen;
  }
  return null;
}

function ScoreCard({ profile, score }: { profile: string; score: Score | undefined }) {
  const meta = SCORE_META[profile] ?? { label: profile, floor: 0, help: "" };
  const profileInfo = SCORE_PROFILE_BY_ID[profile as ScoreProfileId];
  const b = score?.breakdown ?? {};
  const meets = score != null && score.total_score >= meta.floor;
  const incompleteNote = scoreIncompleteNote(profile, score);
  return (
    <div className="score-card">
      <div className="score-head">
        <FieldLabel label={meta.label} help={meta.help} />
        <span>
          {score ? (
            <>
              <strong>{score.total_score.toFixed(1)}</strong>
              <span className="muted" style={{ marginLeft: "0.35rem" }}>
                / {meta.floor} floor
              </span>
              <span className="badge" style={{ marginLeft: "0.45rem" }}>
                {profile === "identification" ? "prescreen" : meets ? "meets floor" : "below floor"}
              </span>
            </>
          ) : (
            <span className="muted">not scored</span>
          )}
        </span>
      </div>
      {profileInfo ? (
        <p className="muted" style={{ margin: "0.35rem 0 0", fontSize: "0.78rem" }}>
          {profileInfo.agentLabel} · {profileInfo.whenComputed}
        </p>
      ) : null}
      {score ? (
        <>
          <p className="muted" style={{ margin: "0.35rem 0 0", fontSize: "0.78rem" }}>
            {score.created_at?.slice(0, 19)} UTC
          </p>
          <ul className="score-breakdown">
            <li>Zoning: {b.zoning_component ?? 0}</li>
            <li>Lot size: {b.lot_size_component ?? 0}</li>
            <li>Corner: {b.corner_component ?? 0}</li>
            <li>Market / demand proximity: {b.demand_proximity_component ?? 0}</li>
          </ul>
          {Array.isArray(b.notes) && b.notes.length > 0 ? (
            <ul className="score-breakdown">
              {b.notes.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
          ) : null}
          {incompleteNote ? <p className="score-incomplete-note">{incompleteNote}</p> : null}
          {score.pilot_snapshot ? (
            <details className="muted" style={{ marginTop: "0.35rem", fontSize: "0.75rem" }}>
              <summary>Pilot snapshot</summary>
              <pre className="json" style={{ maxHeight: 160 }}>
                {JSON.stringify(score.pilot_snapshot, null, 2)}
              </pre>
            </details>
          ) : null}
        </>
      ) : profileInfo ? (
        <p className="muted" style={{ marginTop: "0.5rem", fontSize: "0.78rem" }}>
          {profile === "entitlement" || profile === "strategic"
            ? "Runs when the scoring pipeline processes this parcel."
            : profileInfo.whenComputed}
        </p>
      ) : null}
    </div>
  );
}

function OutreachBriefPanel({ brief }: { brief: Record<string, unknown> }) {
  const tier = typeof brief.owner_research_tier === "string" ? brief.owner_research_tier : null;
  const oneLiner = typeof brief.recorded_owner_one_liner === "string" ? brief.recorded_owner_one_liner : null;
  const steps = Array.isArray(brief.steps) ? brief.steps : [];
  const gaps = Array.isArray(brief.data_gaps) ? (brief.data_gaps as string[]) : [];
  const checklist = Array.isArray(brief.manual_research_checklist)
    ? (brief.manual_research_checklist as string[])
    : [];

  return (
    <div className="panel">
      {tier ? (
        <p>
          <FieldLabel label="Owner research tier" help={FIELD_HELP.ownerTier} />:{" "}
          <span className="badge">{tier}</span>
        </p>
      ) : null}
      {oneLiner ? (
        <p>
          <strong>Recorded owner:</strong> {oneLiner}
        </p>
      ) : null}
      {typeof brief.mailing_address_guess === "string" && brief.mailing_address_guess ? (
        <p className="muted">Mailing: {brief.mailing_address_guess}</p>
      ) : null}
      {typeof brief.phone_guess === "string" && brief.phone_guess ? (
        <p className="muted">Phone (roll): {brief.phone_guess}</p>
      ) : null}
      {typeof brief.email_guess === "string" && brief.email_guess ? (
        <p className="muted">Email (roll): {brief.email_guess}</p>
      ) : null}
      {typeof brief.normalized_owner_key === "string" && brief.normalized_owner_key ? (
        <p className="muted">Owner key: {brief.normalized_owner_key}</p>
      ) : null}
      {typeof brief.same_owner_qualified_other_count === "number" && brief.same_owner_qualified_other_count > 0 ? (
        <p className="muted">
          Portfolio peers (same owner key, qualified): {brief.same_owner_qualified_other_count}
        </p>
      ) : null}
      {steps.length > 0 ? (
        <>
          <h3 style={{ fontSize: "0.9rem", margin: "0.75rem 0 0.35rem" }}>Suggested outreach steps</h3>
          <ol className="score-breakdown" style={{ paddingLeft: "1.2rem" }}>
            {steps.map((step, i) => {
              if (!step || typeof step !== "object") return null;
              const s = step as Record<string, unknown>;
              const title = typeof s.title === "string" ? s.title : `Step ${i + 1}`;
              const instruction = typeof s.instruction === "string" ? s.instruction : "";
              return (
                <li key={`${title}-${i}`}>
                  <strong>{title}</strong>
                  {instruction ? ` — ${instruction}` : ""}
                </li>
              );
            })}
          </ol>
        </>
      ) : null}
      {gaps.length > 0 ? (
        <>
          <h3 style={{ fontSize: "0.9rem", margin: "0.75rem 0 0.35rem" }}>Data gaps</h3>
          <ul className="score-breakdown">
            {gaps.map((g) => (
              <li key={g}>{g}</li>
            ))}
          </ul>
        </>
      ) : null}
      {checklist.length > 0 ? (
        <>
          <h3 style={{ fontSize: "0.9rem", margin: "0.75rem 0 0.35rem" }}>Manual research checklist</h3>
          <ul className="score-breakdown">
            {checklist.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
        </>
      ) : null}
      <details style={{ marginTop: "0.75rem" }}>
        <summary className="muted">Full brief JSON</summary>
        <pre className="json">{JSON.stringify(brief, null, 2)}</pre>
      </details>
    </div>
  );
}

export default function ParcelDetailPage() {
  const params = useParams();
  const id = typeof params.id === "string" ? params.id : "";
  const [detail, setDetail] = useState<ParcelDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    (async () => {
      setErr(null);
      try {
        const res = await fetch(`${apiBase}/parcels/${id}/detail`, { cache: "no-store" });
        if (!res.ok) throw new Error(`parcel detail ${res.status}`);
        const data = (await res.json()) as ParcelDetail;
        if (!cancelled) setDetail(data);
      } catch (e) {
        if (!cancelled) setErr(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [id]);

  const parcel = detail;
  const q = parcel?.qualification;
  const zoningHint = parcel
    ? zoningDetailHint(parcel.zoning_code, parcel.zoning_allows_surface_parking)
    : null;
  const demandHint = parcel ? demandProximityNote(parcel.distance_to_nearest_demand_m) : null;
  const compHint = parcel
    ? parkingCompNote(parcel.distance_to_nearest_comp_parking_m, parcel.nearest_parking_comp)
    : null;
  const assessorLink = parcel?.assessor_summary["County assessor link"];

  return (
    <main>
      <p className="muted">
        <Link href="/parcels">← Parcels</Link>
      </p>
      <h1>{parcel ? parcel.apn : "Parcel"}</h1>
      <p className="muted">Hover the ? next to any label for a plain-language definition.</p>

      {err ? <div className="error">{err}</div> : null}

      {parcel && q ? (
        <>
          <div
            className={`status-banner ${q.dual_qualified ? "status-banner--scoring" : parcel.pilot_in_scope ? "status-banner--ingesting" : "status-banner--warning"}`}
            role="status"
          >
            <strong>
              {q.dual_qualified
                ? "Dual-qualified for deal memo / outreach"
                : parcel.pilot_in_scope
                  ? "In pilot scope — below qualification floors"
                  : "Out of pilot scope"}
            </strong>
            <p style={{ margin: 0 }}>
              {parcel.pilot_region} · Entitlement{" "}
              {q.latest_entitlement_score != null ? q.latest_entitlement_score.toFixed(1) : "—"} (floor{" "}
              {q.qualified_min_entitlement}) · Strategic{" "}
              {q.latest_strategic_score != null ? q.latest_strategic_score.toFixed(1) : "—"} (floor{" "}
              {q.qualified_min_strategic})
            </p>
          </div>

          <h2>Location & zoning</h2>
          <div className="panel">
            <DetailRow label="Parcel ID" help="Internal database UUID." value={<span className="badge">{parcel.id}</span>} />
            <DetailRow label="APN" help={FIELD_HELP.apn} value={parcel.apn} />
            <DetailRow
              label="County"
              help={FIELD_HELP.countyFips}
              value={parcel.county_fips === "53033" ? "53033 (King County)" : parcel.county_fips}
            />
            <DetailRow
              label="Pilot in scope"
              help={FIELD_HELP.pilotInScope}
              value={<span className="badge">{parcel.pilot_in_scope ? "yes" : "no"}</span>}
            />
            <DetailRow
              label="Zoning code"
              help={FIELD_HELP.zoning}
              value={parcel.zoning_code ?? "—"}
              hint={zoningHint}
            />
            <DetailRow
              label="Lot size"
              help={FIELD_HELP.lotSqft}
              value={parcel.lot_sqft != null ? `${Math.round(parcel.lot_sqft).toLocaleString()} sqft` : "—"}
            />
            <DetailRow
              label="Demand distance (POI)"
              help={FIELD_HELP.demandDistance}
              value={formatDistanceMeters(parcel.distance_to_nearest_demand_m)}
              hint={demandHint}
            />
            <DetailRow
              label="Nearest parking comp"
              help={FIELD_HELP.parkingComp}
              value={
                parcel.nearest_parking_comp?.name
                  ? `${parcel.nearest_parking_comp.name} · ${formatDistanceMeters(parcel.distance_to_nearest_comp_parking_m)} · ${formatCompRate(parcel.nearest_parking_comp)}`
                  : formatDistanceMeters(parcel.distance_to_nearest_comp_parking_m)
              }
              hint={compHint}
            />
            <DetailRow label="Corner lot" help={FIELD_HELP.cornerLot} value={parcel.is_corner_lot ? "Yes" : "No"} />
            <DetailRow
              label="Surface parking allowed"
              help={FIELD_HELP.surfaceParking}
              value={
                <span className="badge">{parcel.zoning_allows_surface_parking ? "yes (rules file)" : "no / unknown"}</span>
              }
            />
            <DetailRow
              label="Footprint / centroid"
              help="Parcel polygon stored for scope and distance; centroid is map center."
              value={
                parcel.has_footprint && parcel.centroid_lat != null && parcel.centroid_lon != null
                  ? `${parcel.centroid_lat.toFixed(5)}, ${parcel.centroid_lon.toFixed(5)}`
                  : parcel.has_footprint
                    ? "yes (centroid unavailable)"
                    : "no geometry"
              }
            />
            <DetailRow label="Ingested at" help="When this row was first written to the database." value={parcel.created_at.slice(0, 19)} />
          </div>

          {Object.keys(parcel.assessor_summary).length > 0 ? (
            <>
              <h2>Assessor roll (from ingest)</h2>
              <div className="panel">
                {Object.entries(parcel.assessor_summary).map(([label, value]) => (
                  <DetailRow
                    key={label}
                    label={label}
                    help="Field from county assessor / WaTech parcel layer at ingest time."
                    value={
                      label === "County assessor link" && value.startsWith("http") ? (
                        <a href={value} target="_blank" rel="noreferrer">
                          Open in county portal
                        </a>
                      ) : (
                        value
                      )
                    }
                  />
                ))}
              </div>
            </>
          ) : null}

          <h2>Scores</h2>
          <p className="muted">
            Three independent 0–100 profiles. Only <strong>Atlas + Beacon</strong> together gate deal memos and
            outreach. Cartographer prescreen runs at ingest and may omit parking comp points until pipeline gates pass.
          </p>
          <div className="panel score-grid">
            {(["entitlement", "strategic", "identification"] as const).map((p) => (
              <ScoreCard key={p} profile={p} score={scoreByProfile(parcel.scores, p)} />
            ))}
          </div>

          <h2>Owners (enrichment)</h2>
          <div className="panel">
            {parcel.owners.length === 0 ? (
              <p className="muted">No owner candidates — run pipeline or check assessor roll fields.</p>
            ) : (
              <table className="data">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Kind</th>
                    <th>Confidence</th>
                    <th>Source</th>
                    <th>Owner key</th>
                  </tr>
                </thead>
                <tbody>
                  {parcel.owners.map((o) => (
                    <tr key={o.id}>
                      <td>{o.display_name}</td>
                      <td>{o.kind}</td>
                      <td>{o.confidence.toFixed(2)}</td>
                      <td className="muted">{o.source}</td>
                      <td className="muted">{o.normalized_owner_key ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          <h2>Owner outreach brief</h2>
          {parcel.owner_outreach_brief ? (
            <OutreachBriefPanel brief={parcel.owner_outreach_brief} />
          ) : (
            <div className="panel">
              <p className="muted">No brief yet — run pipeline / Phase C enrichment.</p>
            </div>
          )}

          <h2>Deal memos</h2>
          <div className="panel">
            {parcel.memos.length === 0 ? (
              <p className="muted">No deal memos — generated when entitlement and strategic scores both meet pilot floors.</p>
            ) : (
              parcel.memos.map((m) => (
                <div key={m.id} style={{ marginBottom: "1rem" }}>
                  <strong>{m.title}</strong>
                  <span className="muted" style={{ marginLeft: "0.5rem" }}>
                    {m.created_at.slice(0, 19)}
                  </span>
                  <pre className="json" style={{ maxHeight: 320, marginTop: "0.5rem" }}>
                    {m.body_md}
                  </pre>
                  {Array.isArray(m.open_questions) && m.open_questions.length > 0 ? (
                    <ul className="score-breakdown">
                      {(m.open_questions as string[]).map((oq) => (
                        <li key={oq}>{oq}</li>
                      ))}
                    </ul>
                  ) : null}
                </div>
              ))
            )}
          </div>

          <h2>Approvals</h2>
          <div className="panel">
            {parcel.approvals.length === 0 ? (
              <p className="muted">No approval requests for this parcel.</p>
            ) : (
              <table className="data">
                <thead>
                  <tr>
                    <th>Type</th>
                    <th>Status</th>
                    <th>Created</th>
                    <th>Approved by</th>
                  </tr>
                </thead>
                <tbody>
                  {parcel.approvals.map((a) => (
                    <tr key={a.id}>
                      <td>{a.type}</td>
                      <td>
                        <span className="badge">{a.status}</span>
                      </td>
                      <td className="muted">{a.created_at.slice(0, 19)}</td>
                      <td className="muted">{a.approved_by ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          <h2>Contract drafts</h2>
          <div className="panel">
            {parcel.contract_drafts.length === 0 ? (
              <p className="muted">No contract drafts stored for this parcel.</p>
            ) : (
              <table className="data">
                <thead>
                  <tr>
                    <th>Version</th>
                    <th>Storage key</th>
                    <th>Created</th>
                  </tr>
                </thead>
                <tbody>
                  {parcel.contract_drafts.map((c) => (
                    <tr key={c.id}>
                      <td>{c.version}</td>
                      <td className="muted">{c.s3_key}</td>
                      <td className="muted">{c.created_at.slice(0, 19)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          <h2>Workflow runs</h2>
          <div className="panel">
            {parcel.workflow_runs.length === 0 ? (
              <p className="muted">No workflow runs yet.</p>
            ) : (
              parcel.workflow_runs.map((r) => (
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

          {assessorLink && assessorLink.startsWith("http") ? (
            <p className="muted">
              <a href={assessorLink} target="_blank" rel="noreferrer">
                View on King County eReal Property →
              </a>
            </p>
          ) : null}

          {parcel.raw_properties && Object.keys(parcel.raw_properties).length > 0 ? (
            <>
              <h2>Raw ingest properties</h2>
              <div className="panel">
                <details>
                  <summary className="muted">Full assessor / WaTech JSON from ingest</summary>
                  <pre className="json">{JSON.stringify(parcel.raw_properties, null, 2)}</pre>
                </details>
              </div>
            </>
          ) : null}

          <OwnerRecordPanel record={parcel.owner_record} />
        </>
      ) : !err ? (
        <p className="muted">Loading…</p>
      ) : null}
    </main>
  );
}
