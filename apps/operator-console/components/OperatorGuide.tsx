import Link from "next/link";

const STEPS = [
  {
    title: "Parcels load from county GIS",
    body: "Baltimore City loads from Maryland EGIS (Baltimore County is paused for now). Washington counties load from assessor exports and WaTech. King County has the largest WA footprint today; Baltimore City is the active priority market.",
  },
  {
    title: "Prescreen narrows the field",
    body: "Every ingested parcel gets a Cartographer (identification) score. Only parcels above the prescreen floor are eligible for the full deal pipeline.",
  },
  {
    title: "Agents score and enrich top deals",
    body: "Atlas (entitlement) runs first — if the score is below the qualified floor, enrichment stops. Otherwise Beacon (strategic) runs, then owner lookup, skip trace, outreach brief, memo, and contract draft.",
  },
  {
    title: "You approve before anything goes out",
    body: "Memos, contracts, and outbound email/text/voice/mail sit in Approvals until a human approves. Message copy comes from Message templates.",
  },
] as const;

export function OperatorGuide() {
  return (
    <section className="panel guide-panel" aria-labelledby="guide-heading">
      <h2 id="guide-heading">How the process works</h2>
      <p className="muted guide-intro">
        The console tracks parking-lot acquisition candidates across configured pilot markets (Maryland priority,
        Washington secondary). Automated agents do research and drafting; you review and approve before outreach.
      </p>
      <ol className="guide-steps">
        {STEPS.map((step, i) => (
          <li key={step.title} className="guide-step">
            <span className="guide-step-n">{i + 1}</span>
            <div>
              <strong>{step.title}</strong>
              <p className="muted">{step.body}</p>
            </div>
          </li>
        ))}
      </ol>
      <div className="guide-links muted">
        <strong>Where to work</strong>
        <ul>
          <li>
            <Link href="/outreach">Outreach pipeline</Link> — daily queue of qualified parcels (start with{" "}
            <em>Needs action</em>)
          </li>
          <li>
            <Link href="/approvals">Approvals</Link> — memos, contracts, and outbound messages waiting on you
          </li>
          <li>
            <Link href="/deals">Deal progress</Link> — every parcel with a pipeline run and step-by-step status
          </li>
          <li>
            <Link href="/parcels">Parcels</Link> — browse scored inventory by state or county; open any APN for detail
          </li>
        </ul>
      </div>
    </section>
  );
}

export function QuickStartCards() {
  return (
    <div className="quick-start">
      <Link href="/outreach" className="quick-card">
        <span className="quick-card-label">Start here</span>
        <strong>Outreach pipeline</strong>
        <span className="muted">Qualified deals ranked by score — filter Needs action first</span>
      </Link>
      <Link href="/approvals" className="quick-card">
        <span className="quick-card-label">Review</span>
        <strong>Approvals</strong>
        <span className="muted">Approve or reject memos, contracts, and outbound messages</span>
      </Link>
      <Link href="/templates" className="quick-card">
        <span className="quick-card-label">Customize</span>
        <strong>Message templates</strong>
        <span className="muted">Default email, text, voice, and mail copy before outreach</span>
      </Link>
    </div>
  );
}
