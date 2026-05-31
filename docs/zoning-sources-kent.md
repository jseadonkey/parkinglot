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

## Automated overlay (no desktop GIS)

Use **`scripts/build_king_kent_zoning_overlay.py`** to pull zoning polygons from Esri Feature Layer URLs (or from local GeoJSON you saved from the portals), load parcel footprints from **`DATABASE_URL`**, split Kent vs King unincorporated using **`data/boundaries/wa/kent_city_census_places.geojson`**, and write merge-ready GeoJSON.

1. From each open-data page, copy the **ArcGIS Feature Layer** REST URL ending in **`…/FeatureServer/0`** (not the HTML map page).
2. Confirm zone attribute names: **`python3 scripts/inspect_zoning_layer.py '<layer URL>'`** lists property keys from the first feature (defaults: **`ZONE_ABBR`** for Kent, **`CURRZONE`** for King — override with `--kent-zone-field` / `--king-zone-field`).
3. Run (example):

```bash
export DATABASE_URL=postgresql+psycopg://…
export KENT_ZONING='https://services3.arcgis.com/AME2ELqJ7UG0JjrU/arcgis/rest/services/PUB_PLAN_ZoningDistricts/FeatureServer/0'
export KING_ZONING='https://gisdata.kingcounty.gov/arcgis/rest/services/OpenDataPortal/planning__zoning_area/MapServer/450'
export KENT_ZONE_FIELD=Short_Name

python3 scripts/build_king_kent_zoning_overlay.py \
  -o data/zoning/wa/king_kent_zoning_overlay.geojson \
  --kent-zone-field Short_Name

python3 scripts/validate_phase_b_overlay.py data/zoning/wa/king_kent_zoning_overlay.geojson
```

4. Merge on the Droplet with **`PHASE_B_OVERLAY_PATH=/app/data/zoning/wa/king_kent_zoning_overlay.geojson`** and **`scripts/execute-phase-b.sh`** (see Phase B in `docs/PHASED-EXECUTION-PLAN-A-E.md`).

Layer URLs change when jurisdictions republish services — treat **`KENT_ZONING`** / **`KING_ZONING`** as configuration you refresh when joins fail or fields move.

---

## Workflow → this repository (manual GIS path)

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
