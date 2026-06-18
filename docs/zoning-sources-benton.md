# Zoning sources — Benton County & Tri-Cities (53005)

**Disclaimer:** Operational GIS guidance only—not zoning legal advice. Curate use tables with counsel before acquisition decisions.

## Why multiple sources

Parcels in **Benton County (`53005`)** fall under city zoning (Kennewick, Richland, Pasco, West Richland) or **Benton County unincorporated** zoning. Each authority publishes its own GIS layers.

WaTech parcel ingest does **not** include zoning. After parcel load, run Phase B overlay merge to attach `ZONING` + `ZONING_JURISDICTION`.

---

## City of Kennewick — parcel-level zoning (attribute join)

| Kind | Link |
|------|------|
| **ArcGIS FeatureServer** | [Public/AllGISLayers → Parcel Zoning (59)](https://maps.ci.kennewick.wa.us/server/rest/services/Public/AllGISLayers/FeatureServer/59) |
| **Join key** | WaTech `PARCEL_ID_NR` → strip `005-` prefix → Kennewick `CountyTaxID` (15-digit, no dashes) |
| **Zoning field** | `Zoning` |

Example: WaTech `005-104893100000004` → Kennewick `104893100000004` → zone `RL`.

---

## City of Pasco — zoning districts (spatial join)

| Kind | Link |
|------|------|
| **ArcGIS FeatureServer** | [Citybase_Published_Layers/Zoning](https://gis.pasco-wa.gov/gs/rest/services/Citybase_Published_Layers/Zoning/FeatureServer/0) |
| **Zoning field** | `Zone` |
| **Jurisdiction key** | `pasco_city` |

Use parcel polygon ∩ Pasco zoning polygon; assign `ZONING_JURISDICTION=pasco_city`.

---

## Benton County — unincorporated zoning (spatial join)

| Kind | Link |
|------|------|
| **ArcGIS MapServer** | [Zoning/MapServer/0](https://maps.co.benton.wa.us/server/rest/services/Zoning/MapServer/0) |
| **Zoning field** | `LandUseTyp` |
| **Jurisdiction key** | `benton_unincorporated` |

Applies to unincorporated county land and (interim) Richland/West Richland parcels until Richland parcel-zoning REST is stable.

---

## City of Richland — parcel zoning (blocked interim)

| Kind | Link |
|------|------|
| **ArcGIS MapServer** | [Richland/Zoning → Parcels (0)](https://gisweb24.ci.richland.wa.us/arcgis24web/rest/services/Richland/Zoning/MapServer/0) |

The public REST service currently rejects paginated queries (`Pagination is not supported`). Track as `blocked` in the registry until an alternate export path is confirmed. Until then, Richland situs parcels receive county-layer spatial joins as a conservative fallback.

---

## Workflow → this repository

```bash
# 1) Cache zoning layers locally (no DATABASE_URL required)
python3 scripts/fetch_benton_zoning_layers.py

# 2) Build overlay GeoJSON (fetches WaTech Benton parcels when --parcels omitted)
python3 scripts/build_benton_zoning_overlay.py

# 3) Validate overlay property coverage
python3 scripts/validate_phase_b_overlay.py data/benton/benton_county_zoning_overlay.geojson

# 4) Merge into production parcels (Droplet — needs DATABASE_URL + INTERNAL_API_KEY)
PHASE_B_OVERLAY_PATH=/opt/workspaces/parkinglot/data/benton/benton_county_zoning_overlay.geojson \
  make phase-b-run
```

Overlay features must include:

- **`ZONING`** — district code from the source layer
- **`ZONING_JURISDICTION`** — `kennewick_city`, `pasco_city`, `benton_unincorporated`, or `richland_city`
- **`APN`** — must match WaTech `PARCEL_ID_NR` stored at ingest

Rules YAML: `data/zoning/wa/benton_tri_cities_surface_parking_rules.yaml` (merged automatically with other WA/MD rule files).

After merge, identification prescreen scores recompute; parcels with zoning credit ≥ 60 enter the pipeline backlog.

---

## Related docs

- `docs/WA_STATEWIDE_ROLLOUT.md` — parcel ingest order (Benton is priority #10)
- `docs/ZONING-GOVERNANCE.md` — registry status meanings
- `data/jurisdictions/wa/jurisdiction_registry.csv` — Benton city rows + `source_found` tracking
