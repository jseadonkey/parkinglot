/** Business operations model — mirrors config/pilot.yaml deal.operations and docs/OPERATIONS-MODEL.md */

export const OPERATIONS_MODEL = {
  title: "What we’re looking for",
  leaseModel: "Master lease",
  siteUse: "Standalone unmanned surface parking",
  summary:
    "We master-lease land to operate unmanned surface parking lots (pay-by-app or similar — no attendants, no valet, no staffed garages). Parking on the leased portion must be the primary use, not accessory parking for someone else’s building.",
  partialLotNote:
    "Exception: a site may still work if the owner built on part of the lot (e.g. one half) and a suitable empty portion remains for unmanned parking — subject to zoning and counsel review. The building-value check (≤70% of assessed total) is a roll-data hint that undeveloped capacity may exist.",
  outOfScope: [
    "Accessory parking only (for another building)",
    "Attended or valet lots",
    "Staffed structured garages",
    "Mixed-use where parking isn’t the primary master lease",
  ],
} as const;
