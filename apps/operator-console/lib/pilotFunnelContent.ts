/** Plain-language parcel data funnel — shown on operator overview. */

export type FunnelStep = {
  step: number;
  title: string;
  detail: string;
  runsOn: string;
};

export const PILOT_FUNNEL_STEPS: FunnelStep[] = [
  {
    step: 1,
    title: "County parcel scan",
    detail: "Footprint, assessor ID, land use, building vs land value, owner name.",
    runsOn: "All King County (~633k) — once per bulk load",
  },
  {
    step: 2,
    title: "Geography",
    detail: "Kent city + unincorporated King only. Excludes Seattle, Bellevue, etc.",
    runsOn: "Survivors of step 1",
  },
  {
    step: 3,
    title: "Land use",
    detail: "Drop obvious housing (assessor codes 11–19).",
    runsOn: "Survivors of step 2",
  },
  {
    step: 4,
    title: "Lot size",
    detail: "Minimum 5,000 sq ft.",
    runsOn: "Survivors of step 3",
  },
  {
    step: 5,
    title: "Zoning",
    detail:
      "Drop zones explicitly forbidden for primary-use standalone unmanned surface parking in our rules file (accessory-only parking is out of scope).",
    runsOn: "Survivors of step 4 → ~125k candidates",
  },
  {
    step: 6,
    title: "Slim database row",
    detail: "Store geometry + roll fields only — no paid-parking comp lookup yet.",
    runsOn: "Funnel output ingested to DB",
  },
  {
    step: 7,
    title: "Building check",
    detail:
      "Skip sites where assessed building value exceeds 70% of total (already built out). Proxy for “room on the lot” — partially developed sites (e.g. half empty) may still qualify for unmanned parking on the open portion.",
    runsOn: "Survivors of step 6 — before parking comps",
  },
  {
    step: 8,
    title: "Identification prescreen (Cartographer)",
    detail:
      "0–100 score at ingest from roll + geometry only (zoning, lot size, corner). No parking comp lookup yet — market points stay empty until pipeline.",
    runsOn: "Every parcel loaded to DB",
  },
  {
    step: 9,
    title: "Entitlement score (Atlas)",
    detail:
      "0–100 zoning-forward score in pipeline. Uses POI demand proximity (e.g. Kent Station), not parking comps. Floor 55 for deal qualification.",
    runsOn: "Pipeline runs on in-scope parcel",
  },
  {
    step: 10,
    title: "Strategic score (Beacon)",
    detail:
      "0–100 market-forward score. Parking comp distance + daily rate (40 pts) only after entitlement ≥ 55, surface zoning OK, and building value ≤ 70% of total.",
    runsOn: "Gated subset of pipeline-scored parcels",
  },
  {
    step: 11,
    title: "Owner research (tiered)",
    detail: "Basic = roll only. Standard = SOS + portfolio when dual-qualified. Deep = vendor webhook.",
    runsOn: "Dual-qualified parcels only (entitlement ≥ 55 and strategic ≥ 52)",
  },
  {
    step: 12,
    title: "Deal memo + your approval",
    detail: "Human review of memo and contract draft before outreach.",
    runsOn: "Dual-qualified pipeline completes",
  },
];

export const DEAL_STAGE_OPTIONS = [
  { id: "", label: "All stages" },
  { id: "needs_review", label: "Qualified — needs your review" },
  { id: "approved_ready", label: "Approved — ready for outreach" },
  { id: "scoring", label: "Scoring / enriching" },
  { id: "in_queue", label: "In queue" },
  { id: "screened_out", label: "Screened out" },
  { id: "failed", label: "Failed" },
] as const;

export function dealStageBadgeClass(stage: string): string {
  switch (stage) {
    case "needs_review":
      return "deal-stage--review";
    case "approved_ready":
      return "deal-stage--ready";
    case "scoring":
    case "in_queue":
      return "deal-stage--active";
    case "failed":
      return "deal-stage--failed";
    default:
      return "deal-stage--muted";
  }
}
