import { SCORE_COLUMN_LEGEND, SCORE_PROFILES, OPERATIONS_SCORING_NOTE, SCORING_ORDER_NOTE } from "../lib/scoringMethodology";

type Props = {
  /** compact = summary cards; full = detailed cards with incomplete-data notes */
  variant?: "compact" | "full";
};

export function ScoringMethodologyPanel({ variant = "compact" }: Props) {
  return (
    <section className="scoring-methodology" aria-labelledby="scoring-methodology-heading">
      <h2 id="scoring-methodology-heading">Three scoring agents (0–100 each)</h2>
      <p className="muted">{SCORE_COLUMN_LEGEND}</p>
      <p className="muted">{OPERATIONS_SCORING_NOTE}</p>
      <p className="muted">{SCORING_ORDER_NOTE}</p>
      <div className={`scoring-methodology-grid scoring-methodology-grid--${variant}`}>
        {SCORE_PROFILES.map((p) => (
          <article key={p.id} className="scoring-profile-card">
            <header className="scoring-profile-head">
              <strong>{p.title}</strong>
              <span className="badge">{p.agentLabel}</span>
            </header>
            <p className="scoring-profile-meta muted">
              Floor <strong>{p.floor}</strong> — {p.floorUsedFor}
            </p>
            <dl className="scoring-profile-dl">
              <div>
                <dt>When</dt>
                <dd>{p.whenComputed}</dd>
              </div>
              <div>
                <dt>Inputs</dt>
                <dd>{p.inputs}</dd>
              </div>
              <div>
                <dt>Weights</dt>
                <dd>{p.weightsSummary}</dd>
              </div>
              <div>
                <dt>Market signal</dt>
                <dd>{p.marketSignal}</dd>
              </div>
              {variant === "full" && p.incompleteWhen ? (
                <div className="scoring-profile-incomplete">
                  <dt>May look incomplete when</dt>
                  <dd>{p.incompleteWhen}</dd>
                </div>
              ) : null}
            </dl>
          </article>
        ))}
      </div>
      {variant === "compact" ? (
        <p className="muted scoring-methodology-footnote">
          Identification scores appear first during bulk load but omit parking comps. Strategic scores may lack comp
          points until the parcel passes entitlement + building gates. Open a parcel detail page for full breakdown
          notes.
        </p>
      ) : null}
    </section>
  );
}
