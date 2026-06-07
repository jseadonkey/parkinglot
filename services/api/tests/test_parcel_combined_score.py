from app.parcel_scored_list import _combined_score_value, _mailing_address, _situs_address


def test_combined_score_averages_present_scores() -> None:
    assert _combined_score_value(90.0, 80.0, 70.0) == 80.0
    assert _combined_score_value(90.0, None, 70.0) == 80.0
    assert _combined_score_value(None, None, None) is None


def test_baltimore_realproperty_address_fields_stay_separate() -> None:
    raw = {
        "FULLADDR": "25 S CALVERT ST",
        "MAILTOADD": "445 HOTEL CIR S SAN DIEGO, CA, 92108",
    }

    assert _situs_address(raw, None) == "25 S CALVERT ST"
    assert _mailing_address(raw, None) == "445 HOTEL CIR S SAN DIEGO, CA, 92108"


def test_scored_list_address_falls_back_to_outreach_brief_contacts() -> None:
    brief = {
        "contact_points": [
            {"kind": "mailing_address", "value": "2850 QUARRY LAKE DR #300, 21209"},
            {"kind": "situs_address", "value": "400 W FAYETTE ST"},
        ],
    }

    assert _situs_address({}, brief) == "400 W FAYETTE ST"
    assert _mailing_address({}, brief) == "2850 QUARRY LAKE DR #300, 21209"
