import { redirect } from "next/navigation";

/**
 * When Caddy routes `/operator` to approval-ui by mistake, serve a redirect instead of 404.
 * Healthy deploys proxy `/operator` to operator-console and never hit this route.
 */
export default function OperatorEntryRedirect() {
  redirect("/operator/login");
}
