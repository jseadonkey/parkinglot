import { NextResponse } from "next/server";

import { readApiServerUrl } from "../../../lib/apiServerUrl";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** Public-safe aggregate for partner platform page (single internal endpoint only). */
export async function GET() {
  const internalKey = process.env.INTERNAL_API_KEY?.trim();
  if (!internalKey) {
    return NextResponse.json({ detail: "platform showcase unavailable" }, { status: 503 });
  }
  const base = readApiServerUrl();
  let res: Response;
  try {
    res = await fetch(`${base}/internal/stats/platform-showcase`, {
      headers: { Accept: "application/json", "X-Internal-Key": internalKey },
      cache: "no-store",
    });
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    return NextResponse.json({ detail: `API unreachable: ${msg}` }, { status: 503 });
  }
  const body = await res.text();
  return new NextResponse(body, {
    status: res.status,
    headers: { "Content-Type": "application/json", "Cache-Control": "public, max-age=120" },
  });
}
