import { OPERATIONS_MODEL } from "../lib/operationsModel";

export function OperationsModelPanel() {
  return (
    <section className="operations-model" aria-labelledby="operations-model-heading">
      <h2 id="operations-model-heading">{OPERATIONS_MODEL.title}</h2>
      <p>
        <strong>{OPERATIONS_MODEL.leaseModel}</strong> · {OPERATIONS_MODEL.siteUse}
      </p>
      <p className="muted">{OPERATIONS_MODEL.summary}</p>
      <p className="muted">{OPERATIONS_MODEL.partialLotNote}</p>
      <details className="operations-model-excluded">
        <summary className="muted">Out of scope for this pilot</summary>
        <ul>
          {OPERATIONS_MODEL.outOfScope.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </details>
    </section>
  );
}
