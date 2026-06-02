/** Static pilot geography from config/pilot.yaml — shown instantly while counts load. */

export const PILOT_SCOPE_DEFAULTS = {
  region_name: "Washington — statewide pilot",
  state_fips: "53",
  state_name: "Washington",
  primary_metro_label: "Seattle-Tacoma-Bellevue, WA",
  pilot_county_count: 39,
  min_lot_sqft: 5000,
  qualified_min_entitlement: 55,
} as const;
