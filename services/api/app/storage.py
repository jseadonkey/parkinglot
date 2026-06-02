from __future__ import annotations

import boto3
from botocore.client import BaseClient
from botocore.config import Config

from app.config import get_settings


def get_s3_client() -> BaseClient:
    s = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=s.storage_endpoint,
        aws_access_key_id=s.storage_access_key,
        aws_secret_access_key=s.storage_secret_key,
        region_name=s.storage_region,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def put_text_object(key: str, body: str, content_type: str = "text/markdown") -> None:
    s = get_settings()
    client = get_s3_client()
    client.put_object(Bucket=s.storage_bucket, Key=key, Body=body.encode("utf-8"), ContentType=content_type)


def get_text_object(key: str) -> str:
    s = get_settings()
    client = get_s3_client()
    resp = client.get_object(Bucket=s.storage_bucket, Key=key)
    return resp["Body"].read().decode("utf-8")
