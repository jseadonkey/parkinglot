from parking_ingestion.watech_parcels import (
    county_fips_to_watech_fips_nr,
    watech_fips_nr_to_county_fips,
)


def test_county_round_trip() -> None:
    assert county_fips_to_watech_fips_nr("53033") == "033"
    assert watech_fips_nr_to_county_fips("033") == "53033"
    assert watech_fips_nr_to_county_fips("1") == "53001"
