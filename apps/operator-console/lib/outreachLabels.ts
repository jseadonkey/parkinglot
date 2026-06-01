/** Human-readable labels for outreach pipeline rows. */

export type PipelineRowLike = {
  pipeline_stage: string;
  workflow_status: string | null;
  workflow_step: string | null;
  workflow_error: string | null;
  pending_approval_count: number;
  has_outreach_brief: boolean;
};

export function needsAction(row: PipelineRowLike): boolean {
  if (row.pipeline_stage === "failed") return true;
  if (row.pending_approval_count > 0) return true;
  if (row.pipeline_stage === "blocked") return true;
  return false;
}

export function statusHeadline(row: PipelineRowLike): string {
  if (row.pipeline_stage === "failed") return "Pipeline failed";
  if (row.pending_approval_count > 0) {
    const n = row.pending_approval_count;
    return n === 1 ? "1 approval waiting" : `${n} approvals waiting`;
  }
  if (row.pipeline_stage === "blocked") {
    if (row.workflow_step === "awaiting_human") return "Waiting on you";
    return "Blocked";
  }
  if (row.pipeline_stage === "completed") return "Ready for outreach";
  if (row.pipeline_stage === "running") return "Processing";
  if (row.pipeline_stage === "no_run") return "Not started";
  return row.pipeline_stage;
}

export function statusDetail(row: PipelineRowLike): string | null {
  if (row.workflow_error) return row.workflow_error.slice(0, 140);
  if (row.pending_approval_count > 0) return "Review contract draft on Approvals page";
  if (row.pipeline_stage === "blocked" && row.workflow_step) {
    return stepLabel(row.workflow_step);
  }
  if (row.pipeline_stage === "completed") {
    return row.has_outreach_brief ? "Outreach brief ready" : "No outreach brief yet";
  }
  if (row.workflow_step) return stepLabel(row.workflow_step);
  return null;
}

export function stepLabel(step: string): string {
  const map: Record<string, string> = {
    awaiting_human: "Human review required",
    enrich: "Enriching owner data",
    score: "Scoring parcel",
    memo: "Drafting deal memo",
  };
  return map[step] ?? step.replaceAll("_", " ");
}

export function formatRelativeTime(iso: string | null): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return iso.slice(0, 10);
  const diffMs = Date.now() - then;
  const mins = Math.floor(diffMs / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 48) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  if (days < 14) return `${days}d ago`;
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function stageBadgeClass(stage: string): string {
  switch (stage) {
    case "blocked":
      return "badge badge-warn";
    case "completed":
      return "badge badge-ok";
    case "failed":
      return "badge badge-err";
    case "running":
      return "badge badge-run";
    default:
      return "badge";
  }
}
