# Washington pilot — public data entry points

Use licensed parcel vendors for production; these are **starting points** for King / Snohomish / Pierce research.

## County assessor & GIS (open / semi-open)

| County     | FIPS  | Notes |
|-----------|-------|--------|
| King      | 53033 | [King County GIS / parcel search](https://gismaps.kingcounty.gov/parcelviewer2/) |
| Snohomish | 53061 | County GIS / assessor portals (verify current URLs and ToS) |
| Pierce    | 53053 | County GIS / assessor portals |

## State business registry (entities)

- [Washington Secretary of State — Corporations](https://ccfs.sos.wa.gov/) for entity verification when enriching owners.

## Zoning

Zoning is **municipal** in Washington (city + county). Map county open GIS + city zoning layers per submarket; expect multiple sources for a Puget Sound-wide product.

## DigitalOcean region

There is **no Seattle DO datacenter**. Use **`sfo3`** (or `sfo2`) for lowest latency from Washington to DigitalOcean; droplet, managed Postgres, and Spaces should use the **same region slug** for simpler networking and Spaces colocation.
