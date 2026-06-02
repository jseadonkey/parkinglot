/** Parse skip-trace / vendor lookup from parcel owner_outreach_brief JSON. */

export type VendorContact = {
  channel: string;
  value: string;
  label: string | null;
};

export type VendorLookup = {
  provider: string;
  outcome: string;
  http_status: number | null;
  notes: string | null;
  contacts: VendorContact[];
  error_detail: string | null;
};

export type SkipTraceView = {
  hasBrief: boolean;
  recordedOwner: string | null;
  researchTier: string | null;
  computedAt: string | null;
  vendor: VendorLookup | null;
  /** Assessor-roll contacts from ingest (not skip-trace). */
  rollContacts: { kind: string; value: string; source: string | null }[];
};

const OUTCOME_LABELS: Record<string, string> = {
  hit: "Completed — vendor returned contacts",
  skipped_disabled: "Not run — vendor lookup disabled in config",
  skipped_no_url: "Not run — no vendor URL configured",
  skipped_tier: "Skipped — parcel below score threshold for vendor lookup",
  error: "Failed — vendor request error",
};

export function outcomeLabel(outcome: string): string {
  return OUTCOME_LABELS[outcome] ?? outcome.replaceAll("_", " ");
}

export function outcomeBadgeClass(outcome: string): string {
  if (outcome === "hit") return "badge-ok";
  if (outcome === "error") return "badge-err";
  if (outcome.startsWith("skipped")) return "badge-warn";
  return "badge";
}

export function parseSkipTraceView(brief: Record<string, unknown> | null | undefined): SkipTraceView {
  if (!brief || typeof brief !== "object") {
    return {
      hasBrief: false,
      recordedOwner: null,
      researchTier: null,
      computedAt: null,
      vendor: null,
      rollContacts: [],
    };
  }

  const rawVendor = brief.vendor_lookup;
  let vendor: VendorLookup | null = null;
  if (rawVendor && typeof rawVendor === "object") {
    const v = rawVendor as Record<string, unknown>;
    const contactsRaw = Array.isArray(v.contacts) ? v.contacts : [];
    vendor = {
      provider: String(v.provider ?? "webhook"),
      outcome: String(v.outcome ?? "unknown"),
      http_status: typeof v.http_status === "number" ? v.http_status : null,
      notes: v.notes != null ? String(v.notes) : null,
      error_detail: v.error_detail != null ? String(v.error_detail) : null,
      contacts: contactsRaw
        .filter((c): c is Record<string, unknown> => typeof c === "object" && c !== null)
        .map((c) => ({
          channel: String(c.channel ?? "unknown"),
          value: String(c.value ?? ""),
          label: c.label != null ? String(c.label) : null,
        }))
        .filter((c) => c.value.trim().length > 0),
    };
  }

  const rollRaw = Array.isArray(brief.contact_points) ? brief.contact_points : [];
  const rollContacts = rollRaw
    .filter((c): c is Record<string, unknown> => typeof c === "object" && c !== null)
    .map((c) => ({
      kind: String(c.kind ?? "unknown"),
      value: String(c.value ?? ""),
      source: c.source != null ? String(c.source) : null,
    }))
    .filter((c) => c.value.trim().length > 0);

  return {
    hasBrief: true,
    recordedOwner: brief.recorded_owner_one_liner != null ? String(brief.recorded_owner_one_liner) : null,
    researchTier: brief.owner_research_tier != null ? String(brief.owner_research_tier) : null,
    computedAt: brief.computed_at != null ? String(brief.computed_at) : null,
    vendor,
    rollContacts,
  };
}

export function skipTraceRan(view: SkipTraceView): boolean {
  return view.vendor?.outcome === "hit";
}
