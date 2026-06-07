from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.db.models import Parcel
from app.db.session import get_db
from app.main import app
from app.outreach_decisions import require_owner_contact_approved
from parking_core.models import OwnerOutreachBrief


def _brief_dict() -> dict:
    return OwnerOutreachBrief(
        county_fips="53033",
        apn="123456-7890",
        recorded_owner_one_liner="Jane Doe",
        contact_points=[],
        mailing_address_guess="100 Main St, Seattle, WA 98101",
        situs_address_guess="102 Main St, Seattle, WA 98101",
        phone_guess="206-555-0100",
        email_guess="owner@example.com",
        steps=[],
        data_gaps=[],
        compliance_notes=[],
        computed_at=datetime.now(tz=UTC),
    ).model_dump(mode="json")


def _parcel(decision: str = "pending") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        apn="123456-7890",
        county_fips="53033",
        owner_outreach_brief=_brief_dict(),
        owner_contact_decision=decision,
        owner_contact_decision_by=None,
        owner_contact_decision_at=None,
        owner_contact_decision_note=None,
    )


class _FakeSession:
    def __init__(self, parcel: SimpleNamespace) -> None:
        self.parcel = parcel

    def get(self, model: object, key: uuid.UUID) -> SimpleNamespace | None:
        if model is Parcel and key == self.parcel.id:
            return self.parcel
        return None

    def refresh(self, row: object) -> None:
        return None


def _client_for(parcel: SimpleNamespace) -> TestClient:
    app.dependency_overrides[get_db] = lambda: _FakeSession(parcel)
    return TestClient(app)


def test_require_owner_contact_approved_blocks_pending_and_rejected() -> None:
    require_owner_contact_approved(_parcel("approved"))

    with pytest.raises(HTTPException) as pending:
        require_owner_contact_approved(_parcel("pending"))
    assert pending.value.status_code == 403
    assert "human review" in pending.value.detail

    with pytest.raises(HTTPException) as rejected:
        require_owner_contact_approved(_parcel("rejected"))
    assert rejected.value.status_code == 403
    assert "rejected" in rejected.value.detail


def test_outreach_drafts_endpoint_waits_for_human_contact_decision() -> None:
    parcel = _parcel("pending")
    client = _client_for(parcel)
    try:
        resp = client.get(f"/parcels/{parcel.id}/outreach/drafts")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 403
    assert "approve owner contact" in resp.json()["detail"]


def test_outreach_approval_request_waits_for_human_contact_decision() -> None:
    parcel = _parcel("pending")
    client = _client_for(parcel)
    try:
        resp = client.post(
            f"/parcels/{parcel.id}/outreach/drafts/email/request-approval",
            json={"requested_by": "operator@example.com"},
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 403
    assert "approve owner contact" in resp.json()["detail"]


def test_contact_decision_endpoint_records_human_verdict(monkeypatch: pytest.MonkeyPatch) -> None:
    parcel = _parcel("pending")
    audits: list[dict] = []

    def fake_write_audit(*_args: object, **kwargs: object) -> None:
        audits.append(dict(kwargs))

    monkeypatch.setattr("app.routers.outreach.write_audit", fake_write_audit)
    client = _client_for(parcel)
    try:
        resp = client.post(
            f"/parcels/{parcel.id}/outreach/contact-decision",
            json={"decision": "approved", "decided_by": "operator@example.com"},
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["owner_contact_decision"] == "approved"
    assert body["owner_contact_decision_by"] == "operator@example.com"
    assert parcel.owner_contact_decision == "approved"
    assert audits[0]["action"] == "owner_contact_decision_updated"
