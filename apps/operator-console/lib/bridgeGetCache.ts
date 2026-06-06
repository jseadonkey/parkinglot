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

export function statsCacheTtlMs(subpath: string): number {
  if (subpath === "internal/stats/scoring-summary") {
    return SCORING_SUMMARY_TTL_MS;
  }
  return DEFAULT_TTL_MS;
}
