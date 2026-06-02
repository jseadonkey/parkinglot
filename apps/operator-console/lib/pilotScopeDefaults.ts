/** Static pilot geography — shown instantly while counts load (multi-state). */

export const PILOT_SCOPE_DEFAULTS = {
  region_name: "Baltimore MD (priority) + Washington statewide",
  state_fips: "24",
  state_name: "Maryland + Washington",
  primary_market_name: "Baltimore, Maryland",
  primary_market_state_fips: "24",
  priority_county_fips: ["24510", "24005"] as const,
  primary_metro_label: "Baltimore-Columbia-Towson, MD",
  pilot_county_count: 41,
  min_lot_sqft: 5000,
  qualified_min_entitlement: 55,
} as const;
