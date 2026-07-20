/** Short TTL cache for read-heavy bridge GETs (overview stats). */

type Entry = { body: string; status: number; expiresAt: number };

const store = new Map<string, Entry>();

const DEFAULT_TTL_MS = 60_000;
/** Scoring summary scans many parcel_scores rows — cache longer on repeat overview loads. */
const SCORING_SUMMARY_TTL_MS = 300_000;

export function cacheKey(path: string, query = ""): string {
  return query ? `${path}?${query}` : path;
}

export function readBridgeCache(key: string): Entry | null {
  const hit = store.get(key);
  if (!hit) return null;
  if (Date.now() > hit.expiresAt) {
    store.delete(key);
    return null;
  }
  return hit;
}

export function writeBridgeCache(key: string, status: number, body: string, ttlMs = DEFAULT_TTL_MS): void {
  store.set(key, { status, body, expiresAt: Date.now() + ttlMs });
}

export function isStatsCachePath(subpath: string): boolean {
  return (
    subpath === "internal/stats/pilot-scope" ||
    subpath === "internal/stats/scoring-summary" ||
    subpath === "internal/stats/backlog-eta" ||
    subpath === "internal/stats/export-readiness"
  );
}

function isPipelineCachePath(subpath: string): boolean {
  return subpath === "internal/pipeline/outreach-board" || subpath === "internal/pipeline/deal-progress";
}

function isHeavyReadCachePath(subpath: string): boolean {
  return (
    subpath === "internal/parcels/scored-list" ||
    subpath === "internal/owners/portfolios-ranked" ||
    subpath.startsWith("internal/owners/")
  );
}

/** TTL for bridge GET responses we cache server-side (null = no cache). */
export function bridgeCacheTtlMs(subpath: string): number | null {
  if (subpath === "internal/stats/scoring-summary") {
    return SCORING_SUMMARY_TTL_MS;
  }
  if (isStatsCachePath(subpath)) {
    return DEFAULT_TTL_MS;
  }
  if (isPipelineCachePath(subpath)) {
    return DEFAULT_TTL_MS;
  }
  if (isHeavyReadCachePath(subpath)) {
    return DEFAULT_TTL_MS;
  }
  return null;
}

/** Upstream fetch timeout — heavy stats scans exceed the old 15s cap. */
export function bridgeTimeoutMs(subpath: string): number {
  if (subpath === "internal/stats/backlog-eta") {
    return 8_000;
  }
  if (subpath === "internal/stats/export-readiness") {
    return 180_000;
  }
  if (subpath === "internal/stats/scoring-summary") {
    return 60_000;
  }
  if (isStatsCachePath(subpath)) {
    return 30_000;
  }
  if (subpath.startsWith("internal/pipeline/")) {
    return 90_000;
  }
  if (subpath.startsWith("internal/parcels/") || subpath.startsWith("internal/owners/")) {
    return 120_000;
  }
  if (subpath.startsWith("parcels/")) {
    return 120_000;
  }
  return 45_000;
}
