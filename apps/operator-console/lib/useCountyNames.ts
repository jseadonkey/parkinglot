"use client";

import { useEffect, useState } from "react";

import { bridgeUrl } from "./paths";

const FALLBACK: Record<string, string> = {
  "53033": "King",
};

export function useCountyNames(): (fips: string) => string {
  const [map, setMap] = useState<Record<string, string>>(FALLBACK);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(bridgeUrl("internal/stats/pilot-scope"), { cache: "no-store" });
        if (!res.ok) return;
        const data = (await res.json()) as {
          counties?: Array<{ county_fips: string; county_name: string }>;
        };
        if (cancelled || !data.counties) return;
        const next: Record<string, string> = { ...FALLBACK };
        for (const c of data.counties) {
          const short = c.county_name.replace(/ County$/i, "");
          next[c.county_fips] = short;
        }
        setMap(next);
      } catch {
        /* keep fallback */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return (fips: string) => map[fips] ?? fips;
}

export function countyLine(label: (fips: string) => string, fips: string): string {
  const name = label(fips);
  return name === fips ? fips : `${name} Co · ${fips}`;
}
