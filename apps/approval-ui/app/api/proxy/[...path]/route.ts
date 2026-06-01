import { NextRequest, NextResponse } from "next/server";

import { readApiServerUrl } from "../../../../lib/apiServerUrl";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** Server-side proxy to the API — avoids browser CORS and wrong PUBLIC_API_URL on the client. */
function allowedPath(path: string): boolean {
  if (path === "approvals" || path.startsWith("approvals/")) return true;
  if (path === "outreach-templates" || path.startsWith("outreach-templates/")) return true;
  return false;
}

export async function GET(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  return proxy(req, ctx, "GET");
}

export async function PUT(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  return proxy(req, ctx, "PUT");
}

export async function POST(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  return proxy(req, ctx, "POST");
}

async function proxy(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }, method: string) {
  const parts = (await ctx.params).path;
  const subpath = parts.join("/");
  if (!allowedPath(subpath)) {
    return NextResponse.json({ detail: "path not allowed" }, { status: 403 });
  }

  const baseClean = readApiServerUrl();
  const qs = req.nextUrl.search;
  const url = `${baseClean}/${subpath}${qs}`;

  const headers: Record<string, string> = { Accept: "application/json" };
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
