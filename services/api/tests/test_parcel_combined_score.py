from app.parcel_scored_list import _combined_score_value


def test_combined_score_averages_present_scores() -> None:
    assert _combined_score_value(90.0, 80.0, 70.0) == 80.0
    assert _combined_score_value(90.0, None, 70.0) == 80.0
    assert _combined_score_value(None, None, None) is None
