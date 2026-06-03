# Zoning sources — Baltimore City (Maryland)

**Disclaimer:** Operational GIS guidance only—not legal advice. Article 32 and BMZA conditional uses require counsel before acquisitions.

## Why Baltimore is different from Washington

- **Code:** Baltimore City **Article 32** (not King/Kent WA ordinances).
- **Use tables:** **Table 10-301** lists **Parking Lot (Principal Use)** and **Parking Garage (Principal Use)** with **P** (permitted), **CB** (conditional via Board of Municipal and Zoning Appeals), **CO** (Council ordinance), or blank (not allowed).
- **GIS:** City **zoning district polygons** are separate from the **parcel** layer you ingest from EGIS.

Scoring uses `data/zoning/md/baltimore_city_surface_parking_rules.yaml`. **Only P (permitted-by-right) districts get full zoning score credit.** CB and CO districts are stored as `allows_surface_parking: false` until counsel approves a parcel-specific override via `ZONING_ALLOWS_SURFACE_PARKING` on the overlay.

## Entitlement tiers for paid surface parking (principal use)

Source: Article 32 use tables — row **Parking Lot (Principal Use)** (not accessory parking). Symbol key: [§ 1-205](https://codes.baltimorecity.gov/us/md/cities/baltimore/code/32/zoning-tables).

| Tier | Symbol | Meaning for acquisitions | Scoring default |
|------|--------|------------------------|-----------------|
| **1 — Best fit** | **P** | Outright principal surface parking allowed | Full `zoning_permitted_surface_parking` weight (35 pts in Baltimore pilot) |
| **2 — Entitlement path** | **CB** | BMZA conditional use — feasible but needs hearing/conditions | 0 unless overlay override |
| **3 — Political path** | **CO** | Mayor & City Council ordinance (common for legacy downtown lots) | 0 unless overlay override |
| **4 — Not viable** | blank / absent | Principal parking lot not listed (most R-1–R-4, OS accessory-only) | 0 |

### Tier 1 — prioritize (P districts)

| Zone | Table | Notes |
|------|-------|-------|
| **C-3, C-4** | [10-301](https://codes.baltimorecity.gov/us/md/cities/baltimore/code/32/zoning-tables/10-301) | Neighborhood/commercial corridors — best general commercial targets |
| **I-1, I-2, MI, OIC, BSC** | [11-301](https://codes.baltimorecity.gov/us/md/cities/baltimore/code/32/zoning-tables/11-301) | Industrial — often large lots; **I-1** is common on the city GIS layer |
| **C-5-TO, C-5-HS** | C-5 subdistrict table | Downtown subdistricts where principal lot is **P** (not base C-5) |
| **EC-1, EC-2, H** | [12-501](https://codes.baltimorecity.gov/us/md/cities/baltimore/code/32/zoning-tables/12-501), [12-601](https://codes.baltimorecity.gov/us/md/cities/baltimore/code/32/zoning-tables/12-601) | Campus districts — **P** but tied to educational/hospital context |
| **PC-1 … PC-4** | [12-1302](https://codes.baltimorecity.gov/us/md/cities/baltimore/code/32/zoning-tables/12-1302) | Port Covington — **P** (small geography) |

**Correction vs early pilot YAML:** **C-3/C-4 are P**, not conditional. **Base C-5 is CO**, not P — downtown surface lots often exist via legacy council ordinances, not by-right entitlement.

### Tier 2 — secondary funnel (CB / BMZA)

| Zone | Table |
|------|-------|
| C-1, C-1-VC, C-1-E, C-2 | 10-301 |
| C-5-DC, C-5-IH, C-5-DE, C-5-HT | C-5 subdistricts |
| OR-1, OR-2 | 12-301 |
| TOD-1 … TOD-4 | 12-402 (principal lots **max 1 acre**, § 12-504) |
| IMU-2 | 11-301 |

### Tier 3 — deprioritize unless existing CO on record

Base **C-5**, **C-5-G**, **IMU-1**, and **R-5 through R-10** (Table 9-301 lists principal parking as **CO** in dense residential districts).

### Tier 4 — exclude from principal-use pipeline

**R-1 through R-4** (Table 8-301 — no principal parking row), **OS** (Table 7-202 — **accessory** parking only).

All tiers must meet **§ 14-331** (screening, no on-lot repair, landscape manual).

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
