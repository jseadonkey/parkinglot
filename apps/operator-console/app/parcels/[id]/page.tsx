"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { bridgeUrl } from "../../../lib/paths";
import {
  outcomeBadgeClass,
  outcomeLabel,
  parseSkipTraceView,
  skipTraceRan,
} from "../../../lib/skipTraceDisplay";
import { canMutate, useAuth } from "../../../lib/useAuth";

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

type OutreachDraft = {
  channel: string;
  template_slug: string;
  to_name: string | null;
  to_email: string | null;
  to_phone: string | null;
  to_mailing_address: string | null;
  subject: string | null;
  body: string;
  has_recipient: boolean;
};

const DRAFT_LABELS: Record<string, string> = {
  email: "Email",
  sms: "Text",
  phone: "Voice",
  certified_mail: "Mail",
};

export default function ParcelDetailPage() {
  const auth = useAuth();
  const allowActions = canMutate(auth);
  const params = useParams();
  const id = typeof params.id === "string" ? params.id : "";
  const [parcel, setParcel] = useState<Parcel | null>(null);
  const [runs, setRuns] = useState<WorkflowRun[]>([]);
  const [score, setScore] = useState<Score | null>(null);
  const [scoreErr, setScoreErr] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<OutreachDraft[]>([]);
  const [draftErr, setDraftErr] = useState<string | null>(null);
  const [draftChannel, setDraftChannel] = useState("email");
  const [requestActor, setRequestActor] = useState("operator@example.com");
  const [approvalMsg, setApprovalMsg] = useState<string | null>(null);
  const [requesting, setRequesting] = useState(false);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    (async () => {
      setErr(null);
      try {
        const [rp, rr] = await Promise.all([
          fetch(bridgeUrl(`parcels/${id}`), { cache: "no-store" }),
          fetch(bridgeUrl(`parcels/${id}/workflow-runs?limit=20`), { cache: "no-store" }),
        ]);
        if (!rp.ok) throw new Error(`parcel ${rp.status}`);
        if (!rr.ok) throw new Error(`workflow-runs ${rr.status}`);
        const p = (await rp.json()) as Parcel;
        const w = (await rr.json()) as WorkflowRun[];
        if (!cancelled) {
          setParcel(p);
          setRuns(w);
        }
        const rs = await fetch(bridgeUrl(`parcels/${id}/score?profile=entitlement`), { cache: "no-store" });
        if (rs.ok) {
          const s = (await rs.json()) as Score;
          if (!cancelled) setScore(s);
        } else {
          if (!cancelled) setScoreErr(`No entitlement score (${rs.status})`);
        }
        if (p.owner_outreach_brief) {
          const rd = await fetch(bridgeUrl(`parcels/${id}/outreach/drafts`), { cache: "no-store" });
          if (rd.ok) {
            const d = (await rd.json()) as OutreachDraft[];
            if (!cancelled) {
              setDrafts(d);
              if (d.length > 0) {
                setDraftChannel((prev) => (d.some((x) => x.channel === prev) ? prev : d[0].channel));
              }
            }
          } else if (!cancelled) {
            setDraftErr(`Message drafts unavailable (${rd.status})`);
          }
        }
      } catch (e) {
        if (!cancelled) setErr(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [id]);

  const activeDraft = drafts.find((d) => d.channel === draftChannel) ?? drafts[0] ?? null;
  const skipTrace = useMemo(() => parseSkipTraceView(parcel?.owner_outreach_brief), [parcel?.owner_outreach_brief]);

  async function requestApproval(channel: string) {
    if (!allowActions || !id) return;
    setApprovalMsg(null);
    setRequesting(true);
    try {
      const res = await fetch(bridgeUrl(`parcels/${id}/outreach/drafts/${channel}/request-approval`), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ requested_by: requestActor }),
      });
      if (res.status === 409) {
        setApprovalMsg("Already pending approval for this channel — check Approvals.");
        return;
      }
      if (!res.ok) {
        const detail = await res.text();
        setApprovalMsg(`Request failed (${res.status}): ${detail}`);
        return;
      }
      setApprovalMsg("Sent to approvals queue for counsel review.");
    } finally {
      setRequesting(false);
    }
  }

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

          <h2>Skip trace &amp; owner lookup</h2>
          <p className="muted">
            Licensed vendor skip-trace runs during the enrichment pipeline and is stored on the outreach brief as{" "}
            <code>vendor_lookup</code>. Assessor-roll contacts come from county ingest only.
          </p>
          <div className="panel">
            {!skipTrace.hasBrief ? (
              <p className="muted">No outreach brief yet — run the pipeline to record owner research and skip trace.</p>
            ) : (
              <>
                {skipTrace.recordedOwner ? (
                  <div className="row">
                    <span className="muted">Recorded owner</span>
                    <span>{skipTrace.recordedOwner}</span>
                  </div>
                ) : null}
                {skipTrace.researchTier ? (
                  <div className="row">
                    <span className="muted">Research tier</span>
                    <span className="badge">{skipTrace.researchTier}</span>
                  </div>
                ) : null}
                {skipTrace.computedAt ? (
                  <div className="row">
                    <span className="muted">Brief computed</span>
                    <span className="muted">{skipTrace.computedAt.slice(0, 19).replace("T", " ")} UTC</span>
                  </div>
                ) : null}

                {skipTrace.vendor ? (
                  <>
                    <div className="row">
                      <span className="muted">Skip trace status</span>
                      <span>
                        <span className={`badge ${outcomeBadgeClass(skipTrace.vendor.outcome)}`}>
                          {skipTraceRan(skipTrace) ? "Completed" : skipTrace.vendor.outcome.replaceAll("_", " ")}
                        </span>
                      </span>
                    </div>
                    <div className="row">
                      <span className="muted">Outcome</span>
                      <span>{outcomeLabel(skipTrace.vendor.outcome)}</span>
                    </div>
                    <div className="row">
                      <span className="muted">Provider</span>
                      <span>
                        {skipTrace.vendor.provider}
                        {skipTrace.vendor.http_status != null ? (
                          <span className="muted"> · HTTP {skipTrace.vendor.http_status}</span>
                        ) : null}
                      </span>
                    </div>
                    {skipTrace.vendor.notes ? (
                      <div className="row">
                        <span className="muted">Notes</span>
                        <span>{skipTrace.vendor.notes}</span>
                      </div>
                    ) : null}
                    {skipTrace.vendor.error_detail ? (
                      <div className="row">
                        <span className="muted">Error</span>
                        <span className="error">{skipTrace.vendor.error_detail}</span>
                      </div>
                    ) : null}

                    {skipTrace.vendor.contacts.length > 0 ? (
                      <>
                        <h3 style={{ marginTop: "1rem", fontSize: "0.95rem" }}>Skip-trace contacts (vendor)</h3>
                        <table className="data">
                          <thead>
                            <tr>
                              <th>Channel</th>
                              <th>Value</th>
                              <th>Label</th>
                            </tr>
                          </thead>
                          <tbody>
                            {skipTrace.vendor.contacts.map((c, i) => (
                              <tr key={`${c.channel}-${c.value}-${i}`}>
                                <td>{c.channel}</td>
                                <td>{c.value}</td>
                                <td className="muted">{c.label ?? "—"}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </>
                    ) : skipTraceRan(skipTrace) ? (
                      <p className="muted" style={{ marginTop: "0.75rem" }}>
                        Skip trace completed but the vendor returned no contact rows.
                      </p>
                    ) : null}
                  </>
                ) : (
                  <p className="muted" style={{ marginTop: "0.5rem" }}>
                    No <code>vendor_lookup</code> block on this brief — skip trace was not recorded for this parcel.
                  </p>
                )}

                {skipTrace.rollContacts.length > 0 ? (
                  <>
                    <h3 style={{ marginTop: "1rem", fontSize: "0.95rem" }}>Assessor-roll contacts (ingest)</h3>
                    <table className="data">
                      <thead>
                        <tr>
                          <th>Kind</th>
                          <th>Value</th>
                          <th>Source</th>
                        </tr>
                      </thead>
                      <tbody>
                        {skipTrace.rollContacts.map((c, i) => (
                          <tr key={`${c.kind}-${c.value}-${i}`}>
                            <td>{c.kind}</td>
                            <td>{c.value}</td>
                            <td className="muted">{c.source ?? "—"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </>
                ) : null}
              </>
            )}
          </div>

          <h2>Owner outreach brief (full JSON)</h2>
          <p className="muted">
            Complete structured brief from the pipeline. For agent chat logs, check Slack.
          </p>
          <div className="panel">
            {parcel.owner_outreach_brief ? (
              <pre className="json">{JSON.stringify(parcel.owner_outreach_brief, null, 2)}</pre>
            ) : (
              <p className="muted">No brief yet — run pipeline / Phase C enrichment.</p>
            )}
          </div>

          <h2>Message drafts</h2>
          <p className="muted">
            Rendered from admin templates using this parcel&apos;s owner data.{" "}
            <Link href="/templates">Edit default templates</Link>
          </p>
          {draftErr ? <div className="error">{draftErr}</div> : null}
          {drafts.length > 0 && activeDraft ? (
            <div className="panel">
              <div className="template-tabs" role="tablist" aria-label="Outreach channels">
                {drafts.map((d) => (
                  <button
                    key={d.channel}
                    type="button"
                    role="tab"
                    aria-selected={d.channel === draftChannel}
                    className={d.channel === draftChannel ? "template-tab-pill active" : "template-tab-pill"}
                    onClick={() => setDraftChannel(d.channel)}
                  >
                    {DRAFT_LABELS[d.channel] ?? d.channel}
                    {!d.has_recipient ? " · no recipient" : ""}
                  </button>
                ))}
              </div>
              <div className="muted" style={{ marginTop: "0.85rem", fontSize: "0.85rem" }}>
                {activeDraft.to_email ? (
                  <div>
                    To: {activeDraft.to_name ?? "—"} &lt;{activeDraft.to_email}&gt;
                  </div>
                ) : null}
                {activeDraft.to_phone ? <div>To phone: {activeDraft.to_phone}</div> : null}
                {activeDraft.to_mailing_address ? <div>To mail: {activeDraft.to_mailing_address}</div> : null}
                {!activeDraft.has_recipient ? (
                  <div>No {DRAFT_LABELS[activeDraft.channel]?.toLowerCase() ?? activeDraft.channel} on file for this parcel.</div>
                ) : null}
              </div>
              {activeDraft.subject ? (
                <div style={{ marginTop: "0.75rem" }}>
                  <span className="muted">Subject: </span>
                  {activeDraft.subject}
                </div>
              ) : null}
              <pre className="preview-body">{activeDraft.body}</pre>
              {allowActions && activeDraft.has_recipient ? (
                <div className="toolbar-row" style={{ marginTop: "1rem" }}>
                  <label className="toolbar-field">
                    <span className="muted">Request as</span>
                    <input
                      value={requestActor}
                      onChange={(e) => setRequestActor(e.target.value)}
                      placeholder="name@company.com"
                    />
                  </label>
                  <button
                    type="button"
                    className="primary"
                    disabled={requesting}
                    onClick={() => void requestApproval(activeDraft.channel)}
                  >
                    {requesting ? "Submitting…" : "Request approval to send"}
                  </button>
                  <Link href="/approvals" className="btn-link">
                    View approvals
                  </Link>
                </div>
              ) : null}
              {approvalMsg ? <div className={approvalMsg.startsWith("Sent") ? "success" : "error"}>{approvalMsg}</div> : null}
            </div>
          ) : parcel.owner_outreach_brief && !draftErr ? (
            <p className="muted">Loading message drafts…</p>
          ) : null}
        </>
      ) : !err ? (
        <p className="muted">Loading…</p>
      ) : null}
    </main>
  );
}
