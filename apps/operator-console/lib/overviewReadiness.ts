/** Fast overview readiness derived from cached backlog-eta (ops snapshot). */

export type GapStat = {
  count: number;
  pct: number;
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

export type BacklogEtaForReadiness = {
  items: BacklogEtaItem[];
  summary: { decision: string };
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

export function exportReadinessFromBacklogEta(
  eta: BacklogEtaForReadiness,
  parcelTotal: number,
): ExportReadinessSnapshot {
  const items = eta.items;
  const pipeline = backlogItem(items, "pipeline_funnel");
  const demand = backlogItem(items, "demand_distance");
  const poi = backlogItem(items, "baltimore_poi_density");
  const brief = backlogItem(items, "owner_outreach_briefs");
  const poiTotal = poi?.total_count ?? parcelTotal;
  const briefTotal = brief?.total_count ?? poiTotal;

  return {
    parcel_row_total: parcelTotal,
    parcels_missing_footprint: EMPTY,
    parcels_missing_zoning_code: EMPTY,
    parcels_missing_lot_sqft: EMPTY,
    parcels_missing_distance_to_nearest_demand_m: gapFromItem(demand, parcelTotal),
    parcels_missing_poi_commercial_count_400m: gapFromItem(poi, poiTotal),
    parcels_poi_density_candidates: { count: poiTotal, pct: 0 },
    parcels_missing_score_identification: EMPTY,
    parcels_missing_score_entitlement: EMPTY,
    parcels_missing_score_strategic: EMPTY,
    parcels_missing_entitlement_or_strategic: gapFromItem(backlogItem(items, "score_gaps"), parcelTotal),
    parcels_prescreen_qualified: { count: pipeline?.total_count ?? 0, pct: 0 },
    parcels_pipeline_funnel_backlog: gapFromItem(pipeline, pipeline?.total_count ?? parcelTotal),
    parcels_ruled_out_by_prescreen: EMPTY,
    parcels_ruled_out_at_atlas: EMPTY,
    parcels_owner_outreach_targets: { count: briefTotal, pct: 0 },
    parcels_missing_owner_outreach_brief: gapFromItem(brief, briefTotal),
    recommended_next_steps: [eta.summary.decision],
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
