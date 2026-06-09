import numpy as np
import pytest

from app.config import get_settings
from app.pipeline.matching import (
    Ink, Candidate, ColorMatch, match_color, classify_quality, _delta_e_to_refs,
)


def _settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "http://x")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "x")
    monkeypatch.setenv("WORKER_SECRET", "x")
    get_settings.cache_clear()
    return get_settings()


def test_delta_e_to_refs_zero_for_same():
    refs = np.array([[50.0, 0.0, 0.0], [20.0, 0.0, 0.0]])
    d = _delta_e_to_refs((50.0, 0.0, 0.0), refs)
    assert d.shape == (2,)
    assert d[0] < 0.01
    assert d[1] > 1


def test_exact_color_is_rank_1_with_delta_e_near_zero(monkeypatch):
    s = _settings(monkeypatch)
    inks = [
        Ink(id="red", lab=(53.24, 80.09, 67.20)),
        Ink(id="blue", lab=(32.30, 79.19, -107.86)),
        Ink(id="gray", lab=(50.0, 0.0, 0.0)),
    ]
    m = match_color((53.24, 80.09, 67.20), inks, s)
    assert isinstance(m, ColorMatch)
    assert m.candidates[0].ink_id == "red"
    assert m.candidates[0].rank == 1
    assert m.candidates[0].delta_e < 0.5
    assert m.best_delta_e < 0.5
    assert m.match_quality == "excellent"
    assert m.needs_mix is False


def test_returns_top_n_sorted(monkeypatch):
    s = _settings(monkeypatch)
    inks = [Ink(id=f"i{i}", lab=(float(i * 5), 0.0, 0.0)) for i in range(10)]
    m = match_color((2.0, 0.0, 0.0), inks, s)
    assert len(m.candidates) == s.candidates_n
    des = [c.delta_e for c in m.candidates]
    assert des == sorted(des)
    assert [c.rank for c in m.candidates] == [1, 2, 3, 4, 5]


def test_poor_match_sets_needs_mix(monkeypatch):
    s = _settings(monkeypatch)
    # única tinta muy lejana del color objetivo
    inks = [Ink(id="far", lab=(95.0, -80.0, 80.0))]
    m = match_color((20.0, 50.0, -50.0), inks, s)
    assert m.match_quality == "poor"
    assert m.needs_mix is True


def test_classify_quality_thresholds(monkeypatch):
    s = _settings(monkeypatch)
    assert classify_quality(1.0, s) == "excellent"
    assert classify_quality(4.0, s) == "good"
    assert classify_quality(8.0, s) == "fair"
    assert classify_quality(15.0, s) == "poor"


def test_empty_inks_raises(monkeypatch):
    s = _settings(monkeypatch)
    with pytest.raises(ValueError):
        match_color((50.0, 0.0, 0.0), [], s)
