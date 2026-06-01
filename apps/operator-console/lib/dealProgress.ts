/** Pipeline step order for deal progress visualization. */

export const PIPELINE_STEPS = [
  "score",
  "enrich",
  "memo",
  "contract_draft",
  "awaiting_human",
] as const;

export type PipelineStepId = (typeof PIPELINE_STEPS)[number];

const STEP_LABELS: Record<string, string> = {
  ingest: "Ingest",
  score: "Score",
  enrich: "Enrich",
  memo: "Memo",
  contract_draft: "Contract",
  awaiting_human: "Review",
};

export function pipelineStepLabel(step: string | null): string {
  if (!step) return "—";
  return STEP_LABELS[step] ?? step.replaceAll("_", " ");
}

export function pipelineStepIndex(step: string | null): number {
  if (!step) return -1;
  const idx = PIPELINE_STEPS.indexOf(step as PipelineStepId);
  return idx >= 0 ? idx : -1;
}

export function pipelineProgressPercent(row: {
  pipeline_stage: string;
  workflow_step: string | null;
}): number {
  if (row.pipeline_stage === "completed") return 100;
  if (row.pipeline_stage === "failed") return 0;
  const idx = pipelineStepIndex(row.workflow_step);
  if (idx < 0) return row.pipeline_stage === "running" ? 15 : 0;
  return Math.round(((idx + 1) / PIPELINE_STEPS.length) * 100);
}

export function statusLabel(stage: string, step: string | null, pendingApprovals: number): string {
  if (stage === "failed") return "Failed";
  if (pendingApprovals > 0) return "Needs approval";
  if (stage === "blocked" || step === "awaiting_human") return "Waiting on you";
  if (stage === "completed") return "Complete";
  if (stage === "running") return pipelineStepLabel(step);
  return stage;
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
