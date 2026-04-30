from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import ApprovalRequest, AuditLog, Parcel, WorkflowRun

logger = logging.getLogger(__name__)


def _count_since(db: Session, model: type, column: Any, cutoff: datetime) -> int:
    n = db.scalar(select(func.count()).select_from(model).where(column >= cutoff))
    return int(n or 0)


def _pending_approvals(db: Session) -> int:
    n = db.scalar(
        select(func.count()).select_from(ApprovalRequest).where(ApprovalRequest.status == "pending"),
    )
    return int(n or 0)


def _workflow_status_since(db: Session, cutoff: datetime) -> dict[str, int]:
    stmt = (
        select(WorkflowRun.status, func.count())
        .select_from(WorkflowRun)
        .where(WorkflowRun.updated_at >= cutoff)
        .group_by(WorkflowRun.status)
    )
    return {str(row[0]): int(row[1]) for row in db.execute(stmt).all()}


def _recent_audit_lines(db: Session, cutoff: datetime, limit: int = 8) -> list[str]:
    stmt = select(AuditLog).where(AuditLog.created_at >= cutoff).order_by(AuditLog.created_at.desc()).limit(limit)
    lines: list[str] = []
    for row in db.scalars(stmt):
        lines.append(f"• *{row.actor}* — `{row.action}` ({row.entity_type})")
    return lines


def build_slack_digest_blocks(db: Session, *, hours: int = 4) -> tuple[list[dict[str, Any]], str]:
    """Return Block Kit blocks plus a plain-text fallback for notifications."""
    cutoff = datetime.now(tz=UTC) - timedelta(hours=hours)
    new_parcels = _count_since(db, Parcel, Parcel.created_at, cutoff)
    wf_by_status = _workflow_status_since(db, cutoff)
    pending = _pending_approvals(db)
    audit_lines = _recent_audit_lines(db, cutoff)
    failed_n = db.scalar(
        select(func.count())
        .select_from(WorkflowRun)
        .where(and_(WorkflowRun.updated_at >= cutoff, WorkflowRun.status == "failed")),
    )
    failed_n = int(failed_n or 0)

    wf_lines = [f"• `{k}`: {v}" for k, v in sorted(wf_by_status.items())] or [
        "• _(no workflow updates in this window)_",
    ]
    audit_block = "\n".join(audit_lines) if audit_lines else "_(no audit events in this window)_"

    header = f"Parking acquisition — {hours}h standup ({cutoff:%Y-%m-%d %H:%M} → now UTC)"
    fallback = (
        f"{header}\n"
        f"Ingest: {new_parcels} new parcels | Pending approvals: {pending} | "
        f"Workflow updates by status: {wf_by_status!s} | Failures: {failed_n}"
    )

    blocks: list[dict[str, Any]] = [
        {"type": "header", "text": {"type": "plain_text", "text": "Parking agents — standup", "emoji": True}},
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"_{header}_",
                },
            ],
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "*Ingest agent*\n"
                    f"New parcels recorded in the last *{hours}h*: *{new_parcels}*\n"
                    "_Assumes assessor / GeoJSON ingest paths writing to `parcels`._"
                ),
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "*Scoring & pipeline agent*\n"
                    f"Workflow runs touched in the last *{hours}h* (by `updated_at` status):\n"
                    + "\n".join(wf_lines)
                    + f"\n\n_Failures in window:_ *{failed_n}*"
                ),
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "*Human-gate coordinator*\n"
                    f"*Pending* approval requests (needs a person): *{pending}*\n"
                    "_Use the approval UI or `GET /approvals?status=pending`._"
                ),
            },
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*Ops / audit log (snippet)*\n" + audit_block},
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": (
                        "_This is a scheduled digest. Replying here does not reach the agents yet; "
                        "see docs/SLACK.md for two-way options._"
                    ),
                },
            ],
        },
    ]
    return blocks, fallback


def post_digest_to_slack(settings: Settings, blocks: list[dict[str, Any]], fallback: str) -> dict[str, Any]:
    token = (settings.slack_bot_token or "").strip()
    channel = (settings.slack_digest_channel_id or "").strip()
    if not token or not channel:
        raise ValueError("slack not configured")
    client = WebClient(token=token)
    try:
        resp = client.chat_postMessage(channel=channel, blocks=blocks, text=fallback)
        return {"ok": resp.get("ok"), "ts": resp.get("ts")}
    except SlackApiError as e:
        logger.exception("Slack API error posting digest")
        raise RuntimeError(e.response.get("error", str(e))) from e


def post_text_to_slack(settings: Settings, *, text: str, channel_id: str | None = None) -> dict[str, Any]:
    token = (settings.slack_bot_token or "").strip()
    channel = (channel_id or settings.slack_digest_channel_id or "").strip()
    if not token or not channel:
        raise ValueError("slack not configured")
    client = WebClient(token=token)
    try:
        resp = client.chat_postMessage(channel=channel, text=text)
        return {"ok": resp.get("ok"), "ts": resp.get("ts"), "channel": resp.get("channel")}
    except SlackApiError as e:
        logger.exception("Slack API error posting message")
        raise RuntimeError(e.response.get("error", str(e))) from e
