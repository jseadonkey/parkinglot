# Operations model — Kent + unincorporated King pilot

**This is the business definition for scoring, zoning flags, and outreach.** Not legal advice.

## What we do

We **master-lease land** to operate **standalone, unmanned surface parking lots**:

- Pay-by-app or similar — **no attendants, no valet, no staffed booths**
- **Surface parking as the primary use** on the leased portion (not accessory parking for someone else’s building)
- Deal structure default: **`master_lease`** (see `config/pilot.yaml` → `deal.primary_structure`)

## What we do not pursue (out of scope)

- Accessory parking only (serving another tenant’s building as the sole use)
- Attended or valet operations
- Structured garages we would staff
- Mixed-use ground leases where parking is not the primary operation

## Partially developed lots (important exception)

We **only** target standalone unmanned lots, but a parcel **may still qualify** when:

- The owner has **developed part of the lot** (e.g. a building on one half), and
- A **suitable undeveloped portion** remains for unmanned surface parking, and
- Zoning and access allow parking on that portion (counsel review required)

The **building-value prescreen** (assessed building ≤ 70% of land + building total) is a **roll-data proxy** for “room left on the lot.” It is not a site visit or survey.

## How this connects to the codebase

| Area | File / behavior |
|------|-----------------|
| Canonical config | `config/pilot.yaml` → `deal.operations` |
| Zoning suitability | `data/zoning/wa/kent_king_surface_parking_rules.yaml` — primary-use commercial/commuter/automotive parking paths |
| Building prescreen | `config/pilot_parcel_prescreen.yaml` + pipeline comp gate — filters heavily built-out sites |
| Operator UI | `apps/operator-console/lib/operationsModel.ts` |
| Agent memory | `.cursor/rules/operations-model.mdc` |

## Related docs

- `docs/compliance-checklist.md` — counsel approval for contract templates
- `docs/PARKING-COMPS.md` — market signal for unmanned paid lots
- `data/zoning/wa/README.md` — zoning flag semantics
