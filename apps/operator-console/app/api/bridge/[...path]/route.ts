import { NextRequest, NextResponse } from "next/server";

/**
 * Server-side proxy to the API with X-Internal-Key — never expose the key to the browser.
 * Allowlist GET paths under /internal/* needed by the operator console.
 */
function allowedInternalPath(path: string): boolean {
  if (path.startsWith("internal/stats/")) return true;
  if (path.startsWith("internal/owners/")) return true;
  if (path.startsWith("internal/pipeline/")) return true;
  return false;
}

export async function GET(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const internalKey = process.env.INTERNAL_API_KEY?.trim();
  if (!internalKey) {
    return NextResponse.json({ detail: "INTERNAL_API_KEY not configured on operator-console" }, { status: 503 });
  }

  const parts = (await ctx.params).path;
  const subpath = parts.join("/");
  if (!allowedInternalPath(subpath)) {
    return NextResponse.json({ detail: "path not allowed" }, { status: 403 });
  }

  const base =
    process.env.API_SERVER_URL?.trim() || process.env.NEXT_PUBLIC_API_URL?.trim() || "http://127.0.0.1:8000";
  const baseClean = base.replace(/\/$/, "");
  const qs = req.nextUrl.search;
  const url = `${baseClean}/${subpath}${qs}`;

  const res = await fetch(url, {
    headers: {
      Accept: "application/json",
      "X-Internal-Key": internalKey,
    },
    cache: "no-store",
  });

  const body = await res.text();
  return new NextResponse(body, {
    status: res.status,
    headers: {
      "Content-Type": res.headers.get("Content-Type") || "application/json",
    },
  });
}
