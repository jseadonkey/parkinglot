#!/usr/bin/env python3
"""Split a pilot candidate GeoJSON into chunk files for parallel Celery ingest.

  python3 scripts/split_pilot_geojson.py \\
    -i data/pilot/kent_pilot_candidates.geojson \\
    -o data/pilot/chunks \\
    --chunk-size 10500
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Split pilot GeoJSON into ingest chunks.")
    parser.add_argument(
        "-i",
        "--input",
        type=Path,
        default=_REPO / "data/pilot/kent_pilot_candidates.geojson",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=_REPO / "data/pilot/chunks",
    )
    parser.add_argument("--chunk-size", type=int, default=10_500)
    parser.add_argument(
        "--prefix",
        default="kent_pilot_candidates",
        help="Chunk filename prefix (default kent_pilot_candidates)",
    )
    args = parser.parse_args()

    src: Path = args.input
    out_dir: Path = args.output_dir
    chunk_size = max(500, int(args.chunk_size))

    if not src.is_file():
        print(f"error: missing input {src}", file=sys.stderr)
        return 1

    print(f"Loading {src} ({src.stat().st_size / 1_000_000:.1f} MB)…")
    data = json.loads(src.read_text(encoding="utf-8"))
    if data.get("type") != "FeatureCollection":
        print("error: expected FeatureCollection", file=sys.stderr)
        return 1
    features = data.get("features") or []
    total = len(features)
    if total == 0:
        print("error: no features", file=sys.stderr)
        return 1

    out_dir.mkdir(parents=True, exist_ok=True)
    chunks_meta: list[dict] = []
    n_chunks = (total + chunk_size - 1) // chunk_size

    for idx in range(n_chunks):
        start = idx * chunk_size
        end = min(start + chunk_size, total)
        slice_feats = features[start:end]
        name = f"{args.prefix}_{idx + 1:03d}.geojson"
        path = out_dir / name
        chunk = {"type": "FeatureCollection", "features": slice_feats}
        path.write_text(json.dumps(chunk, separators=(",", ":")), encoding="utf-8")
        container_path = f"/app/data/pilot/chunks/{name}"
        chunks_meta.append(
            {
                "index": idx + 1,
                "file": name,
                "host_path": str(path.resolve()),
                "container_path": container_path,
                "feature_count": len(slice_feats),
                "feature_offset": start,
            }
        )
        print(f"  wrote {name} ({len(slice_feats):,} features)")

    manifest = {
        "source": str(src.resolve()),
        "total_features": total,
        "chunk_size": chunk_size,
        "chunk_count": len(chunks_meta),
        "chunks": chunks_meta,
    }
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Manifest: {manifest_path} ({len(chunks_meta)} chunks, {total:,} features)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
