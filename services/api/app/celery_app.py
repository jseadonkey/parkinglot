from __future__ import annotations

import os

from celery import Celery
from celery.schedules import crontab

broker = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
backend = os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/0")

celery = Celery("parking", broker=broker, backend=backend)
celery.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_default_queue="parking",
    beat_schedule={
        "slack-parking-digest-4h": {
            "task": "app.tasks.slack_agent_digest",
            "schedule": crontab(minute=0, hour="*/4"),
        },
    },
)

import app.tasks  # noqa: E402,F401 — register Celery tasks
