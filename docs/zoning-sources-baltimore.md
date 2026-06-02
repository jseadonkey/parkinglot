# Zoning sources — Baltimore City (Maryland)

**Disclaimer:** Operational GIS guidance only—not legal advice. Article 32 and BMZA conditional uses require counsel before acquisitions.

## Why Baltimore is different from Washington

- **Code:** Baltimore City **Article 32** (not King/Kent WA ordinances).
- **Use tables:** **Table 10-301** lists **Parking Lot (Principal Use)** and **Parking Garage (Principal Use)** with **P** (permitted), **CB** (conditional via Board of Municipal and Zoning Appeals), **CO** (Council ordinance), or blank (not allowed).
- **GIS:** City **zoning district polygons** are separate from the **parcel** layer you ingest from EGIS.

Scoring uses `data/zoning/md/baltimore_city_surface_parking_rules.yaml`. **CB districts are treated as not allowed** until you set `ZONING_ALLOWS_SURFACE_PARKING` on the overlay or counsel approves a scoring policy for conditional uses.

## Official GIS — zoning districts

| Kind | Link |
|------|------|
| **ArcGIS MapServer** | [CityView/Zoning_New layer 0](https://geodata.baltimorecity.gov/egis/rest/services/CityView/Zoning_New/MapServer/0) |
| **Planning GIS** | [planning.baltimorecity.gov/maps-data/GIS](https://planning.baltimorecity.gov/maps-data/GIS) |
| **Interactive** | CityView / OpenBaltimore (search “zoning districts”) |

Export scripts (repo):

```bash
python3 scripts/fetch_baltimore_city_parcels.py -o data/baltimore/baltimore_city_parcels.geojson
python3 scripts/fetch_baltimore_zoning_districts.py -o data/baltimore/baltimore_city_zoning_districts.geojson
python3 scripts/build_baltimore_zoning_overlay.py \
  --parcels data/baltimore/baltimore_city_parcels.geojson \
  --zoning data/baltimore/baltimore_city_zoning_districts.geojson \
  -o data/baltimore/baltimore_city_zoning_overlay.geojson
```

(`build_baltimore_zoning_overlay.py` uses parcel centroid → zoning polygon; same property aliases as ingest.)

## Phase B — spatial join to parcels

1. Export **parcel** and **zoning** GeoJSON (commands above), or run Droplet resource **`baltimore_zoning_overlay`** (fetch + join + merge).
2. Each matched parcel gets **`ZONING`** and **`ZONING_JURISDICTION=baltimore_city`** on the overlay.
3. Set **`ZONING_JURISDICTION=baltimore_city`** (or rely on auto-infer from `COUNTY_FIPS=24510`).
4. Optional: set **`ZONING_ALLOWS_SURFACE_PARKING`** per parcel if counsel reviewed BMZA conditionals.
5. Merge onto existing rows:

```http
POST /internal/ingest/merge-geojson-attributes
{"path":"/app/data/baltimore/baltimore_city_zoning_overlay.geojson","refresh_pipeline":true}
```

Worker path must match Droplet mount (`data/` → `/app/data/`).

Dry-run:

```bash
python3 scripts/validate_phase_b_overlay.py data/baltimore/baltimore_city_zoning_overlay.geojson
```

## Curating the rules YAML

1. Open [Table 10-301](https://codes.baltimorecity.gov/us/md/cities/baltimore/code/32/zoning-tables/10-301) — row **Parking Lot (Principal Use)**.
2. For each district code appearing in your GIS join, set `allows_surface_parking: true` only where the table shows **P** for that use (not **CB** unless policy changes).
3. Add missing zone labels as they appear on the CityView layer (field names vary — check layer schema).

## Re-score after overlay

After merge, identification + entitlement scores refresh for touched parcels. Re-run priority enqueue for Baltimore City (`24510`) from Droplet resources or:

```http
POST /internal/pipeline/enqueue-priority?limit=75
```

Filter outreach board: `state_fips=24` or `county_fips=24510`.
