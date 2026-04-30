from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Comma-separated browser origins for CORS (e.g. https://parking.example.com). Empty = local dev defaults.
    cors_allow_origins: str = Field(
        default="",
        validation_alias=AliasChoices("CORS_ALLOW_ORIGINS", "cors_allow_origins"),
    )
    # If set, POST /internal/* requires header X-Internal-Key matching this value (use in production).
    internal_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("INTERNAL_API_KEY", "internal_api_key"),
    )
    app_version: str = Field(default="dev", validation_alias=AliasChoices("APP_VERSION", "app_version"))

    database_url: str = "postgresql+psycopg://parking:parking@localhost:5432/parking"
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/0"
    pilot_config_path: str = "./config/pilot.yaml"
    storage_endpoint: str = "http://localhost:9000"
    storage_access_key: str = "minio"
    storage_secret_key: str = "minio12345"
    storage_bucket: str = "parking-drafts"
    storage_region: str = "us-east-1"
    api_public_url: str = "http://localhost:8000"

    # Slack (optional): bot posts a digest on a schedule from Celery Beat → worker task.
    slack_bot_token: str = Field(default="", validation_alias=AliasChoices("SLACK_BOT_TOKEN", "slack_bot_token"))
    slack_digest_channel_id: str = Field(
        default="",
        validation_alias=AliasChoices("SLACK_DIGEST_CHANNEL_ID", "slack_digest_channel_id"),
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
