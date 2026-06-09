from parking_crew.regions import default_audit_inputs, priority_county_fips, region_name_for_fips


def test_priority_county_defaults_to_baltimore_city() -> None:
    fips = priority_county_fips()
    assert fips
    assert fips[0] == "24510"


def test_region_name_for_baltimore() -> None:
    assert "Baltimore" in region_name_for_fips("24510")


def test_default_audit_inputs_shape() -> None:
    inputs = default_audit_inputs("24510")
    assert inputs["county_fips"] == "24510"
    assert "region_name" in inputs
    assert inputs["lookback_hours"] == 168
