import { NextRequest, NextResponse } from "next/server";

import { readApiServerUrl } from "../../../../lib/apiServerUrl";
import {
  bridgeCacheTtlMs,
  bridgeTimeoutMs,
  cacheKey,
  readBridgeCache,
  writeBridgeCache,
} from "../../../../lib/bridgeGetCache";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * Server-side proxy to the API — never expose INTERNAL_API_KEY for /internal/* to the browser.
 */
function allowedPath(path: string): boolean {
  if (path.startsWith("internal/")) return true;
  if (path === "approvals" || path.startsWith("approvals/")) return true;
  if (path === "parcels" || path.startsWith("parcels/")) return true;
  if (path === "audit" || path.startsWith("audit")) return true;
  if (path === "workflow-runs" || path.startsWith("workflow-runs/")) return true;
  if (path === "outreach-templates" || path.startsWith("outreach-templates/")) return true;
  return false;
}

function isInternalPath(path: string): boolean {
  return path.startsWith("internal/");
}

function backlogEtaFallbackItem({
  key,
  label,
  recommendation,
  why,
}: {
  key: string;
  label: string;
  recommendation: string;
  why: string;
}) {
  return {
    key,
    label,
    status: "unknown",
    active_now: false,
    backlog_count: 0,
    total_count: 0,
    backlog_pct: 0,
    unit: "items",
    value: "selective",
    work_type: "ops_status",
    assumed_units_per_day: null,
    eta_days: null,
    eta_label: "Unavailable while bridge is degraded",
    eta_confidence: "unknown",
    recommendation,
    why,
    server_load_tier: "low",
    server_load_note: "Live server-load details are unavailable until the API responds.",
  };
}

function backlogEtaFallback(status = 503): NextResponse {
  return NextResponse.json(
    {
      generated_at: new Date().toISOString(),
      server_load: {
        pressure_level: "unknown",
        assessed_at: null,
        parking_queue_depth: 0,
        score_gaps: 0,
        ident_score_gaps: 0,
        ent_score_gaps: 0,
        primary_drivers: ["Backlog ETA API did not respond before the operator bridge fallback."],
        signals: [],
        scheduled_jobs: [
          {
            name: "Idle-work tick",
            schedule_utc: "*/15 * * * *",
            load_tier: "low",
            status: "active",
            note: "When queues are empty, statewide ingest/scoring should continue on the next idle tick.",
          },
          {
            name: "Priority pipeline enqueue",
            schedule_utc: "*/2 hours",
            load_tier: "high",
            status: "active",
            note: "Exact backlog counts are unavailable while the bridge is degraded.",
          },
        ],
        throttles: [],
      },
      summary: {
        active_parking_queue_depth: 0,
        active_slack_queue_depth: 0,
        workers_online: false,
        worker_detail: `Backlog ETA temporarily unavailable (upstream ${status}).`,
        ops_auto_fix_enabled: false,
        data_checked_at: null,
        data_source: "bridge_fallback",
        high_value_remaining: 0,
        decision: "Backlog ETA is temporarily unavailable. Health checks may still be OK; refresh in a minute.",
      },
      inventory: {
        region_name: null,
        records_gathered: 0,
        records_gathering: 0,
        counties_gathered: 0,
        counties_to_be_gathered: 0,
        pilot_county_count: 0,
        parking_queue_depth: 0,
        pipeline_backlog: 0,
        wa_rollout_paused: null,
        county_breakdown_pending: true,
        gathering_note: "Live gathering counts unavailable while the bridge is degraded.",
      },
      items: [
        backlogEtaFallbackItem({
          key: "bridge_status",
          label: "Backlog API bridge",
          recommendation:
            "Treat counts as unknown until the API responds. If this persists, check API logs and deploy the backlog timeout fix.",
          why:
            "The operator console is up, but its server-side bridge could not get a live backlog ETA response.",
        }),
        backlogEtaFallbackItem({
          key: "statewide_idle_work",
          label: "Statewide idle-work tick",
          recommendation:
            "If queues are empty, automated statewide ingest/scoring should resume on the next idle-work tick.",
          why:
            "Baltimore rows can be complete while Washington county ingest and post-ingest scoring still move forward.",
        }),
        backlogEtaFallbackItem({
          key: "draft_storage_reruns",
          label: "Draft-storage failure reruns",
          recommendation:
            "After the retry controls are deployed, use Deals or Outreach to rerun any remaining draft-storage failures.",
          why:
            "NoSuchBucket failures from before bucket provisioning are recoverable by rerunning the pipeline.",
        }),
      ],
      degraded: true,
    },
    {
      status: 200,
      headers: {
        "X-Bridge-Degraded": "true",
      },
    },
  );
}

async function proxy(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }, method: string) {
  const parts = (await ctx.params).path;
  const subpath = parts.join("/");
  if (!allowedPath(subpath)) {
    return NextResponse.json({ detail: "path not allowed" }, { status: 403 });
  }

  const internalKey = process.env.INTERNAL_API_KEY?.trim();
  if (isInternalPath(subpath) && !internalKey) {
    return NextResponse.json({ detail: "INTERNAL_API_KEY not configured on operator-console" }, { status: 503 });
  }

  const baseClean = readApiServerUrl();
  const qs = req.nextUrl.searchParams.toString();
  const url = `${baseClean}/${subpath}${qs ? `?${qs}` : ""}`;
  const cacheTtlMs = method === "GET" ? bridgeCacheTtlMs(subpath) : null;
  const statsCacheKey = cacheTtlMs !== null ? cacheKey(subpath, qs) : null;

  if (statsCacheKey) {
    const cached = readBridgeCache(statsCacheKey);
    if (cached) {
      return new NextResponse(cached.body, {
        status: cached.status,
        headers: {
          "Content-Type": "application/json",
          "X-Bridge-Cache": "HIT",
        },
      });
    }
  }

  const headers: Record<string, string> = { Accept: "application/json" };
  if (isInternalPath(subpath) && internalKey) {
    headers["X-Internal-Key"] = internalKey;
  }
  const contentType = req.headers.get("Content-Type");
  if (contentType) headers["Content-Type"] = contentType;

  const controller = new AbortController();
  const timeoutMs = bridgeTimeoutMs(subpath);
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  const init: RequestInit = { method, headers, cache: "no-store", signal: controller.signal };
  if (method !== "GET" && method !== "HEAD") {
    init.body = await req.text();
  }

  let res: Response;
  try {
    res = await fetch(url, init);
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    if (subpath === "internal/stats/backlog-eta") {
      return backlogEtaFallback();
    }
    return NextResponse.json(
      { detail: `API unreachable at ${baseClean}: ${msg}` },
      { status: 503 },
    );
  } finally {
    clearTimeout(timeout);
  }
  const body = await res.text();
  if (subpath === "internal/stats/backlog-eta" && !res.ok) {
    return backlogEtaFallback(res.status);
  }
  if (statsCacheKey && res.ok) {
    writeBridgeCache(statsCacheKey, res.status, body, cacheTtlMs ?? 60_000);
  }
  return new NextResponse(body, {
    status: res.status,
    headers: {
      "Content-Type": res.headers.get("Content-Type") || "application/json",
      ...(statsCacheKey ? { "X-Bridge-Cache": "MISS" } : {}),
    },
  });
}

export async function GET(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  return proxy(req, ctx, "GET");
}

export async function POST(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  return proxy(req, ctx, "POST");
}

export async function PUT(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  return proxy(req, ctx, "PUT");
}
