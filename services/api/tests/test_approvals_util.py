from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.approvals_util import pending_approval_for


def _row(*, parcel_id: str, channel: str | None = None) -> SimpleNamespace:
    payload: dict[str, str] = {"parcel_id": parcel_id}
    if channel is not None:
        payload["channel"] = channel
    return SimpleNamespace(
        type="outbound_message",
        status="pending",
        payload=payload,
    )


def test_pending_approval_for_matches_channel() -> None:
    db = MagicMock()
    db.scalars.return_value.all.return_value = [
        _row(parcel_id="p1", channel="email"),
        _row(parcel_id="p1", channel="sms"),
    ]
    found = pending_approval_for(
        db,
        approval_type="outbound_message",
        parcel_id="p1",
        payload_match={"channel": "sms"},
    )
    assert found is not None
    assert found.payload["channel"] == "sms"


def test_pending_approval_for_ignores_other_parcels() -> None:
    db = MagicMock()
    db.scalars.return_value.all.return_value = [
        _row(parcel_id="other", channel="email"),
    ]
    found = pending_approval_for(
        db,
        approval_type="outbound_message",
        parcel_id="p1",
        payload_match={"channel": "email"},
    )
    assert found is None
