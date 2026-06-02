/** Static pilot geography — shown instantly while counts load (Baltimore-first). */

export const PILOT_SCOPE_DEFAULTS = {
  region_name: "Baltimore + Washington pilot",
  state_fips: "24",
  state_name: "Maryland",
  primary_metro_label: "Baltimore-Columbia-Towson, MD",
  pilot_county_count: 41,
  min_lot_sqft: 5000,
  qualified_min_entitlement: 55,
} as const;
