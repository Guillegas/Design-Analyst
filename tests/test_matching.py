from app.pipeline.matching import best_match, Ink


def test_exact_color_matches_its_ink_with_delta_e_near_zero():
    inks = [
        Ink(id="ink-red", lab=(53.24, 80.09, 67.20)),
        Ink(id="ink-blue", lab=(32.30, 79.19, -107.86)),
    ]
    match = best_match((53.24, 80.09, 67.20), inks)
    assert match.ink_id == "ink-red"
    assert match.delta_e < 0.5


def test_picks_nearest_of_several():
    inks = [
        Ink(id="ink-dark-gray", lab=(20.0, 0.0, 0.0)),
        Ink(id="ink-light-gray", lab=(80.0, 0.0, 0.0)),
    ]
    match = best_match((75.0, 0.0, 0.0), inks)
    assert match.ink_id == "ink-light-gray"


def test_empty_inks_raises():
    import pytest
    with pytest.raises(ValueError):
        best_match((50.0, 0.0, 0.0), [])
