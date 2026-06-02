from __future__ import annotations

import asyncio
import logging
import textwrap

from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_bolt.async_app import AsyncApp
from sqlalchemy import desc, func, select

from app.config import get_settings
from app.db.models import Parcel, ParcelScore, WorkflowRun
from app.db.session import SessionLocal
from parking_core.pilot import load_pilot_config

logger = logging.getLogger(__name__)


def _session():
    return SessionLocal()


def _qualified_floor() -> float:
    pilot = load_pilot_config(get_settings().pilot_config_path)
    return float(pilot.scoring.qualified_min_score)


def _latest_score_subq():
    return (
        select(ParcelScore.total_score)
        .where(ParcelScore.parcel_id == Parcel.id)
        .order_by(desc(ParcelScore.created_at))
        .limit(1)
        .scalar_subquery()
    )


def _latest_wf_status_subq():
    return (
        select(WorkflowRun.status)
        .where(WorkflowRun.parcel_id == Parcel.id)
        .order_by(desc(WorkflowRun.created_at))
        .limit(1)
        .scalar_subquery()
    )


async def _cmd_parking(ack, respond, command):  # type: ignore[no-untyped-def]
    await ack()
    settings = get_settings()
    if not (settings.slack_bot_token or "").strip():
        await respond("Slack bot token is not configured (`SLACK_BOT_TOKEN`).")
        return

    text = (command.get("text") or "").strip().lower()
    parts = text.split() if text else []
    sub = parts[0] if parts else "qualified"

    db = _session()
    try:
        if sub in {"help", "?", "commands"}:
            await respond(
                textwrap.dedent(
                    """
                    *Parking Slack commands*

                    • `/parking qualified` — top qualified parcels (latest score ≥ pilot floor)
                    • `/parking latest` — newest parcels (most recently created)
                    • `/parking counts` — totals + qualified count

                    _Tip: these responses are ephemeral (visible to you)._
                    """
                ).strip()
            )
            return

        if sub == "counts":
            floor = _qualified_floor()
            latest_total = _latest_score_subq()
            total = int(db.scalar(select(func.count()).select_from(Parcel)) or 0)
            qualified = int(
                db.scalar(select(func.count()).select_from(Parcel).where(latest_total >= floor)) or 0,
            )
            await respond(f"Parcels: *{total}* total | *{qualified}* qualified (latest score ≥ *{floor:.1f}*)")
            return

        if sub == "latest":
            stmt = select(Parcel).order_by(desc(Parcel.created_at)).limit(15)
            rows = list(db.scalars(stmt))
            if not rows:
                await respond("No parcels found yet.")
                return
            lines = [f"• `{p.county_fips}` / `{p.apn}` — id `{p.id}`" for p in rows]
            await respond("*Latest parcels*\n" + "\n".join(lines))
            return

        if sub in {"qualified", "shortlist", "deals", "negotiate"}:
            floor = _qualified_floor()
            latest_score = _latest_score_subq()
            latest_wf = _latest_wf_status_subq()
            stmt = (
                select(Parcel, latest_score.label("total_score"), latest_wf.label("wf_status"))
                .where(latest_score >= floor)
                .order_by(desc(latest_score))
                .limit(15)
            )
            rows = db.execute(stmt).all()
            if not rows:
                await respond(
                    f"No qualified parcels yet (floor *{floor:.1f}*). Try ingesting + running pipelines first."
                )
                return
            lines = []
            for parcel, score, wf_status in rows:
                wf = str(wf_status or "unknown")
                lines.append(
                    f"• `{parcel.county_fips}` / `{parcel.apn}` — score *{float(score):.1f}* — "
                    f"workflow `{wf}` — id `{parcel.id}`"
                )
            await respond(
                f"*Qualified parcels* (latest score ≥ *{floor:.1f}*)\n" + "\n".join(lines),
            )
            return

        await respond(f"Unknown subcommand `{sub}`. Try `/parking help`.")
    except Exception:  # noqa: BLE001
        logger.exception("slack /parking command failed")
        await respond("Sorry — something went wrong running that command. Check server logs.")
    finally:
        db.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()

    app_token = (settings.slack_app_token or "").strip()
    bot_token = (settings.slack_bot_token or "").strip()
    signing_secret = (settings.slack_signing_secret or "").strip()
    if not app_token or not bot_token or not signing_secret:
        raise SystemExit(
            "Missing Slack Socket Mode configuration. Set SLACK_APP_TOKEN, SLACK_BOT_TOKEN, and SLACK_SIGNING_SECRET."
        )

    app = AsyncApp(token=bot_token, signing_secret=signing_secret)
    app.command("/parking")(_cmd_parking)

    async def _run() -> None:
        handler = AsyncSocketModeHandler(app, app_token)
        await handler.start_async()

    asyncio.run(_run())


if __name__ == "__main__":
    main()
