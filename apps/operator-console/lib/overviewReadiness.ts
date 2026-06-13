/** Fast overview readiness derived from cached backlog-eta (ops snapshot). */

export type GapStat = {
  count: number;
  pct: number;
  floor?: number;
  target_count?: number;
};

export type ExportReadinessSnapshot = {
  parcel_row_total: number;
  parcels_missing_footprint: GapStat;
  parcels_missing_zoning_code: GapStat;
  parcels_missing_lot_sqft: GapStat;
  parcels_missing_distance_to_nearest_demand_m: GapStat;
  parcels_missing_poi_commercial_count_400m: GapStat;
  parcels_poi_density_candidates: GapStat;
  parcels_missing_score_identification: GapStat;
  parcels_missing_score_entitlement: GapStat;
  parcels_missing_score_strategic: GapStat;
  parcels_missing_entitlement_or_strategic: GapStat;
  parcels_prescreen_qualified: GapStat;
  parcels_pipeline_funnel_backlog: GapStat;
  parcels_ruled_out_by_prescreen: GapStat;
  parcels_ruled_out_at_atlas: GapStat;
  parcels_owner_outreach_targets: GapStat;
  parcels_missing_owner_outreach_brief: GapStat;
  recommended_next_steps: string[];
};

type BacklogEtaItem = {
  key: string;
  backlog_count: number;
  total_count: number;
  backlog_pct: number;
};

type BacklogEtaSummaryForReadiness = {
  decision: string;
  parcel_row_total?: number | null;
  parcels_prescreen_qualified?: number | null;
  prescreen_floor?: number | null;
  parcels_ruled_out_by_prescreen?: number | null;
  parcels_pipeline_funnel_backlog?: number | null;
};

export type BacklogEtaForReadiness = {
  items: BacklogEtaItem[];
  summary: BacklogEtaSummaryForReadiness;
  degraded?: boolean;
};

const EMPTY: GapStat = { count: 0, pct: 0 };

function backlogItem(items: BacklogEtaItem[], key: string): BacklogEtaItem | undefined {
  return items.find((i) => i.key === key);
}

function gapFromItem(it: BacklogEtaItem | undefined, total?: number): GapStat {
  if (!it) return EMPTY;
  const target = total ?? it.total_count;
  return { count: it.backlog_count, pct: it.backlog_pct, target_count: target };
}

function pctOf(part: number, total: number): number {
  if (total <= 0) return 0;
  return Math.round((100 * part) / total * 100) / 100;
}

export function exportReadinessFromBacklogEta(
  eta: BacklogEtaForReadiness,
  parcelTotal: number,
): ExportReadinessSnapshot {
  const items = eta.items;
  const summary = eta.summary;
  const pipeline = backlogItem(items, "pipeline_funnel");
  const demand = backlogItem(items, "demand_distance");
  const poi = backlogItem(items, "baltimore_poi_density");
  const brief = backlogItem(items, "owner_outreach_briefs");
  const poiTotal = poi?.total_count ?? parcelTotal;
  const briefTotal = brief?.total_count ?? poiTotal;
  const total = summary.parcel_row_total ?? parcelTotal;
  const prescreen =
    summary.parcels_prescreen_qualified ??
    pipeline?.total_count ??
    0;
  const prescreenFloor = summary.prescreen_floor ?? undefined;
  const ruledOut = summary.parcels_ruled_out_by_prescreen ?? 0;
  const pipelineBacklog =
    summary.parcels_pipeline_funnel_backlog ?? pipeline?.backlog_count ?? 0;

  return {
    parcel_row_total: total,
    parcels_missing_footprint: EMPTY,
    parcels_missing_zoning_code: EMPTY,
    parcels_missing_lot_sqft: EMPTY,
    parcels_missing_distance_to_nearest_demand_m: gapFromItem(demand, total),
    parcels_missing_poi_commercial_count_400m: gapFromItem(poi, poiTotal),
    parcels_poi_density_candidates: { count: poiTotal, pct: 0 },
    parcels_missing_score_identification: EMPTY,
    parcels_missing_score_entitlement: EMPTY,
    parcels_missing_score_strategic: EMPTY,
    parcels_missing_entitlement_or_strategic: gapFromItem(backlogItem(items, "score_gaps"), total),
    parcels_prescreen_qualified: {
      count: prescreen,
      pct: pctOf(prescreen, total),
      floor: prescreenFloor,
    },
    parcels_pipeline_funnel_backlog: gapFromItem(
      pipeline ? { ...pipeline, backlog_count: pipelineBacklog } : undefined,
      prescreen || pipeline?.total_count || total,
    ),
    parcels_ruled_out_by_prescreen: { count: ruledOut, pct: pctOf(ruledOut, total) },
    parcels_ruled_out_at_atlas: EMPTY,
    parcels_owner_outreach_targets: { count: briefTotal, pct: 0 },
    parcels_missing_owner_outreach_brief: gapFromItem(brief, briefTotal),
    recommended_next_steps: [summary.decision],
  };
}

export function isBacklogEtaForReadiness(s: unknown): s is BacklogEtaForReadiness {
  return (
    typeof s === "object" &&
    s !== null &&
    "summary" in s &&
    "items" in s &&
    Array.isArray((s as BacklogEtaForReadiness).items) &&
    (s as BacklogEtaForReadiness).degraded !== true
  );
}
