from app.parcel_scored_list import situs_address_approximate


def test_nominatim_road_only_is_approximate() -> None:
    props = {
        "ADDRESS_BACKFILL_SOURCE": "nominatim_centroid_fallback",
        "SITUS_ADDRESS": "Ramsay Way",
        "VISIT_ADDRESS": "Ramsay Way, KENT, WA 98032",
    }
    assert situs_address_approximate(props, situs_address="Ramsay Way") is True


def test_nominatim_with_house_number_not_approximate() -> None:
    props = {
        "ADDRESS_BACKFILL_SOURCE": "nominatim_centroid_fallback",
        "SITUS_ADDRESS": "620 West James Street",
    }
    assert situs_address_approximate(props, situs_address="620 West James Street") is False


def test_assessor_address_not_approximate() -> None:
    props = {"SITUS_ADDRESS": "100 Main St"}
    assert situs_address_approximate(props, situs_address="100 Main St") is False


def test_explicit_flag() -> None:
    props = {"SITUS_ADDRESS_APPROXIMATE": True, "SITUS_ADDRESS": "Ramsay Way"}
    assert situs_address_approximate(props, situs_address="Ramsay Way") is True
