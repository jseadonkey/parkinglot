from app.pipeline_gates import parcel_qualifies_for_human_gate


def test_parcel_qualifies_for_human_gate_both_floors() -> None:
    assert parcel_qualifies_for_human_gate(55.0, 52.0, min_entitlement=55.0, min_strategic=52.0)
    assert not parcel_qualifies_for_human_gate(54.9, 52.0, min_entitlement=55.0, min_strategic=52.0)
    assert not parcel_qualifies_for_human_gate(55.0, 51.9, min_entitlement=55.0, min_strategic=52.0)
