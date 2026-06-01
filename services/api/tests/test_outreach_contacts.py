from __future__ import annotations

from app.outreach_contacts import normalize_contact_value
from parking_core.models import ContactKind


def test_normalize_email_casefolds() -> None:
    assert normalize_contact_value(ContactKind.email, "Owner@Example.com") == "owner@example.com"


def test_normalize_phone_uses_last_ten_digits() -> None:
    assert normalize_contact_value(ContactKind.phone, "+1 (206) 555-0100") == "2065550100"


def test_normalize_address_collapses_whitespace() -> None:
    assert normalize_contact_value(ContactKind.mailing_address, "100  Main   St") == "100 main st"
