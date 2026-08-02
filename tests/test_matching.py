import numpy as np
import pytest

from app.config import get_settings
from app.pipeline.matching import (
    Ink, Candidate, ColorMatch, match_color, classify_quality, _delta_e_to_refs,
    consolidate_by_ink,
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


def _color(weight, role, lab=(50.0, 0.0, 0.0)):
    l, a, b = lab
    return {
        "rgb": {"r": 0, "g": 0, "b": 0},
        "hex": "#000000",
        "lab": {"l": l, "a": a, "b": b},
        "weight": weight,
        "role": role,
    }


def _match(ink_id, delta_e=0.5):
    return ColorMatch(
        candidates=[Candidate(ink_id=ink_id, delta_e=delta_e, rank=1)],
        best_delta_e=delta_e,
        match_quality="excellent",
        needs_mix=False,
    )


def test_consolidate_merges_same_ink(monkeypatch):
    s = _settings(monkeypatch)
    inks = [Ink(id="black", lab=(0.0, 0.0, 0.0)), Ink(id="white", lab=(100.0, 0.0, 0.0))]
    c1, c2 = _color(0.6, "dominant"), _color(0.2, "secondary")
    m = _match("black")
    out = consolidate_by_ink([(c1, m), (c2, m)], inks, s)
    assert len(out) == 1
    assert out[0][1].candidates[0].ink_id == "black"
    assert out[0][0]["weight"] == pytest.approx(0.8)


def test_consolidate_merges_perceptually_equal_inks(monkeypatch):
    s = _settings(monkeypatch)
    # dos negros casi idénticos de dos marcas (ΔE < 2.0)
    inks = [
        Ink(id="A_black", lab=(1.0, 0.0, 0.0)),
        Ink(id="B_black", lab=(1.5, 0.0, 0.0)),
        Ink(id="white", lab=(100.0, 0.0, 0.0)),
    ]
    c1, c2 = _color(0.5, "dominant"), _color(0.3, "secondary")
    out = consolidate_by_ink([(c1, _match("A_black")), (c2, _match("B_black"))], inks, s)
    assert len(out) == 1
    # gana el dominante (mayor peso) -> su tinta A_black
    assert out[0][1].candidates[0].ink_id == "A_black"
    assert out[0][0]["weight"] == pytest.approx(0.8)


def test_consolidate_keeps_distinct_inks(monkeypatch):
    s = _settings(monkeypatch)
    inks = [Ink(id="black", lab=(0.0, 0.0, 0.0)), Ink(id="white", lab=(100.0, 0.0, 0.0))]
    c1, c2 = _color(0.5, "dominant"), _color(0.4, "secondary")
    out = consolidate_by_ink([(c1, _match("black")), (c2, _match("white"))], inks, s)
    assert len(out) == 2


def test_consolidate_recomputes_role_to_dominant(monkeypatch):
    s = _settings(monkeypatch)  # dominant_weight = 0.15
    inks = [Ink(id="black", lab=(0.0, 0.0, 0.0))]
    c1, c2 = _color(0.08, "secondary"), _color(0.09, "secondary")
    m = _match("black")
    out = consolidate_by_ink([(c1, m), (c2, m)], inks, s)
    assert len(out) == 1
    assert out[0][0]["weight"] == pytest.approx(0.17)
    assert out[0][0]["role"] == "dominant"  # 0.17 >= 0.15


def test_consolidate_empty_returns_empty(monkeypatch):
    s = _settings(monkeypatch)
    assert consolidate_by_ink([], [], s) == []


def test_consolidate_keeps_secondary_when_below_threshold(monkeypatch):
    s = _settings(monkeypatch)  # dominant_weight = 0.15
    inks = [Ink(id="black", lab=(0.0, 0.0, 0.0))]
    c1, c2 = _color(0.05, "secondary"), _color(0.04, "secondary")
    m = _match("black")
    out = consolidate_by_ink([(c1, m), (c2, m)], inks, s)
    assert len(out) == 1
    assert out[0][0]["weight"] == pytest.approx(0.09)
    assert out[0][0]["role"] == "secondary"


def test_user_mix_candidate_keeps_its_flag(monkeypatch):
    """Una mezcla propia compite como una candidata más, y el resultado dice que
    lo es: sin el flag no habría forma de escribir el match_type correcto."""
    s = _settings(monkeypatch)
    inks = [
        Ink(id="ink-red", lab=(53.24, 80.09, 67.20)),
        Ink(id="mix-skin", lab=(50.0, 20.0, 20.0), is_user_mix=True),
    ]
    m = match_color((50.0, 20.0, 20.0), inks, s)
    assert m.candidates[0].ink_id == "mix-skin"
    assert m.candidates[0].is_user_mix is True
    assert m.candidates[1].is_user_mix is False


def test_ink_and_mix_compete_in_the_same_comparison(monkeypatch):
    """Botes y mezclas se ordenan juntos por ΔE, no en dos rondas separadas."""
    s = _settings(monkeypatch)
    inks = [
        Ink(id="mix-far", lab=(90.0, 0.0, 0.0), is_user_mix=True),
        Ink(id="ink-near", lab=(50.5, 0.0, 0.0)),
        Ink(id="mix-near", lab=(50.1, 0.0, 0.0), is_user_mix=True),
    ]
    m = match_color((50.0, 0.0, 0.0), inks, s)
    assert [c.ink_id for c in m.candidates] == ["mix-near", "ink-near", "mix-far"]


def test_consolidate_merges_an_ink_and_a_mix_of_the_same_color(monkeypatch):
    """La consolidación mira el color, no de dónde viene la candidata."""
    s = _settings(monkeypatch)
    inks = [
        Ink(id="black", lab=(1.0, 0.0, 0.0)),
        Ink(id="mix-black", lab=(1.5, 0.0, 0.0), is_user_mix=True),
    ]
    c1, c2 = _color(0.5, "dominant"), _color(0.3, "secondary")
    out = consolidate_by_ink(
        [(c1, _match("mix-black")), (c2, _match("black"))], inks, s
    )
    assert len(out) == 1
    assert out[0][1].candidates[0].ink_id == "mix-black"
