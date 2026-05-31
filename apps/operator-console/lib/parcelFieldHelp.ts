/** Plain-language help for parcel detail fields (Kent + unincorporated King pilot). */

export const FIELD_HELP = {
  apn: "Assessor Parcel Number — the county tax ID for this lot. Use it on King County eReal Property and in GIS.",
  countyFips:
    "53033 = King County, Washington. The pilot only scores parcels in Kent city or unincorporated King County (not Seattle, Bellevue, etc.).",
  zoning:
    "Zoning district code from the Kent or King County unincorporated GIS overlay. Tells you what uses the jurisdiction assigns to this location — not a guarantee surface parking is allowed.",
  lotSqft:
    "Lot area in square feet from the assessor footprint. Entitlement scoring expects at least 5,000 sqft; strategic profile allows down to 4,000 sqft.",
  demandDistance:
    "Straight-line distance in meters from the parcel centroid to the nearest pilot “demand generator” POI (e.g. Kent Station). Entitlement scoring still uses POI when comp market is disabled.",
  parkingComp:
    "Nearest curated paid parking lot or garage from our comp list — distance and screening daily rate. Strategic scoring uses this instead of POI when enabled.",
  cornerLot:
    "True when the parcel touches two or more road frontages (corner visibility). Adds scoring points for both entitlement and strategic profiles.",
  surfaceParking:
    "Whether our rules file marks this zone as allowing primary-use standalone surface parking (unmanned lot target). false = residential, prohibited, or unknown — confirm with counsel. Accessory-only parking for another building is out of scope even when true.",
  ownerRecordIntro:
    "Taxpayer of record from the King County Assessor when loaded. For companies (LLC, Inc, Trust), we then seek underlying people via Washington SOS and licensed vendor skip-trace — not a title guarantee.",
  ownerRecordEmpty:
    "No taxpayer record loaded yet for this parcel. Owner research from the pipeline may still show “Unknown owner” until county assessor data is merged.",
  ownerTaxpayerName:
    "Name on the King County property tax account (may differ from deed holder — verify with counsel before outreach).",
  ownerMailingAddress: "Mailing address on the county tax account for notices and tax bills.",
  ownerKind:
    "Company/entity vs individual heuristic from the taxpayer name. Entities need SOS lookup for registered agent and decision-maker.",
  ownerEnrichmentStatus:
    "How far automated + manual owner research has progressed (mail only → SOS principals → phone/email).",
  ownerSosLookup:
    "Washington Secretary of State business search — use to find registered agent and governors for LLCs and corporations.",
  ownerEntityNextStep:
    "This owner looks like a company. Next we need the registered agent and an underlying person (member, manager, or trustee) from WA SOS or a licensed vendor before outreach.",
  entitlementScore:
    "Atlas entitlement score (0–100) — zoning-forward profile from pilot.yaml. Weights zoning allowance, lot size, corner lot, and POI demand proximity (not parking comps). Computed in the full pipeline. Deal memos need ≥ 55 together with strategic.",
  strategicScore:
    "Beacon strategic score (0–100) — market-forward profile from pilot_strategic.yaml. Weights zoning, lot, corner, and nearest paid parking comp (distance + rate). Comp lookup only runs when entitlement, zoning, and building-share gates pass. Deal memos need ≥ 52 together with entitlement.",
  identificationScore:
    "Cartographer identification prescreen (0–100) — quick score at ingest from roll data only (zoning, lot size, corner). Omits parking comps until pipeline runs. Tracking / funnel progress — not used alone for outreach qualification.",
  ownerTier:
    "How deep owner research ran: basic = assessor roll only; standard = SOS + portfolio peers; deep = also calls vendor webhook when configured.",
  pilotInScope:
    "Whether this parcel centroid falls in the Kent + unincorporated King County pilot (not Seattle, Bellevue, or other cities).",
} as const;

const KING_ZONE_HINTS: Record<string, string> = {
  "R-1": "King County urban residential — parking as primary use generally requires zoning review.",
  "R-4": "King County urban residential — confirm commercial parking allowances on the county zoning map.",
  "R-6": "King County urban residential — higher density; parking lot use still usually needs entitlement path.",
  "R-8": "King County residential/multifamily band — verify primary use before underwriting.",
  "R-12": "King County residential/multifamily band — verify primary use before underwriting.",
  "R-18": "King County residential/multifamily band — verify primary use before underwriting.",
  "R-24": "King County residential/multifamily band — verify primary use before underwriting.",
  "R-48": "King County residential/multifamily band — verify primary use before underwriting.",
  "RA-2.5": "King County rural area — large-lot residential character; parking projects need careful entitlement review.",
  "RA-5": "King County rural area — verify allowed commercial parking uses.",
  "RA-10": "King County rural area — verify allowed commercial parking uses.",
  "CB": "King County community business — commuter/automotive parking has a permit path (KCC 21A.08.060).",
  "NB": "King County neighborhood business — commuter parking permitted; confirm scale for pay-lot use.",
  "O": "King County office district — parking as primary use may be permitted with review.",
  "I": "King County industrial — parking as primary use may be permitted with review.",
  "F": "King County forestry district — not a typical surface-parking target without rezoning.",
  "A-10": "King County agriculture district — confirm allowed uses with county planning.",
  "A-35": "King County agriculture district — confirm allowed uses with county planning.",
};

const KENT_ZONE_HINTS: Record<string, string> = {
  "NR-2": "Kent neighborhood residential — housing-focused; commercial parking is not a listed primary use.",
  "NR-3": "Kent neighborhood residential — verify allowed uses before assuming a parking acquisition.",
  "NR-4A": "Kent neighborhood residential — verify allowed uses before assuming a parking acquisition.",
  "NR-4B": "Kent neighborhood residential — verify allowed uses before assuming a parking acquisition.",
  "NR-L": "Kent neighborhood residential low density — not typical for standalone parking lots.",
  "NR-S": "Kent neighborhood residential special — not typical for standalone parking lots.",
  "GC": "Kent general commercial — commercial parking is minor conditional (permit required).",
  "GC-MU": "Kent general commercial mixed-use — commercial parking minor conditional.",
  "CC": "Kent community commercial — commercial parking minor conditional.",
  "CC-MU": "Kent community commercial mixed-use — commercial parking minor conditional.",
  "NCC": "Kent neighborhood community commercial — commercial parking minor conditional.",
  "DC": "Kent downtown commercial core — parking minor conditional; pedestrian/structured parking preferred.",
  "DCE": "Kent downtown commercial enterprise — parking minor conditional; surface caps apply downtown.",
  "DCE-T": "Kent downtown enterprise transitional overlay — parking minor conditional with design limits.",
  "I1": "Kent light industrial — commercial parking minor conditional.",
  "I2": "Kent medium industrial — commercial parking minor conditional.",
  "I3": "Kent heavy industrial — commercial parking minor conditional.",
  "CM": "Kent commercial manufacturing — commercial parking as primary use is not permitted.",
  "MCR": "Kent Midway commercial-residential — commercial parking conditional use.",
  "MTC-1": "Kent Midway transit community — commercial parking minor conditional; TOD standards apply.",
  "MTC-2": "Kent Midway transit community — commercial parking minor conditional; TOD standards apply.",
};

export function zoningDetailHint(code: string | null, allowsSurface: boolean): string | null {
  if (!code) return null;
  const normalized = code.trim().toUpperCase();
  const fromKing = KING_ZONE_HINTS[normalized];
  const fromKent = KENT_ZONE_HINTS[normalized];
  const base = fromKing ?? fromKent;
  if (base) {
    return allowsSurface
      ? `${base} Our rules mark this code as allowing surface parking — still verify with counsel.`
      : `${base} Our rules do not mark surface parking as explicitly allowed for this code.`;
  }
  if (allowsSurface) {
    return "Zone code not in our hint table, but surface parking flag is true — confirm on the official zoning map.";
  }
  return "Unknown or unlisted zone — rules default to conservative (no surface parking credit until curated in kent_king_surface_parking_rules.yaml).";
}

export function formatDistanceMeters(m: number | null | undefined): string {
  if (m == null || Number.isNaN(m)) return "—";
  const feet = m * 3.28084;
  const miles = m / 1609.344;
  if (m < 1000) {
    return `${m.toFixed(0)} m (${Math.round(feet)} ft)`;
  }
  return `${m.toFixed(0)} m (${miles.toFixed(2)} mi)`;
}

export function demandProximityNote(m: number | null | undefined): string | null {
  if (m == null) return "No POI distance computed — usually missing footprint or demand POIs in pilot config.";
  if (m <= 400) return "Within entitlement POI buffer (400 m) — earns demand points when entitlement uses POI scoring.";
  if (m <= 500) return "Outside entitlement POI buffer (400 m) but inside strategic POI fallback buffer (500 m).";
  return "Outside POI scoring buffers — entitlement may still score via parking comps if configured.";
}

export function parkingCompNote(
  distanceM: number | null | undefined,
  comp: { name?: string; rate_usd_per_day?: number; kind?: string } | null | undefined,
  bufferM = 800,
): string | null {
  if (distanceM == null || !comp) {
    return "No parking comp matched — parcel may be far from curated paid lots or below the min screening rate.";
  }
  const rate = comp.rate_usd_per_day;
  const name = comp.name ?? "nearest comp";
  const kind = comp.kind ? ` (${comp.kind})` : "";
  if (distanceM <= bufferM && rate != null && rate >= 6) {
    return `Within ${bufferM} m of “${name}”${kind} at $${rate.toFixed(0)}/day — earns strategic comp proximity points.`;
  }
  if (distanceM > bufferM) {
    return `Nearest comp “${name}”${kind} at ${distanceM.toFixed(0)} m — outside ${bufferM} m strategic buffer.`;
  }
  return `Nearest comp “${name}”${kind}${rate != null ? ` at $${rate.toFixed(0)}/day` : ""}.`;
}

export function formatCompRate(comp: { rate_usd_per_day?: number; rate_usd_per_hour?: number } | null | undefined): string {
  if (!comp) return "—";
  if (comp.rate_usd_per_day != null && comp.rate_usd_per_day > 0) {
    return `$${comp.rate_usd_per_day.toFixed(0)}/day`;
  }
  if (comp.rate_usd_per_hour != null && comp.rate_usd_per_hour > 0) {
    return `$${comp.rate_usd_per_hour.toFixed(0)}/hr`;
  }
  return "—";
}
