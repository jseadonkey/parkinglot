"use client";

import { STATE_NAMES, type PilotCountyRow } from "../lib/usePilotScope";

type Props = {
  stateFips: string;
  countyFips: string;
  counties: PilotCountyRow[];
  priorityFips: Set<string>;
  onStateChange: (stateFips: string) => void;
  onCountyChange: (countyFips: string) => void;
};

export function MarketFilters({
  stateFips,
  countyFips,
  counties,
  priorityFips,
  onStateChange,
  onCountyChange,
}: Props) {
  const countyOptions = counties.filter((c) => !stateFips || c.county_fips.startsWith(stateFips));

  return (
    <>
      <label className="toolbar-field muted">
        State{" "}
        <select
          value={stateFips}
          onChange={(e) => {
            onStateChange(e.target.value);
            onCountyChange("");
          }}
        >
          <option value="">All states</option>
          <option value="24">{STATE_NAMES["24"]} (MD)</option>
          <option value="53">{STATE_NAMES["53"]} (WA)</option>
        </select>
      </label>
      <label className="toolbar-field muted">
        County{" "}
        <select
          value={countyFips}
          onChange={(e) => onCountyChange(e.target.value)}
          disabled={countyOptions.length === 0}
        >
          <option value="">All counties{stateFips ? " in state" : ""}</option>
          {countyOptions
            .slice()
            .sort(
              (a, b) =>
                (b.priority_market || priorityFips.has(b.county_fips) ? 1 : 0) -
                  (a.priority_market || priorityFips.has(a.county_fips) ? 1 : 0) ||
                a.county_name.localeCompare(b.county_name),
            )
            .map((c) => (
              <option key={c.county_fips} value={c.county_fips}>
                {c.county_name}
                {c.priority_market || priorityFips.has(c.county_fips) ? " ★" : ""} ({c.county_fips})
              </option>
            ))}
        </select>
      </label>
    </>
  );
}
