import { headers } from "next/headers";
import { redirect } from "next/navigation";

/**
 * Legacy URL `/operator/login` — forward to the shared site login at `/login`.
 * (Avoid redirect() with a relative `/login` here: basePath would loop to /operator/login.)
 */
export default async function LegacyOperatorLoginPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string }>;
}) {
  const sp = await searchParams;
  const h = await headers();
  const host = h.get("x-forwarded-host") ?? h.get("host") ?? "";
  const proto = h.get("x-forwarded-proto") ?? "https";
  const defaultReturn = "/operator";
  const nextDest =
    typeof sp.next === "string" && sp.next.startsWith("/") ? sp.next : defaultReturn;
  redirect(`${proto}://${host}/login?next=${encodeURIComponent(nextDest)}`);
}
