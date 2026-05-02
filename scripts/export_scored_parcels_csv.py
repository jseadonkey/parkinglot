#!/usr/bin/env python3
"""Export parcels with latest identification / entitlement / strategic scores to CSV.

Requires the API Python environment (SQLAlchemy, geoalchemy2, psycopg) — same as the backend.
Optional Spaces upload uses ``boto3`` (dependency of ``services/api``).

Examples (from repo root; ``services/api`` is added to ``sys.path`` automatically):

  DATABASE_URL=postgresql+psycopg://... python3 scripts/export_scored_parcels_csv.py -o scores.csv

  # API container (scripts at /app/scripts after image rebuild):
  docker compose exec api python /app/scripts/export_scored_parcels_csv.py --limit 500

  # Public HTTPS URL on DigitalOcean Spaces (set STORAGE_* like deploy/.env):
  DATABASE_URL=... STORAGE_ENDPOINT=https://sfo3.digitaloceanspaces.com \\
    STORAGE_ACCESS_KEY=... STORAGE_SECRET_KEY=... STORAGE_BUCKET=my-bucket STORAGE_REGION=us-east-1 \\
    python3 scripts/export_scored_parcels_csv.py --publish-spaces -o scores.csv

Install deps once: ``pip install -e services/api`` (venv recommended).
Default output: ./parcel_scores_export.csv (``-o -`` = stdout).
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from parcel_export_common import build_scored_parcels_statement, ensure_api_path, normalize_database_url

_STORAGE_KEYS = (
    "STORAGE_ENDPOINT",
    "STORAGE_ACCESS_KEY",
    "STORAGE_SECRET_KEY",
    "STORAGE_BUCKET",
    "STORAGE_REGION",
)


def _fmt_cell(val: object) -> str:
    if val is None:
        return ""
    if isinstance(val, bool):
        return "true" if val else "false"
    return str(val)


def _storage_env() -> dict[str, str]:
    out: dict[str, str] = {}
    missing: list[str] = []
    for k in _STORAGE_KEYS:
        v = os.environ.get(k, "").strip()
        if not v:
            missing.append(k)
        else:
            out[k] = v
    if missing:
        raise ValueError(
            "missing required environment variables for Spaces upload: "
            + ", ".join(missing)
            + ". Set the same STORAGE_* values as the API (see deploy/env.production.example)."
        )
    return out


def _virtual_host_public_url(bucket: str, endpoint_url: str, key: str) -> str:
    """HTTPS URL for anonymous reads (after public-read ACL or bucket policy)."""
    raw = endpoint_url.strip()
    if not raw.startswith(("http://", "https://")):
        raw = "https://" + raw
    u = urlparse(raw)
    scheme = u.scheme or "https"
    host = (u.hostname or "").lower()
    if host.endswith(".digitaloceanspaces.com"):
        return f"{scheme}://{bucket}.{host}/{key}"
    netloc = u.netloc or host
    return f"{scheme}://{netloc}/{bucket}/{key}"


def _make_s3_client(env: dict[str, str]):
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=env["STORAGE_ENDPOINT"],
        aws_access_key_id=env["STORAGE_ACCESS_KEY"],
        aws_secret_access_key=env["STORAGE_SECRET_KEY"],
        region_name=env["STORAGE_REGION"],
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def upload_parcel_scores_csv(
    file_path: Path,
    *,
    object_key: str,
    presigned_ttl_seconds: int,
) -> tuple[str, str]:
    """Upload CSV bytes to Spaces. Returns (url, mode) where mode describes how to use the URL.

    Modes: ``public-acl`` (virtual-host HTTPS URL), ``presigned`` (time-limited GET URL),
    ``public-no-acl`` (virtual-host URL; requires bucket policy for anonymous read).
    """
    from botocore.exceptions import ClientError

    env = _storage_env()
    client = _make_s3_client(env)
    bucket = env["STORAGE_BUCKET"]
    endpoint = env["STORAGE_ENDPOINT"]
    body = file_path.read_bytes()

    try:
        client.put_object(
            Bucket=bucket,
            Key=object_key,
            Body=body,
            ContentType="text/csv; charset=utf-8",
            ACL="public-read",
        )
        return _virtual_host_public_url(bucket, endpoint, object_key), "public-acl"
    except ClientError as err:
        code = err.response.get("Error", {}).get("Code", "")
        if code in ("NoSuchBucket", "InvalidAccessKeyId", "SignatureDoesNotMatch"):
            raise

    client.put_object(
        Bucket=bucket,
        Key=object_key,
        Body=body,
        ContentType="text/csv; charset=utf-8",
    )
    base_url = _virtual_host_public_url(bucket, endpoint, object_key)
    ttl = max(60, min(presigned_ttl_seconds, 604800))
    try:
        presigned = client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": object_key},
            ExpiresIn=ttl,
        )
    except Exception:
        presigned = ""
    print(
        "warning: object ACL public-read was rejected or unavailable; uploaded as private. "
        "Set a bucket policy for public read on prefix exports/ if you need a stable HTTPS URL without query params, "
        "or use the presigned URL below. See docs/OPERATIONS.md.",
        file=sys.stderr,
    )
    if presigned:
        return presigned, "presigned"
    return base_url, "public-no-acl"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Export parcels with latest scores (identification, entitlement, strategic) to CSV.",
    )
    p.add_argument(
        "--output",
        "-o",
        default="parcel_scores_export.csv",
        help="Output path (default: ./parcel_scores_export.csv). Use '-' for stdout.",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Maximum number of parcel rows to export.",
    )
    p.add_argument(
        "--publish-spaces",
        "--upload-public",
        action="store_true",
        dest="publish_spaces",
        help="After export, upload CSV to S3-compatible storage (STORAGE_* env) and print a public URL.",
    )
    p.add_argument(
        "--presigned-ttl-seconds",
        type=int,
        default=604800,
        metavar="SEC",
        help="When ACL public-read is unavailable, TTL for presigned GET URL (max 604800). Default: 604800 (7 days).",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if not os.environ.get("DATABASE_URL", "").strip():
        print(
            "error: DATABASE_URL is not set. "
            "Export reads the same Postgres URL as the API (set DATABASE_URL in the environment).",
            file=sys.stderr,
        )
        return 2

    if args.publish_spaces:
        try:
            _storage_env()
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2

    ensure_api_path()

    from sqlalchemy import create_engine

    url = normalize_database_url(os.environ["DATABASE_URL"].strip())
    engine = create_engine(url, pool_pre_ping=True)
    stmt = build_scored_parcels_statement(variant="full_csv", limit=args.limit)

    fieldnames = (
        "parcel_id",
        "apn",
        "county_fips",
        "lot_sqft",
        "zoning_code",
        "zoning_allows_surface_parking",
        "is_corner_lot",
        "distance_to_nearest_demand_m",
        "score_identification",
        "score_entitlement",
        "score_strategic",
        "centroid_lon",
        "centroid_lat",
    )

    def write_rows_to(out_f) -> None:
        writer = csv.DictWriter(out_f, fieldnames=fieldnames)
        writer.writeheader()
        with engine.connect() as conn:
            result = conn.execute(stmt)
            for row in result.mappings():
                writer.writerow({k: _fmt_cell(row[k]) for k in fieldnames})

    upload_src: Path | None = None
    tmp_export: Path | None = None

    try:
        if args.publish_spaces and args.output == "-":
            # URL is printed to stdout; CSV exists only in Spaces (use -o path for a local copy too).
            fd, tmp_name = tempfile.mkstemp(suffix=".csv", text=True)
            os.close(fd)
            tmp_export = Path(tmp_name)
            with tmp_export.open("w", newline="", encoding="utf-8") as out_f:
                write_rows_to(out_f)
            upload_src = tmp_export
        elif args.output == "-":
            write_rows_to(sys.stdout)
        else:
            path = Path(args.output)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("w", newline="", encoding="utf-8") as out_f:
                write_rows_to(out_f)
            if args.publish_spaces:
                upload_src = path

        if args.publish_spaces:
            assert upload_src is not None
            ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            object_key = f"exports/parcel_scores_{ts}.csv"
            url, mode = upload_parcel_scores_csv(
                upload_src,
                object_key=object_key,
                presigned_ttl_seconds=args.presigned_ttl_seconds,
            )
            print(url)
            print(f"spaces: key={object_key} mode={mode} url={url}", file=sys.stderr)
    finally:
        if tmp_export is not None and tmp_export.exists():
            tmp_export.unlink()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
