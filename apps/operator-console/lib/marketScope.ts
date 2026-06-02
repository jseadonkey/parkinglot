/** Geography helpers for multi-state pilot (Maryland + Washington). */

export const STATE_ABBR: Record<string, string> = {
  "24": "MD",
  "53": "WA",
};

export const STATE_NAMES: Record<string, string> = {
  "24": "Maryland",
  "53": "Washington",
};

export function stateFipsFromCounty(countyFips: string): string {
  return countyFips.length >= 2 ? countyFips.slice(0, 2) : "";
}

export function stateAbbr(countyFips: string): string {
  const st = stateFipsFromCounty(countyFips);
  return STATE_ABBR[st] ?? st;
}

export function formatStatesLabel(states: Array<{ state_fips: string; state_name: string }>): string {
  if (states.length === 0) return "—";
  if (states.length === 1) return states[0].state_name;
  return states.map((s) => s.state_name).join(" + ");
}
