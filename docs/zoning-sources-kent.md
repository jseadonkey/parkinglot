# Zoning sources — Kent city & King County unincorporated (south-end pilot)

**Disclaimer:** This document is operational GIS guidance only—not zoning legal advice, not a substitute for title review or counsel. Interpret ordinances with qualified professionals before acquisitions.

## Why two sources

Parcels in **King County (`53033`)** fall under either:

- **City of Kent** municipal zoning (inside Kent city limits — see `data/boundaries/wa/kent_city_census_places.geojson`), or  
- **King County unincorporated** zoning (outside incorporated cities but inside unincorporated King County).

Each jurisdiction publishes its **own** GIS layers. Zoning portal URLs can change; stable boundaries live under `data/boundaries/` while this page tracks authoritative dataset entry points.

---

## City of Kent — zoning districts

| Kind | Link |
|------|------|
| **GeoPortal dataset** | [Kent Zoning Districts](https://gis-cityofkent.opendata.arcgis.com/datasets/kent-zoning-districts) on City of Kent GeoPortal (`gis-cityofkent.opendata.arcgis.com`) |
| **Interactive map** | City zoning maps may be linked from [KentWA.gov](https://www.kentwa.gov/) GIS / planning pages (Experience Builder apps change version-to-version). |

Download **polygons** (GeoJSON or shapefile), join to parcel footprints (intersect or centroid-in-polygon), and carry the district code into parcel attributes.

---

## King County — unincorporated zoning only

The county layer applies to **unincorporated** King County, **not** to land inside Kent or other cities.

| Kind | Link |
|------|------|
| **GIS Data Catalog** | [zoning_area — Zoning for Unincorporated King County](https://www5.kingcounty.gov/sdc?Layer=zoning_area) — metadata, attribute definitions (**CURRZONE** / current zoning style fields per catalog). Use **View in GIS Open Data** from that page for downloads/API when available. |
| **King County Open Data** | [Zoning for Unincorporated King County](https://gis-kingcounty.opendata.arcgis.com/datasets/kingcounty::zoning-for-unincorporated-king-county) (`kingcounty::zoning-for-unincorporated-king-county`). |
| **Optional MapServer** | [Planning/KingCo_Zoning](https://gismaps.kingcounty.gov/imagery/rest/services/Planning/KingCo_Zoning/MapServer) — REST map service for unincorporated zoning (verify layer index in the service directory). |

**Rights / terms:** King County spatial data are distributed with use restrictions. The GIS Data Catalog states that digital products may not be reproduced or redistributed without express written authorization from King County—comply with their terms for production use. Review the current catalog page before bulk redistribution.

---

## Workflow → this repository

1. **Download** Kent zoning districts + King County `zoning_area` (unincorporated).  
2. **Spatial join** each parcel polygon (or centroid) to the correct layer by geography:  
   - Inside Kent boundary → use **Kent** district code.  
   - Outside city limits but unincorporated King → use **King County** current zone field (e.g. catalog **CURRZONE** / “current zoning codes” semantics).  
3. **Emit GeoJSON** (or enrich before ingest) with at least:  
   - **`ZONING`** — normalized zone code string for that jurisdiction.  
   - **`ZONING_JURISDICTION`** — either `kent_city` or `king_unincorporated` (required for YAML rule lookup in `data/zoning/wa/kent_king_surface_parking_rules.yaml`).  
   - Optionally **`ZONING_ALLOWS_SURFACE_PARKING`** — explicit `true` / `false` if you already computed allowance; if omitted, the ingest loader infers from the rules file.  
4. **Ingest** via existing endpoints (`/internal/ingest/geojson-upload`, etc.). Rules path: see `data/zoning/wa/README.md` and optional env **`ZONING_RULES_PATH`**.

---

## Related docs

- `docs/washington-data.md` — parcel ingest entry points.  
- `data/zoning/wa/kent_king_surface_parking_rules.yaml` — curated zone → surface-parking suitability (placeholders until GIS/legal review).  
- `config/pilot.yaml` — `data_sources` pointers.
