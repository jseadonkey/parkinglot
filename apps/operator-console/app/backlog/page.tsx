import { BacklogEtaPanel } from "../../components/BacklogEtaPanel";

export default function BacklogPage() {
  return (
    <div className="page-content">
      <h2>Backlog value & ETA</h2>
      <p className="muted">
        Use this page to decide whether a backlog is worth running, narrowing, throttling, or pausing. ETAs are rough
        unless a recent measured batch exists; low-confidence rows should be sampled before a full run.
      </p>
      <BacklogEtaPanel />
    </div>
  );
}
