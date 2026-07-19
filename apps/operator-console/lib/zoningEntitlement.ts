/** Article 32 principal-use parking entitlement tiers for operator UI. */

export type ZoningEntitlementTier =
  | "permitted"
  | "conditional"
  | "provisional"
  | "council"
  | "excluded"
  | "unknown";

export function tierLabel(tier: string | null | undefined): string {
  switch ((tier || "").toLowerCase()) {
    case "permitted":
      return "Permitted (P)";
    case "conditional":
      return "Conditional";
    case "provisional":
      return "Provisional (WAZA)";
    case "council":
      return "Council ordinance";
    case "excluded":
      return "Not allowed";
    default:
      return "Unknown";
  }
}

export function tierBadgeClass(tier: string | null | undefined): string {
  switch ((tier || "").toLowerCase()) {
    case "permitted":
      return "badge badge-ok";
    case "conditional":
      return "badge badge-warn";
    case "provisional":
      return "badge badge-warn";
    case "council":
      return "badge badge-muted";
    case "excluded":
      return "badge badge-bad";
    default:
      return "badge badge-muted";
  }
}

export function symbolHint(symbol: string | null | undefined): string {
  const s = (symbol || "").toUpperCase();
  if (s === "P") return "Principal parking lot permitted by right.";
  if (s === "CB") return "BMZA conditional use — hearing required.";
  if (s === "M") return "Minor conditional use — hearing or admin review may be required.";
  if (s === "PV") return "WAZA commercial/mixed/industrial class — provisional prospect only; counsel review before outreach.";
  if (s === "CO") return "Mayor & City Council ordinance required.";
  if (s === "NOT_LISTED") return "Principal parking lot not listed in use table.";
  if (s === "ACCESSORY_ONLY") return "Accessory parking only in this district.";
  return "";
}
