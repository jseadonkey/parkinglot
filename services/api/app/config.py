from datetime import date
from functools import lru_cache
from typing import Any

from pydantic import AliasChoices, Field, field_validator
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
    pilot_config_path: str = Field(
        default="./config/pilot.yaml",
        validation_alias=AliasChoices("PILOT_CONFIG_PATH", "pilot_config_path"),
    )
    pilot_strategic_config_path: str = Field(
        default="./config/pilot_strategic.yaml",
        validation_alias=AliasChoices("PILOT_STRATEGIC_CONFIG_PATH", "pilot_strategic_config_path"),
    )
    pilot_identification_config_path: str = Field(
        default="./config/pilot_identification.yaml",
        validation_alias=AliasChoices(
            "PILOT_IDENTIFICATION_CONFIG_PATH",
            "pilot_identification_config_path",
        ),
    )
    # Empty = resolve default rules file under /app/data (Docker) or repo data/zoning/wa (see geojson_loader).
    zoning_rules_path: str = Field(
        default="",
        validation_alias=AliasChoices("ZONING_RULES_PATH", "zoning_rules_path"),
    )
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
    # Dedicated channel for dual-agent score comparison messages (optional).
    slack_agent_discussion_channel_id: str = Field(
        default="",
        validation_alias=AliasChoices(
            "SLACK_AGENT_DISCUSSION_CHANNEL_ID",
            "slack_agent_discussion_channel_id",
        ),
    )
    # When set to 1/true/yes/on: worker posts short Slack lines for ingest + pipeline tasks (in addition to digest).
    slack_agent_event_updates: str = Field(
        default="",
        validation_alias=AliasChoices("SLACK_AGENT_EVENT_UPDATES", "slack_agent_event_updates"),
    )

    # Optional Celery Beat: ingest GeoJSON from a path on the API container (e.g. rsync county export).
    scheduled_geojson_ingest_path: str = Field(
        default="",
        validation_alias=AliasChoices("SCHEDULED_GEOJSON_INGEST_PATH", "scheduled_geojson_ingest_path"),
    )
    scheduled_geojson_ingest_default_county_fips: str = Field(
        default="",
        validation_alias=AliasChoices(
            "SCHEDULED_GEOJSON_INGEST_DEFAULT_COUNTY_FIPS",
            "scheduled_geojson_ingest_default_county_fips",
        ),
    )
    scheduled_geojson_ingest_auto_run_pipeline: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "SCHEDULED_GEOJSON_INGEST_AUTO_RUN_PIPELINE",
            "scheduled_geojson_ingest_auto_run_pipeline",
        ),
    )
    scheduled_geojson_ingest_max_auto_pipeline: int = Field(
        default=100,
        ge=1,
        le=5000,
        validation_alias=AliasChoices(
            "SCHEDULED_GEOJSON_INGEST_MAX_AUTO_PIPELINE",
            "scheduled_geojson_ingest_max_auto_pipeline",
        ),
    )
    scheduled_geojson_ingest_crontab_minute: int = Field(
        default=0,
        ge=0,
        le=59,
        validation_alias=AliasChoices(
            "SCHEDULED_GEOJSON_INGEST_CRONTAB_MINUTE",
            "scheduled_geojson_ingest_crontab_minute",
        ),
    )
    scheduled_geojson_ingest_crontab_hour: int = Field(
        default=7,
        ge=0,
        le=23,
        validation_alias=AliasChoices(
            "SCHEDULED_GEOJSON_INGEST_CRONTAB_HOUR",
            "scheduled_geojson_ingest_crontab_hour",
        ),
    )

    # Periodic pipeline backlog drain (parcels with no parcel_scores yet).
    scheduled_enqueue_unscored_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "SCHEDULED_ENQUEUE_UNSCORED_ENABLED",
            "scheduled_enqueue_unscored_enabled",
        ),
    )
    scheduled_enqueue_unscored_limit: int = Field(
        default=150,
        ge=1,
        le=500,
        validation_alias=AliasChoices(
            "SCHEDULED_ENQUEUE_UNSCORED_LIMIT",
            "scheduled_enqueue_unscored_limit",
        ),
    )
    scheduled_enqueue_unscored_crontab_minute: int = Field(
        default=25,
        ge=0,
        le=59,
        validation_alias=AliasChoices(
            "SCHEDULED_ENQUEUE_UNSCORED_CRONTAB_MINUTE",
            "scheduled_enqueue_unscored_crontab_minute",
        ),
    )
    # Celery crontab hour: int hour, "*", or "*/n" (e.g. "*/4" = every 4 hours UTC).
    scheduled_enqueue_unscored_crontab_hour: str = Field(
        default="*/4",
        validation_alias=AliasChoices(
            "SCHEDULED_ENQUEUE_UNSCORED_CRONTAB_HOUR",
            "scheduled_enqueue_unscored_crontab_hour",
        ),
    )

    # Washington statewide exploration: daily ingest rotation over pilot.region.county_fips (see docs).
    exploration_campaign_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "EXPLORATION_CAMPAIGN_ENABLED",
            "exploration_campaign_enabled",
        ),
    )
    exploration_campaign_config_path: str = Field(
        default="/app/config/exploration_campaign_wa.yaml",
        validation_alias=AliasChoices(
            "EXPLORATION_CAMPAIGN_CONFIG_PATH",
            "exploration_campaign_config_path",
        ),
    )
    exploration_campaign_start_date: date | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "EXPLORATION_CAMPAIGN_START_DATE",
            "exploration_campaign_start_date",
        ),
    )
    exploration_campaign_crontab_hour: int = Field(
        default=6,
        ge=0,
        le=23,
        validation_alias=AliasChoices(
            "EXPLORATION_CAMPAIGN_CRONTAB_HOUR",
            "exploration_campaign_crontab_hour",
        ),
    )
    exploration_campaign_crontab_minute: int = Field(
        default=30,
        ge=0,
        le=59,
        validation_alias=AliasChoices(
            "EXPLORATION_CAMPAIGN_CRONTAB_MINUTE",
            "exploration_campaign_crontab_minute",
        ),
    )

    # Optional licensed vendor webhook for owner/contact enrichment (POST JSON from pipeline).
    owner_vendor_lookup_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "OWNER_VENDOR_LOOKUP_ENABLED",
            "owner_vendor_lookup_enabled",
        ),
    )
    owner_vendor_lookup_url: str = Field(
        default="",
        validation_alias=AliasChoices(
            "OWNER_VENDOR_LOOKUP_URL",
            "owner_vendor_lookup_url",
        ),
    )
    owner_vendor_lookup_api_key: str = Field(
        default="",
        validation_alias=AliasChoices(
            "OWNER_VENDOR_LOOKUP_API_KEY",
            "owner_vendor_lookup_api_key",
        ),
    )

    @field_validator("exploration_campaign_start_date", mode="before")
    @classmethod
    def exploration_start_date_empty_ok(cls, v: Any) -> Any:
        """Compose often passes ``EXPLORATION_CAMPAIGN_START_DATE=`` when unset; coerce to None."""
        if v == "":
            return None
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
