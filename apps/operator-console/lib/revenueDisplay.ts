/** Format illustrative monthly gross for tables (matches outreach page). */
export function formatMonthlyGross(usd: number | null | undefined): string {
  if (usd == null) return "—";
  if (usd >= 1_000_000) return `$${(usd / 1_000_000).toFixed(1)}M/mo`;
  if (usd >= 1_000) return `$${Math.round(usd / 1_000)}k/mo`;
  return `$${Math.round(usd)}/mo`;
}

export type ParcelRevenueSummary = {
  revenue_available: boolean;
  monthly_gross_usd?: number | null;
  monthly_gross_low_usd?: number | null;
  monthly_gross_high_usd?: number | null;
  stalls_estimated?: number | null;
  stalls_low?: number | null;
  stalls_high?: number | null;
  hourly_rate_weighted_usd?: number | null;
  comp_count?: number | null;
  nearest_comp_distance_m?: number | null;
  market_confidence?: number | null;
  market_confidence_tier?: string | null;
  monthly_gross_raw_usd?: number | null;
  market_evidence_notes?: string[] | null;
  demand_occupancy_factor?: number | null;
  occupancy_effective?: number | null;
  distance_to_nearest_demand_m?: number | null;
  poi_demand_intensity?: number | null;
  poi_heavy_anchor_count?: number | null;
  poi_commercial_count?: number | null;
};

const TIER_LABELS: Record<string, string> = {
  high: "High confidence",
  moderate: "Moderate confidence",
  low: "Low confidence",
  very_low: "Very low confidence",
  fallback: "Indicative (no local comps)",
};

export function marketConfidenceLabel(tier: string | null | undefined): string {
  if (!tier) return "";
  return TIER_LABELS[tier] ?? tier;
}

export function formatStallRange(rev: ParcelRevenueSummary | null | undefined): string {
  if (!rev?.revenue_available) return "—";
  const lo = rev.stalls_low ?? rev.stalls_estimated;
  const hi = rev.stalls_high ?? rev.stalls_estimated;
  if (lo == null && hi == null) return "—";
  if (lo === hi) return String(lo ?? hi);
  return `${lo ?? "?"}–${hi ?? "?"}`;
}

export function formatRevenueCell(rev: ParcelRevenueSummary | null | undefined): string {
  if (!rev?.revenue_available) return "—";
  const mid = formatMonthlyGross(rev.monthly_gross_usd);
  if (rev.monthly_gross_low_usd != null && rev.monthly_gross_high_usd != null) {
    return `${mid}`;
  }
  return mid;
}

/** Compact demand line for list tables: nearness + relative size. */
export function formatDemandSignal(rev: ParcelRevenueSummary | null | undefined): string {
  if (!rev) return "—";
  const parts: string[] = [];
  const dist = rev.distance_to_nearest_demand_m;
  if (dist != null) {
    if (dist < 1000) parts.push(`${Math.round(dist)} m`);
    else parts.push(`${(dist / 1000).toFixed(1)} km`);
  }
  const heavy = rev.poi_heavy_anchor_count ?? 0;
  const inten = rev.poi_demand_intensity;
  if (heavy >= 1) {
    parts.push(heavy === 1 ? "1 heavy anchor" : `${heavy} heavy anchors`);
  } else if (inten != null) {
    if (inten >= 25) parts.push(`intensity ${Math.round(inten)} · strong`);
    else if (inten >= 10) parts.push(`intensity ${Math.round(inten)}`);
    else if (inten > 0) parts.push(`intensity ${Math.round(inten)} · weak`);
    else parts.push("no intensity");
  } else if (rev.poi_commercial_count != null) {
    parts.push(`${rev.poi_commercial_count} POIs`);
  }
  if (rev.demand_occupancy_factor != null) {
    parts.push(`${Math.round(rev.demand_occupancy_factor * 100)}% occ.`);
  }
  return parts.length ? parts.join(" · ") : "—";
}

export function demandSignalTitle(rev: ParcelRevenueSummary | null | undefined): string | undefined {
  const notes = rev?.market_evidence_notes?.filter(Boolean);
  if (!notes?.length) return undefined;
  return notes.slice(0, 4).join(" ");
}
