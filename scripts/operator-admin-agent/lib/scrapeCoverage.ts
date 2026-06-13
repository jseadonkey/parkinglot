export type CountyZeroGrab = {
  county_fips: string;
  county_name: string;
  parcels_in_db: number;
  priority_market: boolean;
  kind: "pilot_priority" | "wa_rollout_next" | "wa_rollout_pending";
};

export type ScrapeCoverage = {
  pilot_county_count: number;
  counties_with_data: number;
  counties_zero_grab_count: number;
  scrape_gaps: CountyZeroGrab[];
  wa_rollout_enabled: boolean;
  wa_counties_remaining: number;
  wa_next_county_fips: string | null;
  wa_next_county_parcels: number;
  wa_cooldown_ready: boolean;
  backlog_complete: boolean;
  should_advance_counties: boolean;
};

type PilotCounty = {
  county_fips: string;
  county_name: string;
  parcels_in_db: number;
  priority_market?: boolean;
};

type PilotScope = {
  pilot_county_count?: number;
  counties_with_ingested_parcels?: number;
  priority_county_fips?: string[];
  counties?: PilotCounty[];
};

type WaRollout = {
  rollout_enabled?: boolean;
  next_county_fips?: string | null;
  counties_remaining?: number;
  cooldown_ready?: boolean | null;
  counties?: { county_fips: string; parcels_in_db: number }[];
};

type BacklogItem = {
  key?: string;
  value?: string;
  backlog_count?: number;
  total_count?: number;
  status?: string;
};

const SCORE_GAPS_DONE_THRESHOLD = Number(process.env.OPERATOR_AGENT_SCORE_GAPS_DONE ?? "1000");

export function buildScrapeCoverage(
  pilotScope: PilotScope | null,
  waRollout: WaRollout | null,
  backlogRaw: unknown,
): ScrapeCoverage {
  const counties = pilotScope?.counties ?? [];
  const priorityFips = new Set(pilotScope?.priority_county_fips ?? []);
  const nextFips = waRollout?.next_county_fips ?? null;
  const waCounties = waRollout?.counties ?? [];

  const zeroGrab: CountyZeroGrab[] = [];
  for (const c of counties) {
    if ((c.parcels_in_db ?? 0) > 0) continue;
    const isPriority = Boolean(c.priority_market) || priorityFips.has(c.county_fips);
    let kind: CountyZeroGrab["kind"] = "wa_rollout_pending";
    if (isPriority) {
      kind = "pilot_priority";
    } else if (nextFips && c.county_fips === nextFips) {
      kind = "wa_rollout_next";
    }
    zeroGrab.push({
      county_fips: c.county_fips,
      county_name: c.county_name,
      parcels_in_db: 0,
      priority_market: isPriority,
      kind,
    });
  }

  const nextParcels =
    waCounties.find((c) => c.county_fips === nextFips)?.parcels_in_db ??
    counties.find((c) => c.county_fips === nextFips)?.parcels_in_db ??
    0;

  const items: BacklogItem[] =
    backlogRaw && typeof backlogRaw === "object" && Array.isArray((backlogRaw as { items?: unknown }).items)
      ? ((backlogRaw as { items: BacklogItem[] }).items ?? [])
      : [];
  const summary =
    backlogRaw && typeof backlogRaw === "object" && "summary" in backlogRaw
      ? ((backlogRaw as { summary: Record<string, unknown> }).summary ?? {})
      : {};

  const highValueRemaining = Number(summary.high_value_remaining ?? 0);
  const scoreGaps = Number(
    items.find((i) => i.key === "score_gaps")?.backlog_count ??
      (summary as { score_gaps?: number }).score_gaps ??
      0,
  );

  const highValueOpen = items
    .filter((i) => i.value === "high")
    .some((i) => Number(i.backlog_count ?? 0) > 0);

  const backlogComplete =
    highValueRemaining === 0 && !highValueOpen && scoreGaps < SCORE_GAPS_DONE_THRESHOLD;

  const waRemaining = Number(waRollout?.counties_remaining ?? 0);
  const rolloutEnabled = Boolean(waRollout?.rollout_enabled);
  const cooldownReady = Boolean(waRollout?.cooldown_ready);
  const governorAllows = summary.wa_rollout_allowed !== false;

  const shouldAdvanceCounties =
    backlogComplete &&
    rolloutEnabled &&
    waRemaining > 0 &&
    governorAllows &&
    (cooldownReady || (nextFips != null && nextParcels === 0));

  return {
    pilot_county_count: Number(pilotScope?.pilot_county_count ?? counties.length),
    counties_with_data: Number(
      pilotScope?.counties_with_ingested_parcels ?? counties.filter((c) => (c.parcels_in_db ?? 0) > 0).length,
    ),
    counties_zero_grab_count: zeroGrab.length,
    scrape_gaps: zeroGrab,
    wa_rollout_enabled: rolloutEnabled,
    wa_counties_remaining: waRemaining,
    wa_next_county_fips: nextFips,
    wa_next_county_parcels: nextParcels,
    wa_cooldown_ready: cooldownReady,
    backlog_complete: backlogComplete,
    should_advance_counties: shouldAdvanceCounties,
  };
}
