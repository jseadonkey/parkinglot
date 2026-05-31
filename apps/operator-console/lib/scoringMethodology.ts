/** Plain-language descriptions of the three scoring profiles (operator console). */

export type ScoreProfileId = "identification" | "entitlement" | "strategic";

export type ScoreProfileInfo = {
  id: ScoreProfileId;
  agentLabel: string;
  title: string;
  floor: number;
  floorUsedFor: string;
  whenComputed: string;
  inputs: string;
  weightsSummary: string;
  marketSignal: string;
  incompleteWhen: string | null;
};

export const SCORE_PROFILES: ScoreProfileInfo[] = [
  {
    id: "identification",
    agentLabel: "Cartographer",
    title: "Identification prescreen",
    floor: 45,
    floorUsedFor: "Tracking only — not used for deal memos or outreach qualification.",
    whenComputed: "Immediately when a parcel is loaded into the database (bulk ingest).",
    inputs: "Assessor roll + geometry only: zoning flag, lot size, corner lot.",
    weightsSummary: "Zoning 45 · lot size 25 · corner 10 · market 20 (max ~80 without comps).",
    marketSignal:
      "Config reserves 20 points for parking comps, but comps are not looked up at ingest — only during the full pipeline for gated parcels.",
    incompleteWhen:
      "Every identification score is missing the market component until (and unless) the parcel later passes the parking-comp gate in pipeline.",
  },
  {
    id: "entitlement",
    agentLabel: "Atlas",
    title: "Entitlement score",
    floor: 55,
    floorUsedFor: "Must meet this floor (with strategic) for deal memos, owner research, and outreach list.",
    whenComputed: "During the scoring pipeline — not at initial ingest.",
    inputs: "Same roll fields plus POI distance to configured demand generators (e.g. Kent Station).",
    weightsSummary: "Zoning 40 · lot size 20 · corner 10 · POI demand proximity 30.",
    marketSignal:
      "Uses straight-line distance to pilot POI points — not parking comps. This profile is the zoning-forward “can we entitle surface parking here?” view.",
    incompleteWhen: null,
  },
  {
    id: "strategic",
    agentLabel: "Beacon",
    title: "Strategic score",
    floor: 52,
    floorUsedFor: "Must meet this floor (with entitlement) for deal memos, owner research, and outreach list.",
    whenComputed: "During the scoring pipeline, after optional parking-comp lookup.",
    inputs: "Roll fields plus nearest curated paid parking lot (distance + screening daily rate) when gates pass.",
    weightsSummary: "Zoning 25 · lot size 20 · corner 15 · parking comp proximity 40.",
    marketSignal:
      "Emphasizes paid parking comp market signal — nearest lot within 800 m at ≥ $6/day screening rate earns up to 40 points.",
    incompleteWhen:
      "Comp lookup runs only when entitlement ≥ 55, zoning allows surface parking, and assessed building value ≤ 70% of total. Most parcels show 0 on the 40-point market component until those gates pass.",
  },
];

export const SCORE_PROFILE_BY_ID: Record<ScoreProfileId, ScoreProfileInfo> = Object.fromEntries(
  SCORE_PROFILES.map((p) => [p.id, p]),
) as Record<ScoreProfileId, ScoreProfileInfo>;

/** Column legend for Ent / Str / Id tables. */
export const SCORE_COLUMN_LEGEND =
  "Ent = Atlas entitlement · Str = Beacon strategic · Id = Cartographer identification prescreen. Only Ent + Str together qualify a parcel for outreach.";

export const DUAL_QUALIFICATION_NOTE =
  "Dual qualification requires both Atlas (entitlement) and Beacon (strategic) to meet their floors. Identification is an early prescreen and does not gate deal memos.";

export const SCORING_ORDER_NOTE =
  "Order of operations: load parcel → identification prescreen → pipeline entitlement (POI) → gated parking comp lookup → strategic score → owner research for dual-qualified parcels.";

/** Mirrors docs/OPERATIONS-MODEL.md — unmanned surface parking master lease. */
export const OPERATIONS_SCORING_NOTE =
  "Acquisition target: master-lease land for standalone unmanned surface parking (not attended/valet/accessory-only). Partially developed lots (e.g. half built, half empty) may qualify on the undeveloped portion — building-value ≤70% is a roll-data proxy.";
