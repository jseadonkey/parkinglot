#!/usr/bin/env python3
"""Print Baltimore zoning tier counts from a Phase B overlay GeoJSON (local QA)."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "ingestion"))

from parking_ingestion.zoning_rules import (  # noqa: E402
    load_effective_zoning_rules,
    resolve_principal_use_symbol,
    zoning_entitlement_tier,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize Baltimore overlay by entitlement tier")
    parser.add_argument(
        "-i",
        "--input",
        type=Path,
        default=ROOT / "data/baltimore/baltimore_city_zoning_overlay.geojson",
    )
    args = parser.parse_args()
    data = json.loads(args.input.read_text(encoding="utf-8"))
    rules = load_effective_zoning_rules()
    tiers: Counter[str] = Counter()
    zones: Counter[str] = Counter()
    for feat in data.get("features") or []:
        props = feat.get("properties") or {}
        z = str(props.get("ZONING") or props.get("Zoning") or "").strip()
        sym = resolve_principal_use_symbol(z, "baltimore_city", rules)
        tier = zoning_entitlement_tier(sym)
        tiers[tier] += 1
        if tier == "permitted":
            zones[z] += 1
    total = sum(tiers.values())
    print(f"Overlay: {args.input} ({total} parcels)")
    for tier, n in tiers.most_common():
        print(f"  {tier}: {n} ({100 * n / total:.1f}%)")
    print("Top permitted zones:")
    for z, n in zones.most_common(10):
        print(f"  {z}: {n}")


if __name__ == "__main__":
    main()
