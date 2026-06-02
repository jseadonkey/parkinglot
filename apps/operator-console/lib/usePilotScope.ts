"use client";

import { useEffect, useState } from "react";

import { STATE_NAMES } from "./marketScope";
import { bridgeUrl } from "./paths";

export type PilotCountyRow = {
  county_fips: string;
  county_name: string;
  parcels_in_db: number;
  priority_market?: boolean;
};

export type PilotScopeData = {
  region_name: string;
  state_name: string;
  primary_market_name?: string;
  priority_county_fips?: string[];
  counties: PilotCountyRow[];
};

export function usePilotScope(): {
  scope: PilotScopeData | null;
  loading: boolean;
  priorityFips: Set<string>;
} {
  const [scope, setScope] = useState<PilotScopeData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(bridgeUrl("internal/stats/pilot-scope"), { cache: "no-store" });
        if (!res.ok) return;
        const data = (await res.json()) as PilotScopeData;
        if (!cancelled) setScope(data);
      } catch {
        /* ignore */
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const priorityFips = new Set(scope?.priority_county_fips ?? ["24510"]);
  return { scope, loading, priorityFips };
}

export function marketFilterParams(stateFips: string, countyFips: string): URLSearchParams {
  const params = new URLSearchParams();
  if (countyFips) params.set("county_fips", countyFips);
  else if (stateFips) params.set("state_fips", stateFips);
  return params;
}

export { STATE_NAMES };
