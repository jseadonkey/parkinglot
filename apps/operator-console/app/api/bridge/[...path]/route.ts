import { NextRequest, NextResponse } from "next/server";

/**
 * Server-side proxy to the API — never expose INTERNAL_API_KEY for /internal/* to the browser.
 */
function allowedPath(path: string): boolean {
  if (path.startsWith("internal/")) return true;
  if (path === "approvals" || path.startsWith("approvals/")) return true;
  if (path === "parcels" || path.startsWith("parcels/")) return true;
  if (path === "audit" || path.startsWith("audit")) return true;
  if (path === "workflow-runs" || path.startsWith("workflow-runs/")) return true;
  return false;
}

function isInternalPath(path: string): boolean {
  return path.startsWith("internal/");
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

  const base =
    process.env.API_SERVER_URL?.trim() || process.env.NEXT_PUBLIC_API_URL?.trim() || "http://127.0.0.1:8000";
  const baseClean = base.replace(/\/$/, "");
  const qs = req.nextUrl.search;
  const url = `${baseClean}/${subpath}${qs}`;

  const headers: Record<string, string> = { Accept: "application/json" };
  if (isInternalPath(subpath) && internalKey) {
    headers["X-Internal-Key"] = internalKey;
  }
  const contentType = req.headers.get("Content-Type");
  if (contentType) headers["Content-Type"] = contentType;

  const init: RequestInit = { method, headers, cache: "no-store" };
  if (method !== "GET" && method !== "HEAD") {
    init.body = await req.text();
  }

  let res: Response;
  try {
    res = await fetch(url, init);
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    return NextResponse.json(
      { detail: `API unreachable at ${baseClean}: ${msg}` },
      { status: 503 },
    );
  }
  const body = await res.text();
  return new NextResponse(body, {
    status: res.status,
    headers: { "Content-Type": res.headers.get("Content-Type") || "application/json" },
  });
}

export async function GET(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  return proxy(req, ctx, "GET");
}

export async function POST(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  return proxy(req, ctx, "POST");
}
