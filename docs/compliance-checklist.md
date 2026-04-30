# Compliance checklist (pilot)

Use this with licensed counsel for your pilot state and deal type. This repository does not provide legal advice.

## Real estate and brokerage

- [ ] Confirm whether your outreach and acquisition activity requires a real estate broker license in the pilot state.
- [ ] If representing third parties, document the agency relationship and fee structure per state rules.

## Contracting and UPL

- [ ] Attorney-reviewed templates for each `deal.primary_structure` in `config/pilot.yaml`.
- [ ] No automated system sends executable contracts without human approval (enforced in workflow + DB constraints).

## Communications (TCPA, CAN-SPAM, state privacy)

- [ ] Channel policy written for each enabled channel in `allowed_outreach_channels`.
- [ ] Suppression list and consent logging implemented before enabling any channel.
- [ ] Review CAN-SPAM requirements for commercial email (if used).

## Data licensing

- [ ] Parcel and zoning dataset licenses allow your storage, derivative scores, and internal display.
- [ ] Attribution and redistribution clauses documented in `docs/data-vendor-shortlist.md`.

## Audit and retention

- [ ] Retention policy for PII (owner names, contacts) and audit logs.
- [ ] Access controls on approval UI and object storage (drafts).
