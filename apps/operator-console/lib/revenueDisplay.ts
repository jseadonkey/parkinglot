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
};

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
