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
import { countyLine, useCountyNames } from "../../../lib/useCountyNames";
import { tierBadgeClass, tierLabel, symbolHint } from "../../../lib/zoningEntitlement";
import { canMutate, useAuth } from "../../../lib/useAuth";

type Parcel = {
  id: string;
  apn: string;
  county_fips: string;
  lot_sqft: number | null;
  zoning_code: string | null;
  zoning_allows_surface_parking: boolean;
  zoning_principal_use_symbol: string | null;
  zoning_entitlement_tier: string | null;
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
  breakdown: {
    zoning_component?: number;
    lot_size_component?: number;
    corner_component?: number;
    demand_proximity_component?: number;
    parking_market_component?: number;
    notes?: string[];
  };
  pilot_snapshot?: {
    parking_rate_comp_count?: number;
    parking_rate_comps_used?: Array<{ name: string; hourly_mid_usd: number }>;
  };
  created_at: string;
};

type DealContext = {
  rate_comps: Array<{
    name: string;
    hourly_mid_usd: number;
    effective_hourly_usd?: number | null;
    origin: string;
    source_note: string | null;
    distance_m?: number | null;
    facility_type?: string | null;
    similarity?: number | null;
    comp_weight?: number | null;
  }>;
  revenue_estimate: {
    available: boolean;
    monthly_gross_usd?: number;
    monthly_gross_low_usd?: number;
    monthly_gross_high_usd?: number;
    annual_gross_usd?: number;
    hourly_rate_median_usd?: number;
    hourly_rate_weighted_usd?: number;
    stalls_estimated?: number;
    stalls_low?: number;
    stalls_high?: number;
    layout_efficiency?: number;
    usable_sqft?: number;
    comp_count?: number;
    reason?: string;
  };
  nearby_qualified_parcels: Array<{
    parcel_id: string;
    apn: string;
    entitlement_score: number;
    distance_m: number | null;
    lot_sqft: number | null;
  }>;
  rate_comp_radius_m: number;
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
  const countyLabel = useCountyNames();
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
  const [dealContext, setDealContext] = useState<DealContext | null>(null);
  const [dealErr, setDealErr] = useState<string | null>(null);

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
        const dc = await fetch(bridgeUrl(`parcels/${id}/deal-context`), { cache: "no-store" });
        if (dc.ok) {
          const ctx = (await dc.json()) as DealContext;
          if (!cancelled) setDealContext(ctx);
        } else if (!cancelled) {
          setDealErr(`Deal context unavailable (${dc.status})`);
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
  const latestRun = runs[0] ?? null;

  const nextStepHint = useMemo(() => {
    if (!parcel) return null;
    if (!latestRun) return "No pipeline run yet — top-scoring qualified parcels are enqueued automatically every few hours.";
    if (latestRun.status === "failed") return "Pipeline failed — check the error below or retry from ops.";
    if (latestRun.status === "running") return `Processing: ${latestRun.current_step?.replaceAll("_", " ") ?? "in progress"}…`;
    if (!parcel.owner_outreach_brief) return "Pipeline running or brief not ready — owner enrichment may still be in progress.";
    if (drafts.length === 0) return "Brief ready — message drafts will appear when templates and contacts are available.";
    return "Review message drafts below, then request counsel approval before anything is sent.";
  }, [parcel, latestRun, drafts.length]);

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
    <div className="page-content">
      <header className="app-page-meta" style={{ marginBottom: "1rem" }}>
        <nav className="breadcrumbs" aria-label="Breadcrumb">
          <span className="breadcrumb-item">
            <Link href="/">Home</Link>
          </span>
          <span className="breadcrumb-item">
            <span className="breadcrumb-sep">›</span>
            <Link href="/parcels">Parcels</Link>
          </span>
          <span className="breadcrumb-item">
            <span className="breadcrumb-sep">›</span>
            <span aria-current="page">{parcel?.apn ?? "Parcel"}</span>
          </span>
        </nav>
        <h1 className="app-page-title">{parcel ? parcel.apn : "Parcel detail"}</h1>
        <p className="app-page-purpose muted">
          Scores, parking market context, owner research, workflow, and outreach drafts — then{" "}
          <Link href="/approvals">Approvals</Link> before anything sends.
        </p>
      </header>

      {err ? <div className="error">{err}</div> : null}

      {parcel && nextStepHint ? (
        <div className="panel panel-inset next-step-panel">
          <strong>What happens next</strong>
          <p className="muted" style={{ margin: "0.35rem 0 0" }}>
            {nextStepHint}
          </p>
        </div>
      ) : null}

      {parcel ? (
        <div className="platform-deliverables parcel-deliverables">
          <div className={`platform-deliverable ${score ? "deliverable-done" : ""}`}>
            <strong>Atlas score</strong>
            <p className="muted">{score ? score.total_score.toFixed(1) : "Not yet scored"}</p>
          </div>
          <div className={`platform-deliverable ${parcel.owner_outreach_brief ? "deliverable-done" : ""}`}>
            <strong>Owner brief</strong>
            <p className="muted">{parcel.owner_outreach_brief ? "Produced" : "Pending enrichment"}</p>
          </div>
          <div className={`platform-deliverable ${dealContext?.revenue_estimate.available ? "deliverable-done" : ""}`}>
            <strong>Revenue model</strong>
            <p className="muted">
              {dealContext?.revenue_estimate.available
                ? `$${dealContext.revenue_estimate.monthly_gross_usd?.toLocaleString()}/mo est.`
                : "Needs comps + lot size"}
            </p>
          </div>
          <div className={`platform-deliverable ${drafts.length > 0 ? "deliverable-done" : ""}`}>
            <strong>Outreach drafts</strong>
            <p className="muted">{drafts.length > 0 ? `${drafts.length} channels` : "After brief + templates"}</p>
          </div>
          <div className={`platform-deliverable ${runs.some((r) => r.status === "completed") ? "deliverable-done" : ""}`}>
            <strong>Pipeline</strong>
            <p className="muted">
              {runs.length === 0 ? "Not started" : runs[0]?.status.replaceAll("_", " ") ?? "—"}
            </p>
          </div>
        </div>
      ) : null}

      {parcel ? (
        <>
          <div className="panel">
            <div className="row">
              <div>
                <strong>{parcel.apn}</strong>
                <span className="muted" style={{ marginLeft: "0.5rem" }}>
                  {countyLine(countyLabel, parcel.county_fips)}
                </span>
              </div>
              <span className="badge">{parcel.id}</span>
            </div>
            <div className="row">
              <span className="muted">Zoning</span>
              <span>
                {parcel.zoning_code ?? "—"}
                {parcel.zoning_entitlement_tier ? (
                  <span className={tierBadgeClass(parcel.zoning_entitlement_tier)} style={{ marginLeft: "0.5rem" }}>
                    {tierLabel(parcel.zoning_entitlement_tier)}
                  </span>
                ) : null}
              </span>
            </div>
            {parcel.zoning_principal_use_symbol ? (
              <div className="row">
                <span className="muted">Entitlement</span>
                <span className="muted">{symbolHint(parcel.zoning_principal_use_symbol)}</span>
              </div>
            ) : null}
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
              <>
                <p>
                  Latest <strong>entitlement</strong>: {score.total_score.toFixed(1)}{" "}
                  <span className="muted">({score.created_at?.slice(0, 19)})</span>
                </p>
                <div className="row">
                  <span className="muted">Zoning</span>
                  <span>{score.breakdown?.zoning_component ?? "—"}</span>
                </div>
                <div className="row">
                  <span className="muted">Lot size</span>
                  <span>{score.breakdown?.lot_size_component ?? "—"}</span>
                </div>
                <div className="row">
                  <span className="muted">Corner</span>
                  <span>{score.breakdown?.corner_component ?? "—"}</span>
                </div>
                <div className="row">
                  <span className="muted">Demand proximity</span>
                  <span>{score.breakdown?.demand_proximity_component ?? "—"}</span>
                </div>
                <div className="row">
                  <span className="muted">Parking market</span>
                  <span>
                    {(score.breakdown?.parking_market_component ?? 0).toFixed(1)}
                    {score.pilot_snapshot?.parking_rate_comp_count != null ? (
                      <span className="muted">
                        {" "}
                        · {score.pilot_snapshot.parking_rate_comp_count} nearby comp
                        {score.pilot_snapshot.parking_rate_comp_count === 1 ? "" : "s"}
                      </span>
                    ) : null}
                  </span>
                </div>
              </>
            ) : (
              <p className="muted">{scoreErr ?? "No score loaded."}</p>
            )}
          </div>

          <h2>Parking market context</h2>
          <p className="muted">
            Illustrative revenue from distance- and similarity-weighted nearby comps, plus a layout-based stall
            estimate — not a formal pro forma.
          </p>
          <div className="panel">
            {dealErr ? <p className="muted">{dealErr}</p> : null}
            {dealContext ? (
              <>
                {dealContext.revenue_estimate.available ? (
                  <>
                    <p>
                      Illustrative gross revenue:{" "}
                      <strong>${dealContext.revenue_estimate.monthly_gross_usd?.toLocaleString()}/mo</strong>
                      {dealContext.revenue_estimate.monthly_gross_low_usd != null &&
                      dealContext.revenue_estimate.monthly_gross_high_usd != null ? (
                        <span className="muted">
                          {" "}
                          (range ${dealContext.revenue_estimate.monthly_gross_low_usd.toLocaleString()}–$
                          {dealContext.revenue_estimate.monthly_gross_high_usd.toLocaleString()}/mo)
                        </span>
                      ) : null}{" "}
                      · ${dealContext.revenue_estimate.annual_gross_usd?.toLocaleString()}/yr
                    </p>
                    <p className="muted" style={{ marginTop: 0 }}>
                      ~
                      {dealContext.revenue_estimate.stalls_low ?? dealContext.revenue_estimate.stalls_estimated}–
                      {dealContext.revenue_estimate.stalls_high ?? dealContext.revenue_estimate.stalls_estimated} stalls
                      (mid {dealContext.revenue_estimate.stalls_estimated}
                      {dealContext.revenue_estimate.usable_sqft
                        ? ` on ~${Math.round(dealContext.revenue_estimate.usable_sqft).toLocaleString()} developable sqft`
                        : ""}
                      ) · weighted rate $
                      {dealContext.revenue_estimate.hourly_rate_weighted_usd ??
                        dealContext.revenue_estimate.hourly_rate_median_usd}
                      /hr
                      {dealContext.revenue_estimate.hourly_rate_median_usd != null &&
                      dealContext.revenue_estimate.hourly_rate_weighted_usd != null &&
                      dealContext.revenue_estimate.hourly_rate_weighted_usd !==
                        dealContext.revenue_estimate.hourly_rate_median_usd ? (
                        <span> (median ${dealContext.revenue_estimate.hourly_rate_median_usd}/hr)</span>
                      ) : null}{" "}
                      · {dealContext.revenue_estimate.comp_count} comps within {dealContext.rate_comp_radius_m}m
                    </p>
                  </>
                ) : (
                  <p className="muted">
                    Revenue estimate unavailable ({dealContext.revenue_estimate.reason ?? "add rate comps"}).
                  </p>
                )}
                {dealContext.rate_comps.length > 0 ? (
                  <table className="data" style={{ marginBottom: "0.75rem" }}>
                    <thead>
                      <tr>
                        <th>Comp</th>
                        <th>Rate</th>
                        <th>Distance</th>
                        <th>Type</th>
                        <th>Match</th>
                      </tr>
                    </thead>
                    <tbody>
                      {dealContext.rate_comps.slice(0, 8).map((c) => (
                        <tr key={`${c.name}-${c.distance_m ?? 0}`}>
                          <td>{c.name}</td>
                          <td>
                            ${(c.effective_hourly_usd ?? c.hourly_mid_usd).toFixed(2)}/hr
                            {c.effective_hourly_usd != null && c.effective_hourly_usd !== c.hourly_mid_usd ? (
                              <span className="muted"> (listed ${c.hourly_mid_usd})</span>
                            ) : null}
                          </td>
                          <td>{c.distance_m != null ? `${Math.round(c.distance_m)} m` : "—"}</td>
                          <td>{c.facility_type ?? "—"}</td>
                          <td>{c.comp_weight != null ? `${Math.round(c.comp_weight * 100)}%` : "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : null}
                <strong>Nearby qualified parcels</strong>
                {dealContext.nearby_qualified_parcels.length === 0 ? (
                  <p className="muted">None within radius (or missing footprint).</p>
                ) : (
                  <table className="data">
                    <thead>
                      <tr>
                        <th>APN</th>
                        <th>Score</th>
                        <th>Distance</th>
                        <th></th>
                      </tr>
                    </thead>
                    <tbody>
                      {dealContext.nearby_qualified_parcels.map((n) => (
                        <tr key={n.parcel_id}>
                          <td>{n.apn}</td>
                          <td>{n.entitlement_score.toFixed(1)}</td>
                          <td>{n.distance_m != null ? `${n.distance_m} m` : "—"}</td>
                          <td>
                            <Link href={`/parcels/${n.parcel_id}`}>Open</Link>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </>
            ) : (
              <p className="muted">Loading market context…</p>
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

          <h2>Owner outreach brief</h2>
          <p className="muted">
            Structured output from the enrichment pipeline — owner candidates, contacts, skip trace, and research tier.
          </p>
          <div className="panel">
            {parcel.owner_outreach_brief ? (
              <details className="brief-details">
                <summary>View structured brief (JSON)</summary>
                <pre className="json">{JSON.stringify(parcel.owner_outreach_brief, null, 2)}</pre>
              </details>
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
    </div>
  );
}
