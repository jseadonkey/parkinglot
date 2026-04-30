# Data vendor shortlist (US parcel / zoning / POI)

**Washington pilot:** see also [washington-data.md](washington-data.md) for county GIS / SOS entry points.

Evaluate licensing, coverage for your **pilot counties** in `config/pilot.yaml`, refresh cadence, and API limits. Replace `TBD` in pilot config after selection.

## Parcel boundaries and attributes

| Vendor | Notes |
|--------|--------|
| [Regrid](https://regrid.com/) | Nationwide parcel API; common for proptech |
| [LightBox](https://lightboxre.com/) | Parcel + context APIs |
| [CoreLogic / SafeGraph alternatives] | Enterprise contracts |

## Zoning / land use

| Source | Notes |
|--------|--------|
| County GIS open data | Often free; inconsistent schema |
| Commercial zoning vendors | Bundled with parcel suites; verify overlay rights |

## Demand generators (distance scoring)

| Source | Notes |
|--------|--------|
| OpenStreetMap (Overpass / Geofabrik) | Hospitals, stadiums, transit — respect ODbL |
| Commercial POI feeds | Cleaner categories; paid |

## Secretary of state / business entities

| Source | Notes |
|--------|--------|
| State SOS portals | Official; scraping policy varies |
| Licensed corporate data vendors | For scale and normalization |

**Pilot action:** Pick one parcel + zoning path for `06075` (or your real pilot FIPS), document contract ID and field mapping in `services/ingestion/README.md`.
