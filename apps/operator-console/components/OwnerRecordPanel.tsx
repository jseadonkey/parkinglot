import { DetailRow } from "./DetailRow";
import { FIELD_HELP } from "../lib/parcelFieldHelp";

export type OwnerContact = {
  channel: string;
  value: string;
  label?: string | null;
  source?: string | null;
  verified?: boolean;
  confidence?: number | null;
};

export type OwnerPerson = {
  name?: string | null;
  role?: string | null;
  address?: string | null;
  phone?: string | null;
  email?: string | null;
  source?: string | null;
};

export type OwnerFieldCandidate = {
  value: string;
  source?: string | null;
  label?: string | null;
  confidence?: number | null;
};

export type SkipTraceSummary = {
  provider?: string | null;
  outcome?: string | null;
  matched_person?: string | null;
  notes?: string | null;
  contacts: OwnerContact[];
};

export type OwnerRecord = {
  taxpayer_name: string | null;
  taxpayer_attn: string | null;
  mailing_address: string | null;
  situs_address: string | null;
  name_candidates: OwnerFieldCandidate[];
  mailing_address_candidates: OwnerFieldCandidate[];
  situs_address_candidates: OwnerFieldCandidate[];
  appraised_land: number | null;
  appraised_improvements: number | null;
  property_type: string | null;
  erealproperty_url: string | null;
  data_source: string | null;
  enriched_at: string | null;
  owner_kind: string | null;
  is_entity: boolean;
  enrichment_status: string | null;
  sos_search_url: string | null;
  registered_agent: string | null;
  registered_agent_address: string | null;
  principal_address: string | null;
  underlying_persons: OwnerPerson[];
  contacts: OwnerContact[];
  enrichment_gaps: string[];
  next_steps: string[];
  owner_research_tier: string | null;
  skip_trace: SkipTraceSummary | null;
};

function formatUsd(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "—";
  return `$${Math.round(n).toLocaleString()}`;
}

function propertyTypeLabel(code: string | null | undefined): string {
  if (!code) return "—";
  const c = code.trim().toUpperCase();
  if (c === "R") return "Residential (assessor code R)";
  if (c === "C") return "Commercial (assessor code C)";
  return code;
}

function hasOwnerData(record: OwnerRecord): boolean {
  return Boolean(
    record.taxpayer_name ||
      record.mailing_address ||
      record.situs_address ||
      record.name_candidates.length > 0 ||
      record.mailing_address_candidates.length > 0 ||
      record.appraised_land != null ||
      record.appraised_improvements != null,
  );
}

function statusLabel(status: string | null | undefined): string {
  if (!status) return "Not started";
  const map: Record<string, string> = {
    missing_taxpayer: "No taxpayer on file",
    roll_only: "Tax roll only",
    entity_needs_sos: "Company — needs SOS lookup",
    entity_mailing_only: "Company — mailing only",
    entity_principals_partial: "Company — partial principals",
    entity_contacts_found: "Company — contacts found",
    individual_mailing_only: "Individual — mailing only",
    individual_contacts_partial: "Individual — partial contacts",
  };
  return map[status] ?? status.replaceAll("_", " ");
}

function sourceTag(source: string | null | undefined): string {
  if (!source) return "";
  if (source === "skip_trace") return "Skip trace";
  return source.replaceAll("_", " ");
}

function roleLabel(role: string | null | undefined): string {
  if (!role) return "";
  if (role === "skip_trace_match") return "Skip trace match";
  return role.replaceAll("_", " ");
}

function CandidateList({
  title,
  help,
  items,
  emptyLabel = "—",
}: {
  title: string;
  help?: string;
  items: OwnerFieldCandidate[];
  emptyLabel?: string;
}) {
  if (items.length === 0) {
    return (
      <DetailRow label={title} help={help ?? ""} value={emptyLabel} />
    );
  }
  if (items.length === 1) {
    const c = items[0];
    return (
      <DetailRow
        label={title}
        help={help ?? ""}
        value={
          <>
            {c.value}
            {c.label || c.source ? (
              <span className="muted" style={{ display: "block", fontSize: "0.78rem", marginTop: "0.15rem" }}>
                {[c.label, c.source ? `via ${sourceTag(c.source)}` : null].filter(Boolean).join(" · ")}
              </span>
            ) : null}
          </>
        }
      />
    );
  }
  return (
    <>
      <h3 style={{ fontSize: "0.9rem", margin: "0.75rem 0 0.35rem" }}>{title}</h3>
      {help ? <p className="muted" style={{ fontSize: "0.78rem", margin: "0 0 0.35rem" }}>{help}</p> : null}
      <ul className="score-breakdown">
        {items.map((c, i) => (
          <li key={`${c.value}-${i}`}>
            <strong>{c.value}</strong>
            {(c.label || c.source) && (
              <span className="muted" style={{ display: "block", fontSize: "0.78rem" }}>
                {[c.label, c.source ? `via ${sourceTag(c.source)}` : null].filter(Boolean).join(" · ")}
              </span>
            )}
          </li>
        ))}
      </ul>
    </>
  );
}

export function OwnerRecordPanel({ record }: { record: OwnerRecord }) {
  const loaded = hasOwnerData(record);
  const names =
    record.name_candidates.length > 0
      ? record.name_candidates
      : record.taxpayer_name
        ? [{ value: record.taxpayer_name, source: record.data_source, label: "Tax account name" }]
        : [];
  const mailings =
    record.mailing_address_candidates.length > 0
      ? record.mailing_address_candidates
      : record.mailing_address
        ? [{ value: record.mailing_address, source: record.data_source, label: "Tax account mailing" }]
        : [];
  const situs =
    record.situs_address_candidates.length > 0
      ? record.situs_address_candidates
      : record.situs_address
        ? [{ value: record.situs_address, source: record.data_source, label: "Property / situs address" }]
        : [];
  const phones = record.contacts.filter((c) => c.channel === "phone");
  const emails = record.contacts.filter((c) => c.channel === "email");
  const skipTrace = record.skip_trace;
  const skipPhones = skipTrace?.contacts.filter((c) => c.channel === "phone") ?? [];
  const skipEmails = skipTrace?.contacts.filter((c) => c.channel === "email") ?? [];

  return (
    <section aria-labelledby="owner-record-heading">
      <h2 id="owner-record-heading">Owner / taxpayer record</h2>
      <p className="muted">{FIELD_HELP.ownerRecordIntro}</p>
      <div className="panel">
        {!loaded ? (
          <p className="muted">{FIELD_HELP.ownerRecordEmpty}</p>
        ) : (
          <>
            <DetailRow
              label="Owner type"
              help={FIELD_HELP.ownerKind}
              value={
                record.is_entity ? (
                  <span className="badge">Company / entity</span>
                ) : record.owner_kind === "individual" ? (
                  <span className="badge">Individual</span>
                ) : (
                  "—"
                )
              }
            />
            <DetailRow
              label="Enrichment status"
              help={FIELD_HELP.ownerEnrichmentStatus}
              value={statusLabel(record.enrichment_status)}
            />
            {record.owner_research_tier ? (
              <DetailRow
                label="Research tier"
                help={FIELD_HELP.ownerTier}
                value={<span className="badge">{record.owner_research_tier}</span>}
              />
            ) : null}
            <CandidateList
              title={names.length > 1 ? "Likely owner / taxpayer names" : "Taxpayer name"}
              help={FIELD_HELP.ownerTaxpayerName}
              items={names}
            />
            {record.taxpayer_attn ? (
              <DetailRow
                label="Attention / c/o line"
                help="Care-of or PO box line on the county tax account, when present."
                value={record.taxpayer_attn}
              />
            ) : null}
            <CandidateList
              title={mailings.length > 1 ? "Likely mailing addresses" : "Mailing address"}
              help={FIELD_HELP.ownerMailingAddress}
              items={mailings}
            />
            {situs.length > 0 ? (
              <CandidateList
                title={situs.length > 1 ? "Likely property / situs addresses" : "Property / situs address"}
                help="On-site address for the parcel — may differ from tax mailing."
                items={situs}
              />
            ) : null}
            {record.is_entity && record.sos_search_url ? (
              <DetailRow
                label="Washington SOS lookup"
                help={FIELD_HELP.ownerSosLookup}
                value={
                  <a href={record.sos_search_url} target="_blank" rel="noreferrer">
                    Search entity on WA SOS →
                  </a>
                }
              />
            ) : null}
            {record.registered_agent ? (
              <DetailRow
                label="Registered agent (SOS)"
                help="From Washington SOS CCFS when available — verify before outreach."
                value={record.registered_agent}
              />
            ) : null}
            {record.registered_agent_address ? (
              <DetailRow
                label="Registered agent address"
                help="Mailing address for the registered agent from SOS."
                value={record.registered_agent_address}
              />
            ) : null}
            {record.principal_address ? (
              <DetailRow
                label="Principal / registry address"
                help="Address tied to registry match when available."
                value={record.principal_address}
              />
            ) : null}
            {record.underlying_persons.length > 0 ? (
              <>
                <h3 style={{ fontSize: "0.9rem", margin: "0.75rem 0 0.35rem" }}>Underlying people</h3>
                <ul className="score-breakdown">
                  {record.underlying_persons.map((p, i) => (
                    <li key={`${p.name}-${i}`}>
                      <strong>{p.name ?? "—"}</strong>
                      {p.role ? ` (${roleLabel(p.role)})` : ""}
                      {p.source === "skip_trace" ? (
                        <span className="badge" style={{ marginLeft: "0.35rem" }}>
                          Skip trace
                        </span>
                      ) : null}
                      {p.address ? ` — ${p.address}` : ""}
                      {p.phone ? ` · phone: ${p.phone}` : ""}
                      {p.email ? ` · email: ${p.email}` : ""}
                    </li>
                  ))}
                </ul>
              </>
            ) : record.is_entity ? (
              <p className="muted" style={{ marginTop: "0.75rem" }}>
                {FIELD_HELP.ownerEntityNextStep}
              </p>
            ) : null}
            {skipTrace && (skipPhones.length > 0 || skipEmails.length > 0) ? (
              <>
                <h3 style={{ fontSize: "0.9rem", margin: "0.75rem 0 0.35rem" }}>
                  Skip trace (BatchData)
                </h3>
                {skipTrace.matched_person ? (
                  <p className="muted" style={{ fontSize: "0.85rem", margin: "0 0 0.35rem" }}>
                    Matched person: <strong>{skipTrace.matched_person}</strong>
                  </p>
                ) : null}
                {skipTrace.notes ? (
                  <p className="muted" style={{ fontSize: "0.78rem", margin: "0 0 0.35rem" }}>
                    {skipTrace.notes}
                  </p>
                ) : null}
                <ul className="score-breakdown">
                  {skipPhones.map((c, i) => (
                    <li key={`st-p-${c.value}-${i}`}>
                      Phone: <strong>{c.value}</strong>
                      <span className="badge" style={{ marginLeft: "0.35rem" }}>
                        Skip trace
                      </span>
                      {c.label ? (
                        <span className="muted" style={{ display: "block", fontSize: "0.78rem" }}>
                          {c.label}
                        </span>
                      ) : null}
                    </li>
                  ))}
                  {skipEmails.map((c, i) => (
                    <li key={`st-e-${c.value}-${i}`}>
                      Email: <strong>{c.value}</strong>
                      <span className="badge" style={{ marginLeft: "0.35rem" }}>
                        Skip trace
                      </span>
                      {c.label ? (
                        <span className="muted" style={{ display: "block", fontSize: "0.78rem" }}>
                          {c.label}
                        </span>
                      ) : null}
                    </li>
                  ))}
                </ul>
              </>
            ) : null}
            {(phones.length > 0 || emails.length > 0) && (
              <>
                <h3 style={{ fontSize: "0.9rem", margin: "0.75rem 0 0.35rem" }}>
                  {phones.length + emails.length > 1 ? "Likely phone & email" : "Phone & email"}
                </h3>
                <ul className="score-breakdown">
                  {phones.map((c, i) => (
                    <li key={`p-${c.value}-${i}`}>
                      Phone: <strong>{c.value}</strong>
                      {(c.label || c.source) && (
                        <span className="muted" style={{ display: "block", fontSize: "0.78rem" }}>
                          {[c.label, c.source ? `via ${sourceTag(c.source)}` : null].filter(Boolean).join(" · ")}
                        </span>
                      )}
                    </li>
                  ))}
                  {emails.map((c, i) => (
                    <li key={`e-${c.value}-${i}`}>
                      Email: <strong>{c.value}</strong>
                      {(c.label || c.source) && (
                        <span className="muted" style={{ display: "block", fontSize: "0.78rem" }}>
                          {[c.label, c.source ? `via ${sourceTag(c.source)}` : null].filter(Boolean).join(" · ")}
                        </span>
                      )}
                    </li>
                  ))}
                </ul>
              </>
            )}
            <DetailRow
              label="Appraised land"
              help="King County assessor land value at enrichment time."
              value={formatUsd(record.appraised_land)}
            />
            <DetailRow
              label="Appraised improvements"
              help="King County assessor building/improvement value — $0 often means vacant or unimproved roll."
              value={formatUsd(record.appraised_improvements)}
            />
            <DetailRow
              label="Assessor property type"
              help="Single-letter King County roll code (R=residential, C=commercial, etc.)."
              value={propertyTypeLabel(record.property_type)}
            />
            {record.erealproperty_url ? (
              <DetailRow
                label="County portal"
                help="Official King County eReal Property detail page for this parcel."
                value={
                  <a href={record.erealproperty_url} target="_blank" rel="noreferrer">
                    Open eReal Property →
                  </a>
                }
              />
            ) : null}
            {record.enrichment_gaps.length > 0 ? (
              <>
                <h3 style={{ fontSize: "0.9rem", margin: "0.75rem 0 0.35rem" }}>Still needed</h3>
                <ul className="score-breakdown">
                  {record.enrichment_gaps.map((g) => (
                    <li key={g}>{g}</li>
                  ))}
                </ul>
              </>
            ) : null}
            {record.next_steps.length > 0 ? (
              <>
                <h3 style={{ fontSize: "0.9rem", margin: "0.75rem 0 0.35rem" }}>Next steps</h3>
                <ol className="score-breakdown" style={{ paddingLeft: "1.2rem" }}>
                  {record.next_steps.map((s) => (
                    <li key={s}>{s}</li>
                  ))}
                </ol>
              </>
            ) : null}
            {record.data_source || record.enriched_at ? (
              <p className="muted" style={{ marginTop: "0.75rem", fontSize: "0.78rem" }}>
                {record.data_source ? `Source: ${record.data_source}` : null}
                {record.data_source && record.enriched_at ? " · " : null}
                {record.enriched_at ? `Updated ${record.enriched_at.slice(0, 19)} UTC` : null}
              </p>
            ) : null}
          </>
        )}
      </div>
    </section>
  );
}
