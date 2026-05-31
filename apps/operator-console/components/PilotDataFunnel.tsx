import Link from "next/link";
import { PILOT_FUNNEL_STEPS } from "../lib/pilotFunnelContent";

export function PilotDataFunnel() {
  return (
    <section className="funnel-section" aria-labelledby="funnel-heading">
      <h2 id="funnel-heading">How we filter parcels (cheap → expensive)</h2>
      <p className="muted">
        We only spend time on parking comps, deep owner lookup, and deal memos for parcels that survive each gate.
        Most county parcels never get past the early sieves.
      </p>
      <ol className="funnel-list">
        {PILOT_FUNNEL_STEPS.map((item) => (
          <li key={item.step} className="funnel-item">
            <div className="funnel-step-num">{item.step}</div>
            <div className="funnel-body">
              <strong>{item.title}</strong>
              <p>{item.detail}</p>
              <span className="funnel-runs muted">Runs on: {item.runsOn}</span>
            </div>
          </li>
        ))}
      </ol>
      <p className="muted funnel-footnote">
        Rule of thumb: <strong>roll and zoning first</strong>, building check second, scores third, parking comps
        fourth, owner lookups last. See <Link href="/deals">Deal progress</Link> for where each parcel sits today.
      </p>
    </section>
  );
}
