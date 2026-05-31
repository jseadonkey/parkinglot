from __future__ import annotations

from typing import Any

from botocore.exceptions import ClientError

from app.config import get_settings
from app.storage import get_s3_client


def probe_storage_bucket() -> dict[str, Any]:
    """Check Spaces/S3 bucket reachability (no secret values returned)."""
    s = get_settings()
    endpoint = (s.storage_endpoint or "").strip()
    bucket = (s.storage_bucket or "").strip()
    region = (s.storage_region or "").strip()
    has_keys = bool((s.storage_access_key or "").strip() and (s.storage_secret_key or "").strip())

    out: dict[str, Any] = {
        "configured": bool(endpoint and bucket and has_keys),
        "endpoint": endpoint or None,
        "bucket": bucket or None,
        "region": region or None,
        "reachable": False,
        "error": None,
        "fix_hint": None,
    }
    if not out["configured"]:
        out["error"] = "STORAGE_* incomplete in deploy/.env"
        out["fix_hint"] = "Set STORAGE_ENDPOINT, STORAGE_BUCKET, STORAGE_ACCESS_KEY, STORAGE_SECRET_KEY in deploy/secrets.env"
        return out

    try:
        client = get_s3_client()
        client.head_bucket(Bucket=bucket)
        out["reachable"] = True
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        out["error"] = f"{code}: {e.response.get('Error', {}).get('Message', str(e))}"
        if code in ("404", "NoSuchBucket", "NotFound"):
            out["fix_hint"] = (
                f"Create a DigitalOcean Space named {bucket!r} in the matching region "
                f"(endpoint {endpoint}), or set STORAGE_BUCKET to an existing Space name."
            )
        elif code in ("403", "AccessDenied"):
            out["fix_hint"] = "Check STORAGE_ACCESS_KEY / STORAGE_SECRET_KEY have read/write on this Space."
    except OSError as e:
        out["error"] = str(e)
        out["fix_hint"] = "Verify STORAGE_ENDPOINT URL and network from the API/worker container."

    if out["reachable"] and endpoint and "sfo3" in endpoint and region == "us-east-1":
        out["fix_hint"] = (
            "STORAGE_REGION is us-east-1 but endpoint looks like sfo3 — set STORAGE_REGION=sfo3 for DigitalOcean Spaces."
        )

    return out
