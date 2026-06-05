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
    api_public_url: str = Field(
        default="http://localhost:8000",
        validation_alias=AliasChoices("API_PUBLIC_URL", "PUBLIC_API_URL", "api_public_url"),
    )

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
    # Celery Beat: pipeline standup digest (default hourly at :00 UTC).
    slack_digest_crontab_minute: int = Field(
        default=0,
        ge=0,
        le=59,
        validation_alias=AliasChoices("SLACK_DIGEST_CRONTAB_MINUTE", "slack_digest_crontab_minute"),
    )
    slack_digest_crontab_hour: str = Field(
        default="*",
        validation_alias=AliasChoices("SLACK_DIGEST_CRONTAB_HOUR", "slack_digest_crontab_hour"),
    )
    slack_digest_window_hours: int = Field(
        default=1,
        ge=1,
        le=24,
        validation_alias=AliasChoices("SLACK_DIGEST_WINDOW_HOURS", "slack_digest_window_hours"),
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
        default=False,
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

    # Optional Celery Beat: Cartographer identification score backfill (same as Phase A refresh-identification).
    scheduled_refresh_identification_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "SCHEDULED_REFRESH_IDENTIFICATION_ENABLED",
            "scheduled_refresh_identification_enabled",
        ),
    )
    scheduled_refresh_identification_limit: int = Field(
        default=2000,
        ge=1,
        le=5000,
        validation_alias=AliasChoices(
            "SCHEDULED_REFRESH_IDENTIFICATION_LIMIT",
            "scheduled_refresh_identification_limit",
        ),
    )
    scheduled_refresh_identification_crontab_minute: int = Field(
        default=10,
        ge=0,
        le=59,
        validation_alias=AliasChoices(
            "SCHEDULED_REFRESH_IDENTIFICATION_CRONTAB_MINUTE",
            "scheduled_refresh_identification_crontab_minute",
        ),
    )
    scheduled_refresh_identification_crontab_hour: str = Field(
        default="*/6",
        validation_alias=AliasChoices(
            "SCHEDULED_REFRESH_IDENTIFICATION_CRONTAB_HOUR",
            "scheduled_refresh_identification_crontab_hour",
        ),
    )
    scheduled_refresh_identification_county_fips: str = Field(
        default="",
        validation_alias=AliasChoices(
            "SCHEDULED_REFRESH_IDENTIFICATION_COUNTY_FIPS",
            "scheduled_refresh_identification_county_fips",
        ),
    )

    # Optional Celery Beat: Beacon demand-distance + identification touch (same as Phase A refresh-demand).
    scheduled_refresh_demand_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "SCHEDULED_REFRESH_DEMAND_ENABLED",
            "scheduled_refresh_demand_enabled",
        ),
    )
    scheduled_refresh_demand_limit: int = Field(
        default=2000,
        ge=1,
        le=5000,
        validation_alias=AliasChoices(
            "SCHEDULED_REFRESH_DEMAND_LIMIT",
            "scheduled_refresh_demand_limit",
        ),
    )
    scheduled_refresh_demand_crontab_minute: int = Field(
        default=40,
        ge=0,
        le=59,
        validation_alias=AliasChoices(
            "SCHEDULED_REFRESH_DEMAND_CRONTAB_MINUTE",
            "scheduled_refresh_demand_crontab_minute",
        ),
    )
    scheduled_refresh_demand_crontab_hour: str = Field(
        default="*/6",
        validation_alias=AliasChoices(
            "SCHEDULED_REFRESH_DEMAND_CRONTAB_HOUR",
            "scheduled_refresh_demand_crontab_hour",
        ),
    )
    scheduled_refresh_demand_county_fips: str = Field(
        default="",
        validation_alias=AliasChoices(
            "SCHEDULED_REFRESH_DEMAND_COUNTY_FIPS",
            "scheduled_refresh_demand_county_fips",
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

    # Slow WA statewide ingest: one new county per day via WaTech when parking queue is light.
    wa_statewide_rollout_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "WA_STATEWIDE_ROLLOUT_ENABLED",
            "wa_statewide_rollout_enabled",
        ),
    )
    wa_statewide_rollout_config_path: str = Field(
        default="/app/config/wa_statewide_rollout.yaml",
        validation_alias=AliasChoices(
            "WA_STATEWIDE_ROLLOUT_CONFIG_PATH",
            "wa_statewide_rollout_config_path",
        ),
    )
    geo_markets_config_path: str = Field(
        default="/app/config/geo_markets.yaml",
        validation_alias=AliasChoices(
            "GEO_MARKETS_CONFIG_PATH",
            "geo_markets_config_path",
        ),
    )
    wa_statewide_rollout_crontab_hour: int = Field(
        default=7,
        ge=0,
        le=23,
        validation_alias=AliasChoices(
            "WA_STATEWIDE_ROLLOUT_CRONTAB_HOUR",
            "wa_statewide_rollout_crontab_hour",
        ),
    )
    wa_statewide_rollout_crontab_minute: int = Field(
        default=15,
        ge=0,
        le=59,
        validation_alias=AliasChoices(
            "WA_STATEWIDE_ROLLOUT_CRONTAB_MINUTE",
            "wa_statewide_rollout_crontab_minute",
        ),
    )

    # Prefer highest entitlement scores when draining pipeline backlog (see enqueue_priority_qualified).
    scheduled_priority_pipeline_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "SCHEDULED_PRIORITY_PIPELINE_ENABLED",
            "scheduled_priority_pipeline_enabled",
        ),
    )
    scheduled_priority_pipeline_limit: int = Field(
        default=75,
        ge=1,
        le=200,
        validation_alias=AliasChoices(
            "SCHEDULED_PRIORITY_PIPELINE_LIMIT",
            "scheduled_priority_pipeline_limit",
        ),
    )
    scheduled_priority_pipeline_crontab_hour: str = Field(
        default="*/2",
        validation_alias=AliasChoices(
            "SCHEDULED_PRIORITY_PIPELINE_CRONTAB_HOUR",
            "scheduled_priority_pipeline_crontab_hour",
        ),
    )
    scheduled_priority_pipeline_crontab_minute: int = Field(
        default=20,
        ge=0,
        le=59,
        validation_alias=AliasChoices(
            "SCHEDULED_PRIORITY_PIPELINE_CRONTAB_MINUTE",
            "scheduled_priority_pipeline_crontab_minute",
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

    outreach_sender_name: str = Field(
        default="",
        validation_alias=AliasChoices("OUTREACH_SENDER_NAME", "outreach_sender_name"),
    )
    outreach_sender_company: str = Field(
        default="",
        validation_alias=AliasChoices("OUTREACH_SENDER_COMPANY", "outreach_sender_company"),
    )
    outreach_sender_email: str = Field(
        default="",
        validation_alias=AliasChoices("OUTREACH_SENDER_EMAIL", "outreach_sender_email"),
    )
    outreach_sender_phone: str = Field(
        default="",
        validation_alias=AliasChoices("OUTREACH_SENDER_PHONE", "outreach_sender_phone"),
    )

    lob_api_key: str = Field(default="", validation_alias=AliasChoices("LOB_API_KEY", "lob_api_key"))
    lob_from_name: str = Field(default="", validation_alias=AliasChoices("LOB_FROM_NAME", "lob_from_name"))
    lob_from_address_line1: str = Field(
        default="",
        validation_alias=AliasChoices("LOB_FROM_ADDRESS_LINE1", "lob_from_address_line1"),
    )
    lob_from_address_line2: str = Field(
        default="",
        validation_alias=AliasChoices("LOB_FROM_ADDRESS_LINE2", "lob_from_address_line2"),
    )
    lob_from_address_city: str = Field(
        default="",
        validation_alias=AliasChoices("LOB_FROM_ADDRESS_CITY", "lob_from_address_city"),
    )
    lob_from_address_state: str = Field(
        default="",
        validation_alias=AliasChoices("LOB_FROM_ADDRESS_STATE", "lob_from_address_state"),
    )
    lob_from_address_zip: str = Field(
        default="",
        validation_alias=AliasChoices("LOB_FROM_ADDRESS_ZIP", "lob_from_address_zip"),
    )
    lob_mail_extra_service: str = Field(
        default="certified",
        validation_alias=AliasChoices("LOB_MAIL_EXTRA_SERVICE", "lob_mail_extra_service"),
    )
    lob_send_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices("LOB_SEND_ENABLED", "lob_send_enabled"),
    )

    # Site watchdog: API + UI + server checks (separate from pipeline Slack digest).
    site_watchdog_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices("SITE_WATCHDOG_ENABLED", "site_watchdog_enabled"),
    )
    site_watchdog_ui_base_url: str = Field(
        default="",
        validation_alias=AliasChoices("SITE_WATCHDOG_UI_BASE_URL", "site_watchdog_ui_base_url"),
    )
    site_watchdog_internal_api_url: str = Field(
        default="",
        validation_alias=AliasChoices(
            "SITE_WATCHDOG_INTERNAL_API_URL",
            "site_watchdog_internal_api_url",
        ),
    )
    site_watchdog_internal_ui_url: str = Field(
        default="",
        validation_alias=AliasChoices(
            "SITE_WATCHDOG_INTERNAL_UI_URL",
            "site_watchdog_internal_ui_url",
        ),
    )
    site_watchdog_retry_count: int = Field(
        default=3,
        ge=1,
        le=10,
        validation_alias=AliasChoices(
            "SITE_WATCHDOG_RETRY_COUNT",
            "site_watchdog_retry_count",
        ),
    )
    site_watchdog_retry_delay_seconds: float = Field(
        default=5.0,
        ge=0.0,
        le=60.0,
        validation_alias=AliasChoices(
            "SITE_WATCHDOG_RETRY_DELAY_SECONDS",
            "site_watchdog_retry_delay_seconds",
        ),
    )
    site_watchdog_slack_channel_id: str = Field(
        default="",
        validation_alias=AliasChoices(
            "SITE_WATCHDOG_SLACK_CHANNEL_ID",
            "site_watchdog_slack_channel_id",
        ),
    )
    site_watchdog_parking_queue_warn: int = Field(
        default=50_000,
        ge=1000,
        le=2_000_000,
        validation_alias=AliasChoices(
            "SITE_WATCHDOG_PARKING_QUEUE_WARN",
            "site_watchdog_parking_queue_warn",
        ),
    )
    site_watchdog_heartbeat_hours: int = Field(
        default=1,
        ge=0,
        le=168,
        validation_alias=AliasChoices(
            "SITE_WATCHDOG_HEARTBEAT_HOURS",
            "site_watchdog_heartbeat_hours",
        ),
    )
    site_watchdog_crontab_minute: str = Field(
        default="0",
        validation_alias=AliasChoices(
            "SITE_WATCHDOG_CRONTAB_MINUTE",
            "site_watchdog_crontab_minute",
        ),
    )
    poi_overpass_url: str = Field(
        default="https://overpass.openstreetmap.fr/api/interpreter",
        description="Public Overpass endpoint; overpass-api.de is often unreachable from DO Droplets.",
        validation_alias=AliasChoices("POI_OVERPASS_URL", "poi_overpass_url"),
    )
    poi_overpass_delay_sec: float = Field(
        default=1.0,
        ge=0.0,
        le=10.0,
        validation_alias=AliasChoices("POI_OVERPASS_DELAY_SEC", "poi_overpass_delay_sec"),
    )
    poi_overpass_user_agent: str = Field(
        default="parkinglot-pilot/1.0 (OSM POI density; +https://github.com/jseadonkey/parkinglot)",
        validation_alias=AliasChoices("POI_OVERPASS_USER_AGENT", "poi_overpass_user_agent"),
    )

    # Ops remediation loop: detect gaps + enqueue safe fixes (Slack queue).
    ops_remediation_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices("OPS_REMEDIATION_ENABLED", "ops_remediation_enabled"),
    )
    ops_remediation_auto_fix: bool = Field(
        default=True,
        validation_alias=AliasChoices("OPS_REMEDIATION_AUTO_FIX", "ops_remediation_auto_fix"),
    )
    ops_remediation_notify_on_warnings: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "OPS_REMEDIATION_NOTIFY_ON_WARNINGS",
            "ops_remediation_notify_on_warnings",
        ),
    )
    ops_remediation_priority_county_fips: str = Field(
        default="24510",
        validation_alias=AliasChoices(
            "OPS_REMEDIATION_PRIORITY_COUNTY_FIPS",
            "ops_remediation_priority_county_fips",
        ),
    )
    ops_remediation_batch_limit: int = Field(
        default=2000,
        ge=50,
        le=5000,
        validation_alias=AliasChoices("OPS_REMEDIATION_BATCH_LIMIT", "ops_remediation_batch_limit"),
    )
    ops_remediation_poi_batch_limit: int = Field(
        default=50,
        ge=10,
        le=200,
        validation_alias=AliasChoices(
            "OPS_REMEDIATION_POI_BATCH_LIMIT",
            "ops_remediation_poi_batch_limit",
        ),
    )
    ops_remediation_pipeline_enqueue_limit: int = Field(
        default=75,
        ge=10,
        le=500,
        validation_alias=AliasChoices(
            "OPS_REMEDIATION_PIPELINE_ENQUEUE_LIMIT",
            "ops_remediation_pipeline_enqueue_limit",
        ),
    )
    ops_remediation_cooldown_sec: int = Field(
        default=3600,
        ge=300,
        le=86400,
        validation_alias=AliasChoices(
            "OPS_REMEDIATION_COOLDOWN_SEC",
            "ops_remediation_cooldown_sec",
        ),
    )
    ops_remediation_heartbeat_hours: int = Field(
        default=12,
        ge=0,
        le=168,
        validation_alias=AliasChoices(
            "OPS_REMEDIATION_HEARTBEAT_HOURS",
            "ops_remediation_heartbeat_hours",
        ),
    )
    ops_remediation_crontab_minute: str = Field(
        default="15",
        validation_alias=AliasChoices(
            "OPS_REMEDIATION_CRONTAB_MINUTE",
            "ops_remediation_crontab_minute",
        ),
    )
    ops_remediation_crontab_hour: str = Field(
        default="*/2",
        validation_alias=AliasChoices(
            "OPS_REMEDIATION_CRONTAB_HOUR",
            "ops_remediation_crontab_hour",
        ),
    )
    ops_remediation_slack_channel_id: str = Field(
        default="",
        validation_alias=AliasChoices(
            "OPS_REMEDIATION_SLACK_CHANNEL_ID",
            "ops_remediation_slack_channel_id",
        ),
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
