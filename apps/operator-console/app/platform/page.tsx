"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { platformShowcaseUrl } from "../../lib/paths";
import { formatStatesLabel } from "../../lib/marketScope";
import { countyLine, useCountyNames } from "../../lib/useCountyNames";

type SampleDeliverable = {
  kind: string;
  title: string;
  excerpt: string;
  parcel_apn: string;
  redacted: boolean;
};

type StateScope = { state_fips: string; state_name: string; county_count: number };

type Showcase = {
  generated_at: string;
  region_name: string;
  state_name: string;
  states_in_scope?: StateScope[];
  primary_market_name?: string;
  priority_county_fips?: string[];
  parcels_in_priority_counties?: number;
  primary_metro_label: string | null;
  pilot_county_count: number;
  counties_with_ingested_parcels: number;
  counties_loaded: Array<{
    county_fips: string;
    county_name: string;
    parcels_in_db: number;
    priority_market?: boolean;
  }>;
  parcels_total: number;
  parcels_prescreen_qualified: number;
  parcels_qualified_entitlement: number;
  parcels_with_full_pipeline_scores: number;
  parcels_with_owner_brief: number;
  parcels_pipeline_backlog: number;
  qualified_floors: { entitlement: number; strategic: number; identification: number };
  pipeline_runs_total: number;
  pipeline_by_stage: Record<string, number>;
  pipeline_by_step: Record<string, number>;
  top_parcels: Array<{
    parcel_id: string;
    apn: string;
    county_fips: string;
    entitlement_score: number | null;
    strategic_score: number | null;
    identification_score: number | null;
    lot_sqft: number | null;
    zoning_code: string | null;
    has_outreach_brief: boolean;
  }>;
  sample_deliverables?: SampleDeliverable[];
};

const PIPELINE_STAGES = [
  {
    id: "ingest",
    title: "County GIS ingest",
    body: "Parcels load from county GIS — Baltimore City EGIS (Maryland) and Washington assessor / WaTech layers — geometry, APN, zoning, lot size, and demand proximity.",
  },
  {
    id: "cartographer",
    title: "Cartographer prescreen",
    body: "Every parcel scored at ingest for surface-parking fit. Low scores never enter expensive enrichment — saving compute for real candidates.",
  },
  {
    id: "atlas",
    title: "Atlas entitlement",
    body: "Zoning, lot size, corner lot, and distance to demand POIs. Below the qualified floor → pipeline stops before owner research.",
  },
  {
    id: "beacon",
    title: "Beacon strategic",
    body: "Market and strategic fit on parcels Atlas already passed. Both agents must agree before enrichment runs.",
  },
  {
    id: "enrich",
    title: "Owner enrichment",
    body: "Assessor roll + licensed skip trace + state registry lookup + portfolio peers. Produces a structured owner outreach brief.",
  },
  {
    id: "deliver",
    title: "Deal package",
    body: "Deal memo, ground-lease contract draft, parking revenue context, and multi-channel outreach copy — email, text, voice, mail.",
  },
  {
    id: "human",
    title: "Counsel gate",
    body: "Nothing sends automatically. Memos, contracts, and outbound messages wait in Approvals for human sign-off.",
  },
] as const;

const AGENTS = [
  {
    codename: "Cartographer",
    role: "Identification prescreen",
    evaluates: "Zoning allows surface parking, minimum lot size, corner exposure, distance to hospitals/stadiums/transit demand generators.",
    when: "Runs on every parcel at GIS ingest — instant triage across loaded counties (King WA, Baltimore MD, and growing).",
  },
  {
    codename: "Atlas",
    role: "Entitlement scoring",
    evaluates: "Legal/planning feasibility — can this lot plausibly operate as paid parking given zoning and geometry?",
    when: "Full pipeline step 1. Failing score skips Beacon and all owner spend.",
  },
  {
    codename: "Beacon",
    role: "Strategic scoring",
    evaluates: "Market attractiveness — demand proximity, strategic weights from pilot config, combined ranking for outreach priority.",
    when: "Full pipeline step 2, only if Atlas passes the qualified floor.",
  },
] as const;

const DELIVERABLES = [
  {
    title: "Owner outreach brief",
    desc: "Ranked contact channels, research tier, skip-trace results, and compliance-aware next steps.",
  },
  {
    title: "Deal memo",
    desc: "Markdown investment narrative generated from scores, zoning, and market context.",
  },
  {
    title: "Contract draft",
    desc: "Ground-lease template populated and stored — ready for counsel review.",
  },
  {
    title: "Parking revenue model",
    desc: "Nearby garage comps + stall estimate → illustrative monthly/annual gross (PostGIS benchmarks).",
  },
  {
    title: "Multi-channel outreach",
    desc: "Email, SMS, voice script, and certified mail rendered from editable templates + owner data.",
  },
  {
    title: "Portfolio intelligence",
    desc: "Normalized owner keys surface landlords with multiple qualified lots in one market.",
  },
] as const;

const AUTOMATION = [
  "Celery workers process pipelines 24/7 on the production droplet",
  "Top entitlement deals enqueued every 2 hours — highest scores first",
  "Hourly Slack standup digest + site health watchdog",
  "41 counties across Maryland + Washington; Baltimore prioritized, WA statewide ingest paced",
  "PostGIS spatial queries for rate comps and nearby qualified parcels",
] as const;

function sampleKindLabel(kind: string): string {
  switch (kind) {
    case "deal_memo":
      return "Deal memo";
    case "contract_draft":
      return "Contract draft";
    case "outreach_email":
      return "Outreach email";
    default:
      return kind.replaceAll("_", " ");
  }
}

function fmt(n: number): string {
  return n.toLocaleString();
}

function fmtScore(v: number | null): string {
  return v != null ? v.toFixed(0) : "—";
}

export default function PlatformPage() {
  const countyLabel = useCountyNames();
  const [data, setData] = useState<Showcase | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setErr(null);
      try {
        const res = await fetch(platformShowcaseUrl(), { cache: "no-store" });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const json = (await res.json()) as Showcase;
        if (!cancelled) setData(json);
      } catch (e) {
        if (!cancelled) setErr(e instanceof Error ? e.message : String(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const updated = data?.generated_at
    ? new Date(data.generated_at).toLocaleString(undefined, {
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
      })
    : null;

  return (
    <div className="page-content platform-page">
      <header className="platform-hero">
        <div className="platform-hero-top">
          <div>
            <p className="platform-eyebrow">Multi-state parking acquisition</p>
            <h1>Automated deal intelligence platform</h1>
          </div>
          <div className="platform-hero-actions no-print">
            <button type="button" className="outline" onClick={() => window.print()}>
              Save as PDF
            </button>
          </div>
        </div>
        <p className="platform-lead">
          Three scoring agents, gated enrichment, and full deal packaging — from multi-market parcel ingest to
          counsel-approved outreach. Built for institutional partners who need scale without sacrificing control.
        </p>
        <p className="muted platform-share no-print">
          Shareable link — no login required for this page. Owner contact details in samples are redacted.
        </p>
        {updated ? (
          <p className="muted platform-updated">Live metrics · updated {updated}</p>
        ) : loading ? (
          <p className="muted platform-updated">Loading live metrics…</p>
        ) : null}
      </header>

      {err ? <div className="error">{err}</div> : null}

      {data ? (
        <>
          <section className="platform-metrics" aria-label="Live platform metrics">
            <div className="platform-metric">
              <span className="platform-metric-n">{fmt(data.parcels_total)}</span>
              <span className="platform-metric-label">Parcels analyzed</span>
            </div>
            <div className="platform-metric">
              <span className="platform-metric-n">{fmt(data.parcels_prescreen_qualified)}</span>
              <span className="platform-metric-label">
                Pass prescreen (≥ {data.qualified_floors.identification})
              </span>
            </div>
            <div className="platform-metric">
              <span className="platform-metric-n">{fmt(data.parcels_qualified_entitlement)}</span>
              <span className="platform-metric-label">Entitlement-qualified</span>
            </div>
            <div className="platform-metric">
              <span className="platform-metric-n">{fmt(data.parcels_with_owner_brief)}</span>
              <span className="platform-metric-label">Owner briefs produced</span>
            </div>
            <div className="platform-metric">
              <span className="platform-metric-n">{fmt(data.pipeline_runs_total)}</span>
              <span className="platform-metric-label">Pipeline runs tracked</span>
            </div>
            <div className="platform-metric">
              <span className="platform-metric-n">
                {data.counties_with_ingested_parcels}/{data.pilot_county_count}
              </span>
              <span className="platform-metric-label">Counties with data</span>
            </div>
          </section>

          <section className="panel platform-section">
            <h2>Geographic scope</h2>
            <p className="muted">
              {data.region_name} ·{" "}
              {data.states_in_scope && data.states_in_scope.length > 0
                ? formatStatesLabel(data.states_in_scope)
                : data.state_name}
              {data.primary_market_name ? ` · Priority: ${data.primary_market_name}` : ""}
              {data.primary_metro_label ? ` · ${data.primary_metro_label}` : ""}. Ingest is configured for{" "}
              {data.pilot_county_count} counties; data is loaded for {data.counties_with_ingested_parcels} today
              {data.parcels_in_priority_counties != null && data.parcels_in_priority_counties > 0
                ? ` (${fmt(data.parcels_in_priority_counties)} in priority Maryland counties)`
                : ""}
              .
            </p>
            {data.counties_loaded.length > 0 ? (
              <div className="platform-county-chips">
                {data.counties_loaded.map((c) => (
                  <span
                    key={c.county_fips}
                    className={c.priority_market ? "badge badge-priority" : "badge"}
                  >
                    {countyLine(countyLabel, c.county_fips)}: {fmt(c.parcels_in_db)}
                  </span>
                ))}
              </div>
            ) : null}
          </section>

          <section className="platform-section">
            <h2>End-to-end pipeline</h2>
            <p className="muted section-lead">
              Parcels narrow through deterministic gates — we only spend on owner lookup, skip trace, and contract
              generation when both Atlas and Beacon agree a lot is worth pursuing.
            </p>
            <div className="platform-pipeline">
              {PIPELINE_STAGES.map((stage, i) => (
                <div key={stage.id} className="platform-pipeline-step">
                  <div className="platform-pipeline-marker">{i + 1}</div>
                  <div className="platform-pipeline-body">
                    <strong>{stage.title}</strong>
                    <p className="muted">{stage.body}</p>
                  </div>
                </div>
              ))}
            </div>
          </section>

          <section className="platform-section">
            <h2>Three scoring agents</h2>
            <p className="muted section-lead">
              Named agents in Slack digests and operator views — each runs a YAML-configured scoring engine over
              parcel attributes (not black-box LLM guesses on zoning).
            </p>
            <div className="platform-agents">
              {AGENTS.map((a) => (
                <article key={a.codename} className="panel platform-agent-card">
                  <div className="platform-agent-name">{a.codename}</div>
                  <div className="platform-agent-role">{a.role}</div>
                  <p className="muted">{a.evaluates}</p>
                  <p className="muted platform-agent-when">
                    <strong>When:</strong> {a.when}
                  </p>
                </article>
              ))}
            </div>
          </section>

          <section className="platform-section">
            <h2>What the system produces</h2>
            <div className="platform-deliverables">
              {DELIVERABLES.map((d) => (
                <div key={d.title} className="platform-deliverable">
                  <strong>{d.title}</strong>
                  <p className="muted">{d.desc}</p>
                </div>
              ))}
            </div>
          </section>

          <section className="panel platform-section">
            <h2>Pipeline activity (live)</h2>
            <div className="cols">
              {Object.entries(data.pipeline_by_stage).map(([stage, n]) => (
                <div key={stage} className="stat">
                  <div className="n">{n}</div>
                  <div className="muted">{stage.replaceAll("_", " ")}</div>
                </div>
              ))}
            </div>
            {Object.keys(data.pipeline_by_step).length > 0 ? (
              <>
                <p className="muted" style={{ marginTop: "1rem" }}>
                  Currently processing by step:
                </p>
                <div className="platform-county-chips">
                  {Object.entries(data.pipeline_by_step).map(([step, n]) => (
                    <span key={step} className="badge">
                      {step.replaceAll("_", " ")}: {n}
                    </span>
                  ))}
                </div>
              </>
            ) : null}
            <p className="muted" style={{ marginTop: "1rem" }}>
              {fmt(data.parcels_pipeline_backlog)} prescreen-qualified parcels still waiting for full Atlas/Beacon
              scoring · qualified floors: Cartographer ≥ {data.qualified_floors.identification}, Atlas ≥{" "}
              {data.qualified_floors.entitlement}
            </p>
          </section>

          {data.sample_deliverables && data.sample_deliverables.length > 0 ? (
            <section className="platform-section">
              <h2>Sample outputs (from real pipeline runs)</h2>
              <p className="muted section-lead">
                Excerpts from production deal memos, contract drafts, and outreach email — contact details redacted
                for partner sharing. Full artifacts available to authorized operators after counsel review.
              </p>
              <div className="platform-samples">
                {data.sample_deliverables.map((s) => (
                  <article key={s.kind} className="panel platform-sample-card">
                    <div className="platform-sample-head">
                      <span className="badge">{sampleKindLabel(s.kind)}</span>
                      <span className="muted">APN {s.parcel_apn}</span>
                    </div>
                    <h3 className="platform-sample-title">{s.title}</h3>
                    <pre className="platform-sample-body">{s.excerpt}</pre>
                  </article>
                ))}
              </div>
            </section>
          ) : null}

          <section className="platform-section">
            <h2>Top-ranked deals (sample)</h2>
            <p className="muted section-lead">
              Highest entitlement scores in the database right now — open any parcel to see market context, owner
              research, and outreach drafts.
            </p>
            <div className="panel panel-flush">
              <table className="data">
                <thead>
                  <tr>
                    <th>APN</th>
                    <th>County</th>
                    <th>Atlas</th>
                    <th>Beacon</th>
                    <th>Cartographer</th>
                    <th>Lot</th>
                    <th>Brief</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {data.top_parcels.map((p) => (
                    <tr key={p.parcel_id}>
                      <td>{p.apn}</td>
                      <td className="muted">{countyLine(countyLabel, p.county_fips)}</td>
                      <td>
                        <strong>{fmtScore(p.entitlement_score)}</strong>
                      </td>
                      <td>{fmtScore(p.strategic_score)}</td>
                      <td>{fmtScore(p.identification_score)}</td>
                      <td className="muted">
                        {p.lot_sqft != null ? `${Math.round(p.lot_sqft).toLocaleString()} sf` : "—"}
                      </td>
                      <td>{p.has_outreach_brief ? "✓" : "—"}</td>
                      <td>
                        <Link href={`/parcels/${p.parcel_id}`} className="btn-link">
                          View deal →
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="panel platform-section platform-automation">
            <h2>Automation &amp; reliability</h2>
            <ul className="platform-automation-list">
              {AUTOMATION.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          </section>

          <section className="platform-cta panel">
            <h2>Explore the live console</h2>
            <p className="muted">
              Partners with access can drill into qualified deals, approval queues, and parcel-level enrichment.
            </p>
            <div className="platform-cta-links">
              <Link href="/outreach" className="btn-link btn-link-primary">
                Outreach pipeline
              </Link>
              <Link href="/deals" className="btn-link">
                Deal progress
              </Link>
              <Link href="/parcels" className="btn-link">
                All parcels
              </Link>
              <Link href="/" className="btn-link">
                Operator overview
              </Link>
            </div>
          </section>
        </>
      ) : loading && !err ? (
        <div className="panel muted">Loading platform showcase…</div>
      ) : null}
    </div>
  );
}
