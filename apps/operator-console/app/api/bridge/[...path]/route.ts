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

function backlogEtaFallback(status = 503): NextResponse {
  return NextResponse.json(
    {
      generated_at: new Date().toISOString(),
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
      items: [],
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
